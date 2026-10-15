package gov.authorization

test_deny_by_default_with_no_input if {
	got := decision with input as {}
	got.allowed == false
	got.sources == []
}

test_a_held_permission_is_granted if {
	got := decision with input as {
		"organisation_id": "org-1",
		"user_id": "user-1",
		"permission": "registry.write",
		"permissions": ["registry.read", "registry.write"],
		"requires_resource_accountability": false,
	}
	got.allowed == true
	got.sources == ["rbac.permission_granted"]
}

test_a_permission_the_caller_does_not_hold_is_denied if {
	got := decision with input as {
		"organisation_id": "org-1",
		"user_id": "user-1",
		"permission": "registry.retire",
		"permissions": ["registry.read", "registry.write"],
		"requires_resource_accountability": false,
	}
	got.allowed == false
}

test_accountability_denial_beats_the_grant if {
	got := decision with input as {
		"organisation_id": "org-1",
		"user_id": "user-1",
		"permission": "registry.write",
		"permissions": ["registry.write"],
		"requires_resource_accountability": true,
		"resource": {"type": "agent", "id": "agent-9", "owner_user_id": "user-2"},
	}
	got.allowed == false
	got.sources == ["abac.resource_accountability"]
}

test_the_accountable_person_is_granted if {
	got := decision with input as {
		"organisation_id": "org-1",
		"user_id": "user-1",
		"permission": "registry.write",
		"permissions": ["registry.write"],
		"requires_resource_accountability": true,
		"resource": {"type": "agent", "id": "agent-9", "owner_user_id": "user-1"},
	}
	got.allowed == true
}

test_a_holder_of_write_any_is_granted_on_another_persons_resource if {
	got := decision with input as {
		"organisation_id": "org-1",
		"user_id": "admin-1",
		"permission": "registry.write",
		"permissions": ["registry.write", "registry.write_any"],
		"requires_resource_accountability": true,
		"resource": {"type": "agent", "id": "agent-9", "owner_user_id": "user-2"},
	}
	got.allowed == true
}

test_write_any_alone_does_not_grant_the_underlying_permission if {
	# The exemption lifts the accountability rule; it does not substitute for
	# holding the permission the action requires.
	got := decision with input as {
		"organisation_id": "org-1",
		"user_id": "admin-1",
		"permission": "registry.retire",
		"permissions": ["registry.write_any"],
		"requires_resource_accountability": true,
		"resource": {"type": "agent", "id": "agent-9", "owner_user_id": "user-2"},
	}
	got.allowed == false
}

test_a_resource_scoped_action_without_a_resource_is_denied if {
	got := decision with input as {
		"organisation_id": "org-1",
		"user_id": "user-1",
		"permission": "registry.write",
		"permissions": ["registry.write"],
		"requires_resource_accountability": true,
		"resource": null,
	}
	got.allowed == false
	got.sources == ["abac.resource_missing"]
}

test_an_unrecognised_permission_is_denied if {
	got := decision with input as {
		"organisation_id": "org-1",
		"user_id": "user-1",
		"permission": "registry.teleport",
		"permissions": ["registry.read"],
	}
	got.allowed == false
}
