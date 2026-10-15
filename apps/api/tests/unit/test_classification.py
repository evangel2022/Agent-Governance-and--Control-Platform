"""Unit tests for the data classification taxonomy (T118)."""

from __future__ import annotations

import pytest

from gov.api.domain.classification import (
    CLASSES,
    CONFIDENTIAL,
    INTERNAL,
    PUBLIC,
    RESTRICTED,
    UnknownClassificationError,
    highest,
    is_sensitive,
    validate_classification,
)


def test_taxonomy_has_the_four_levels_in_order() -> None:
    assert CLASSES == (PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED)


@pytest.mark.parametrize("value", list(CLASSES))
def test_declared_classes_validate(value: str) -> None:
    assert validate_classification(value) == value


@pytest.mark.parametrize("value", ["", "secret", "PUBLIC", "top_secret", None])
def test_undeclared_classes_are_rejected(value: object) -> None:
    with pytest.raises(UnknownClassificationError):
        validate_classification(value)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (PUBLIC, False),
        (INTERNAL, False),
        (CONFIDENTIAL, True),
        (RESTRICTED, True),
    ],
)
def test_only_confidential_and_restricted_are_sensitive(
    value: str, expected: bool
) -> None:
    assert is_sensitive(value) is expected


def test_highest_returns_the_most_sensitive_class() -> None:
    assert highest([PUBLIC, RESTRICTED, INTERNAL]) == RESTRICTED
    assert highest([PUBLIC]) == PUBLIC
    assert highest([CONFIDENTIAL, RESTRICTED]) == RESTRICTED


def test_highest_of_an_empty_set_is_an_error() -> None:
    with pytest.raises(ValueError, match="empty"):
        highest([])


def test_highest_rejects_an_undeclared_class() -> None:
    with pytest.raises(UnknownClassificationError):
        highest([PUBLIC, "secret"])
