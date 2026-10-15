package gov

test_deny_by_default if {
	got := decision with input as {
		"organisation_id": "o1",
		"agent_version_id": "av1",
		"tool_id": "t1",
		"environment": "prod",
		"risk_level": "low",
		"policies": [],
	}
	got.effect == "deny"
	count(got.matched) == 0
}

test_allow_when_a_policy_grants if {
	got := decision with input as {
		"organisation_id": "o1",
		"agent_version_id": "av1",
		"tool_id": "t1",
		"environment": "prod",
		"risk_level": "low",
		"policies": [{
			"id": "p1",
			"version_id": "pv1",
			"effect": "allow",
			"agent_version_id": null,
			"tool_id": "t1",
			"environment": "prod",
			"valid_from": null,
			"valid_until": null,
		}],
	}
	got.effect == "allow"
	got.matched == ["pv1"]
}

test_explicit_deny_beats_broader_allow if {
	got := decision with input as {
		"organisation_id": "o1",
		"agent_version_id": "av1",
		"tool_id": "t1",
		"environment": "prod",
		"risk_level": "low",
		"policies": [
			{"id": "p1", "version_id": "pv1", "effect": "allow", "agent_version_id": null, "tool_id": "t1", "environment": "prod", "valid_from": null, "valid_until": null},
			{"id": "p2", "version_id": "pv2", "effect": "deny", "agent_version_id": "av1", "tool_id": "t1", "environment": "prod", "valid_from": null, "valid_until": null},
		],
	}
	got.effect == "deny"
	got.matched == ["pv2"]
}

test_policy_for_another_agent_does_not_apply if {
	got := decision with input as {
		"organisation_id": "o1",
		"agent_version_id": "av1",
		"tool_id": "t1",
		"environment": "prod",
		"risk_level": "low",
		"policies": [{
			"id": "p1",
			"version_id": "pv1",
			"effect": "allow",
			"agent_version_id": "av-other",
			"tool_id": "t1",
			"environment": "prod",
			"valid_from": null,
			"valid_until": null,
		}],
	}
	got.effect == "deny"
}

test_expired_policy_does_not_apply if {
	got := decision with input as {
		"organisation_id": "o1",
		"agent_version_id": "av1",
		"tool_id": "t1",
		"environment": "prod",
		"risk_level": "low",
		"at": "2026-06-01T00:00:00Z",
		"policies": [{
			"id": "p1",
			"version_id": "pv1",
			"effect": "allow",
			"agent_version_id": null,
			"tool_id": "t1",
			"environment": "prod",
			"valid_from": null,
			"valid_until": "2026-01-01T00:00:00Z",
		}],
	}
	got.effect == "deny"
}

test_policy_for_another_environment_does_not_apply if {
	got := decision with input as {
		"organisation_id": "o1",
		"agent_version_id": "av1",
		"tool_id": "t1",
		"environment": "prod",
		"risk_level": "low",
		"policies": [{
			"id": "p1",
			"version_id": "pv1",
			"effect": "allow",
			"agent_version_id": null,
			"tool_id": "t1",
			"environment": "staging",
			"valid_from": null,
			"valid_until": null,
		}],
	}
	got.effect == "deny"
}

test_high_risk_requires_approval if {
	requires_approval with input as {"risk_level": "high"}
}

test_medium_risk_does_not_require_approval if {
	not requires_approval with input as {"risk_level": "medium"}
}
