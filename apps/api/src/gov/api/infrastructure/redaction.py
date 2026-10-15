"""Sensitive-data redaction.

FR-040 and constitution Principle V require classified values to be redacted
from logs, traces, metrics and error messages. The protection is applied at the
boundary rather than at each call site, because "remember to redact" is exactly
the kind of rule that fails silently under deadline pressure.

Three boundaries are covered here:

1. `LogRedactionFilter` - a standard logging filter, so every record is cleaned
   as it is emitted, including structured extras.
2. `RedactingTelemetrySink` - wraps any telemetry sink, so attributes are
   cleaned before they leave the process. The concrete OpenTelemetry exporter is
   supplied as the wrapped sink, which keeps vendor wiring out of this rule.
3. `Redactor.redact` - used on error payloads so a problem detail cannot echo a
   classified value back to the caller.

Redaction is deliberately conservative: anything whose key looks sensitive is
replaced wholesale, and configured value patterns are scrubbed from free text.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

REDACTED = "[redacted]"

#: Keys whose values are never emitted, regardless of classification metadata.
DEFAULT_SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|credential|"
    r"private[_-]?key|iban|account[_-]?number|card[_-]?number|national[_-]?id)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    """One telemetry record: a span attribute set or a metric label set."""

    name: str
    attributes: Mapping[str, Any]


class TelemetrySink(Protocol):
    """Anything that ships telemetry out of the process."""

    def emit(self, event: TelemetryEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class Redactor:
    """Replaces sensitive values with a placeholder."""

    placeholder: str = REDACTED
    sensitive_keys: frozenset[str] = field(default_factory=frozenset)
    key_pattern: re.Pattern[str] = DEFAULT_SENSITIVE_KEY_PATTERN
    value_patterns: tuple[re.Pattern[str], ...] = ()

    def is_sensitive_key(self, key: str) -> bool:
        if key in self.sensitive_keys:
            return True
        return bool(self.key_pattern.search(key))

    def redact(self, value: Any, *, key: str | None = None) -> Any:
        """Return a copy of the value with sensitive content replaced.

        When `key` names a sensitive field the value is replaced wholesale, so
        no part of it can survive. Otherwise mappings and sequences are walked so
        nested structure is covered, and free text is scrubbed by pattern.
        """
        if key is not None and self.is_sensitive_key(key):
            return self.placeholder
        if isinstance(value, Mapping):
            return {str(k): self.redact(v, key=str(k)) for k, v in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, str | bytes):
            return [self.redact(item) for item in value]
        if isinstance(value, str):
            return self._redact_text(value)
        return value

    def _redact_text(self, value: str) -> str:
        result = value
        for pattern in self.value_patterns:
            result = pattern.sub(self.placeholder, result)
        return result


#: The redactor used when no project-specific configuration is supplied.
#:
#: It carries no explicit field names on purpose. Naming fields wholesale is how
#: a redaction default ends up destroying legitimate content (an audit `detail`
#: or a problem `detail` is prose, not a secret). Deployments extend this with
#: the field names their classification registry declares sensitive, and with
#: value patterns for structured identifiers.
DEFAULT_REDACTOR = Redactor()


class LogRedactionFilter(logging.Filter):
    """Redacts a record as it is emitted.

    The message is rendered and scrubbed, and any structured extra whose name
    looks sensitive is replaced.
    """

    def __init__(self, redactor: Redactor | None = None) -> None:
        super().__init__()
        self._redactor = redactor or DEFAULT_REDACTOR

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            return True
        record.msg = self._redactor.redact(rendered)
        record.args = ()
        for key, value in list(record.__dict__.items()):
            if key in _LOGGING_INTERNALS:
                continue
            if self._redactor.is_sensitive_key(key):
                record.__dict__[key] = self._redactor.redact(value, key=key)
        return True


#: Attributes the logging module owns. Redacting these would corrupt the record.
_LOGGING_INTERNALS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


@dataclass(frozen=True, slots=True)
class RedactingTelemetrySink:
    """Redacts telemetry attributes before delegating to the real sink."""

    inner: TelemetrySink
    redactor: Redactor = DEFAULT_REDACTOR

    def emit(self, event: TelemetryEvent) -> None:
        self.inner.emit(
            TelemetryEvent(
                name=event.name,
                attributes=self.redactor.redact(event.attributes),
            )
        )
