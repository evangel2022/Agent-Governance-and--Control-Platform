"""The data classification taxonomy.

FR-043 fixes four levels. Tool permissions, model usage restrictions and stored
sensitive fields must declare one of them, and the redaction layer keys off the
sensitive subset. The taxonomy lives in the domain layer because it is a
business rule, not a transport or storage concern.
"""

from __future__ import annotations

from collections.abc import Iterable

PUBLIC = "public"
INTERNAL = "internal"
CONFIDENTIAL = "confidential"
RESTRICTED = "restricted"

#: Ordered from least to most sensitive, which makes `highest` well defined.
CLASSES: tuple[str, ...] = (PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED)

#: Classes whose values must be encrypted and redacted from telemetry.
SENSITIVE_CLASSES: frozenset[str] = frozenset({CONFIDENTIAL, RESTRICTED})


class UnknownClassificationError(ValueError):
    """Raised when a value is not a declared classification."""


def validate_classification(value: str) -> str:
    """Return the classification if it is declared.

    Raises:
        UnknownClassificationError: when the value is not part of the taxonomy.
            An undeclared class is rejected rather than defaulted, because a
            silent default would weaken protection.
    """
    if value not in CLASSES:
        raise UnknownClassificationError(
            f"unknown data classification {value!r}; expected one of {', '.join(CLASSES)}"
        )
    return value


def is_sensitive(value: str) -> bool:
    """Return whether a classification requires encryption and redaction."""
    return validate_classification(value) in SENSITIVE_CLASSES


def highest(values: Iterable[str]) -> str:
    """Return the most sensitive classification in the set.

    Raises:
        ValueError: when the iterable is empty.
    """
    checked = [validate_classification(value) for value in values]
    if not checked:
        raise ValueError("cannot take the highest of an empty classification set")
    return max(checked, key=CLASSES.index)
