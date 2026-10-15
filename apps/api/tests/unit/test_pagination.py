"""Unit tests for pagination and UTC normalization helpers (T028)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from gov.api.interface.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    MIN_PAGE_SIZE,
    InvalidPageToken,
    clamp_page_size,
    decode_page_token,
    encode_page_token,
    paginate,
    to_utc,
    utc_now,
)


def test_page_token_round_trip() -> None:
    assert decode_page_token(encode_page_token(0)) == 0
    assert decode_page_token(encode_page_token(37)) == 37


def test_negative_offset_cannot_be_encoded() -> None:
    with pytest.raises(InvalidPageToken):
        encode_page_token(-1)


@pytest.mark.parametrize("token", ["", "not-a-token", "!!!"])
def test_malformed_tokens_are_rejected(token: str) -> None:
    with pytest.raises(InvalidPageToken):
        decode_page_token(token)


def test_token_with_invalid_payload_is_rejected() -> None:
    import base64

    bad = base64.urlsafe_b64encode(b'{"o": "many"}').decode().rstrip("=")
    with pytest.raises(InvalidPageToken):
        decode_page_token(bad)


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (None, DEFAULT_PAGE_SIZE),
        (0, MIN_PAGE_SIZE),
        (-5, MIN_PAGE_SIZE),
        (10, 10),
        (10_000, MAX_PAGE_SIZE),
    ],
)
def test_page_size_is_clamped(requested: int | None, expected: int) -> None:
    assert clamp_page_size(requested) == expected


def test_first_page_returns_a_next_token_when_more_items_remain() -> None:
    page = paginate(list(range(10)), page_size=4)
    assert page.items == (0, 1, 2, 3)
    assert page.total == 10
    assert page.next_page_token is not None


def test_walking_the_pages_visits_every_item_exactly_once() -> None:
    items = list(range(11))
    seen: list[int] = []
    token: str | None = None
    for _ in range(10):
        page = paginate(items, page_size=4, token=token)
        seen.extend(page.items)
        token = page.next_page_token
        if token is None:
            break
    assert seen == items
    assert token is None


def test_last_page_has_no_next_token() -> None:
    page = paginate(list(range(3)), page_size=10)
    assert page.next_page_token is None
    assert page.items == (0, 1, 2)


def test_empty_collection_pages_cleanly() -> None:
    page = paginate([], page_size=10)
    assert page.items == ()
    assert page.total == 0
    assert page.next_page_token is None


def test_utc_now_is_timezone_aware() -> None:
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_naive_datetime_is_treated_as_utc() -> None:
    naive = datetime(2026, 10, 13, 9, 0, 0)
    assert to_utc(naive) == datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)


def test_aware_datetime_is_converted_to_utc() -> None:
    shanghai = timezone(timedelta(hours=8))
    local = datetime(2026, 10, 13, 17, 0, 0, tzinfo=shanghai)
    assert to_utc(local) == datetime(2026, 10, 13, 9, 0, 0, tzinfo=UTC)
