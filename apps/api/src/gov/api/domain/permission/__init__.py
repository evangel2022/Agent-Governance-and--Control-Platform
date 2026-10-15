"""Permission domain: the catalogue, and the rules a grant must satisfy."""

from gov.api.domain.permission.catalogue import (
    BY_NAME,
    CATALOGUE,
    PermissionDefinition,
    PermissionNameError,
    UnknownPermissionError,
    by_resource,
    get,
)
from gov.api.domain.permission.responsibility import is_accountable, validate_transfer
from gov.api.domain.permission.rules import (
    BUILTIN_ROLE_CODES,
    AssignmentState,
    PermissionRuleError,
    RoleStatus,
    ScopeType,
    assert_role_is_mutable,
    assignment_state,
    is_effective,
    validate_scope,
)

__all__ = [
    "BUILTIN_ROLE_CODES",
    "BY_NAME",
    "CATALOGUE",
    "AssignmentState",
    "PermissionDefinition",
    "PermissionNameError",
    "PermissionRuleError",
    "RoleStatus",
    "ScopeType",
    "UnknownPermissionError",
    "assert_role_is_mutable",
    "assignment_state",
    "by_resource",
    "get",
    "is_accountable",
    "is_effective",
    "validate_scope",
    "validate_transfer",
]
