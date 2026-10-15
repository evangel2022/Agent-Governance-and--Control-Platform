package gov.authorization

import future.keywords.in

# Authorization decisions for the Permission Center.
#
# The control plane resolves the caller's effective permissions and the facts
# about the resource, and passes them in. This bundle decides; it never reaches
# for data itself, so a decision can be replayed from its input alone.
#
# input = {
#   "organisation_id": string,
#   "user_id":         string,
#   "permission":      string,      # the action being attempted
#   "requested_at":    string,      # RFC 3339, or null
#   "permissions":     [string],    # the caller's effective permissions
#   "roles":           [ {"id", "name"} ],
#   "requires_resource_accountability": boolean,   # ABAC switch, set by the caller
#   "resource":        {"type", "id", "owner_user_id"} | null,
#   "context":         object,
# }

# Deny by default. This is the most important line in the file: an action nobody
# has granted is refused, including when the input is empty or malformed.
default decision := {
	"allowed": false,
	"reason": "deny by default: no rule grants this action",
	"sources": [],
}

decision := {"allowed": false, "reason": reason, "sources": sources} if {
	count(violations) > 0
	sources := source_names(violations)
	reason := sprintf("denied by %v", [sources])
}

decision := {"allowed": true, "reason": reason, "sources": sources} if {
	count(violations) == 0
	count(grants) > 0
	sources := source_names(grants)
	reason := sprintf("granted by %v", [sources])
}

# A permission the caller actually holds.
grants contains {"rule": "rbac.permission_granted", "detail": permission} if {
	some permission in object.get(input, "permissions", [])
	permission == input.permission
}

# Attribute-based rule: an action that affects a single resource requiring
# accountability may only be taken by the person accountable for it. A holder of
# the permission who is not accountable is therefore refused - an explicit denial
# that beats the broader grant, which is what makes the outcome deterministic.
#
# The exemption is a permission, not a role: only `registry.write_any` lifts the
# rule, so who may act on any Agent is something the platform grants explicitly
# rather than something the control plane decides while assembling the input.
violations contains {"rule": "abac.resource_accountability", "detail": resource_id} if {
	object.get(input, "requires_resource_accountability", false) == true
	resource := object.get(input, "resource", null)
	resource != null
	resource.owner_user_id != input.user_id
	not "registry.write_any" in object.get(input, "permissions", [])
	resource_id := resource.id
}

# A resource-scoped action with no resource to check is a malformed request, and
# a malformed request is refused rather than treated as unscoped.
violations contains {"rule": "abac.resource_missing", "detail": null} if {
	object.get(input, "requires_resource_accountability", false) == true
	object.get(input, "resource", null) == null
}

source_names(entries) := names if {
	names := [entry.rule | some entry in entries]
}
