"""Data classification taxonomy (FR-043)."""

from gov.api.domain.classification.taxonomy import (
    CLASSES,
    CONFIDENTIAL,
    INTERNAL,
    PUBLIC,
    RESTRICTED,
    SENSITIVE_CLASSES,
    UnknownClassificationError,
    highest,
    is_sensitive,
    validate_classification,
)

__all__ = [
    "CLASSES",
    "CONFIDENTIAL",
    "INTERNAL",
    "PUBLIC",
    "RESTRICTED",
    "SENSITIVE_CLASSES",
    "UnknownClassificationError",
    "highest",
    "is_sensitive",
    "validate_classification",
]
