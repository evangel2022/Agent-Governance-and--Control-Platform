"""Opaque, cursor-style pagination for list endpoints.

Tokens are base64url-encoded JSON carrying an offset. They are deliberately
opaque to clients, and a malformed token is rejected rather than silently
treated as "start from the beginning", which would hide client bugs and make
audit queries non-reproducible.

All emitted timestamps in this module are UTC, matching the FR-039 and
constitution expectations that recorded times are unambiguous and comparable
across a distributed deployment.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

MIN_PAGE_SIZE = 1
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50


class InvalidPageToken(ValueError):
    """Raised when a page token cannot be decoded."""


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(tz=UTC)


def to_utc(value: datetime) -> datetime:
    """Return the value normalized to UTC.

    A naive datetime is assumed to be UTC rather than local time, because the
    platform must not depend on the host's timezone configuration.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def encode_page_token(offset: int) -> str:
    """Encode an offset into an opaque page token."""
    if offset < 0:
        raise InvalidPageToken("offset must not be negative")
    raw = json.dumps({"o": offset}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_page_token(token: str) -> int:
    """Decode a page token into an offset.

    Raises:
        InvalidPageToken: if the token is not a well-formed token produced by
            encode_page_token.
    """
    if not token:
        raise InvalidPageToken("empty page token")
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        offset = payload["o"]
    except (binascii.Error, UnicodeDecodeError, ValueError, KeyError, TypeError) as exc:
        raise InvalidPageToken(f"malformed page token: {token!r}") from exc
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise InvalidPageToken(f"invalid offset in page token: {token!r}")
    return offset


def clamp_page_size(page_size: int | None) -> int:
    """Clamp a requested page size into the supported range."""
    if page_size is None:
        return DEFAULT_PAGE_SIZE
    if page_size < MIN_PAGE_SIZE:
        return MIN_PAGE_SIZE
    if page_size > MAX_PAGE_SIZE:
        return MAX_PAGE_SIZE
    return page_size


@dataclass(frozen=True)
class Page[T]:
    """One page of results plus the token needed to fetch the next page."""

    items: tuple[T, ...]
    total: int
    next_page_token: str | None


def paginate[T](
    items: Sequence[T],
    page_size: int | None = None,
    token: str | None = None,
) -> Page[T]:
    """Return one page of items starting at the position named by the token."""
    size = clamp_page_size(page_size)
    offset = decode_page_token(token) if token else 0
    total = len(items)
    window = items[offset : offset + size]
    next_offset = offset + len(window)
    next_token = encode_page_token(next_offset) if next_offset < total else None
    return Page(items=tuple(window), total=total, next_page_token=next_token)
