package gov

import future.keywords.in

# Policy evaluation for Agent tool invocation.
#
# input = {
#   "organisation_id":  string,
#   "actor":            string,        # identity that requested the invocation
#   "agent_version_id": string,
#   "tool_id":          string,
#   "environment":      string,        # e.g. "prod", "staging"
#   "risk_level":       string,        # low | medium | high | critical
#   "at":               string,        # RFC 3339 instant, or null
#   "policies": [ {
#       "id", "version_id", "effect": "allow" | "deny",
#       "agent_version_id": string | null,
#       "tool_id": string | null,
#       "environment": string,
#       "valid_from": string | null,
#       "valid_until": string | null
#   } ]
# }

# Fail closed: with no matching policy the invocation is denied. This is the
# single most important property of the bundle (constitution Principle III).
default decision := {
	"effect": "deny",
	"reason": "deny by default: no policy grants this invocation",
	"matched": [],
}

decision := resolved if {
	count(matched) > 0
	resolved := resolve(matched)
}

matched := [p |
	some p in object.get(input, "policies", [])
	agent_in_scope(p)
	tool_in_scope(p)
	environment_matches(p)
	valid_now(p)
]

# A policy scoped to no agent applies to every agent; a policy scoped to an
# agent version applies only to that version.
agent_in_scope(p) if {
	object.get(p, "agent_version_id", null) == null
}

agent_in_scope(p) if {
	object.get(p, "agent_version_id", null) == input.agent_version_id
}

tool_in_scope(p) if {
	object.get(p, "tool_id", null) == null
}

tool_in_scope(p) if {
	object.get(p, "tool_id", null) == input.tool_id
}

environment_matches(p) if {
	object.get(p, "environment", "") == input.environment
}

valid_now(p) if {
	within(object.get(p, "valid_from", null), object.get(p, "valid_until", null), object.get(input, "at", null))
}

within(from, until, at) if {
	from == null
	until == null
}

within(from, until, at) if {
	from != null
	at != null
	until == null
	time.parse_rfc3339_ns(at) >= time.parse_rfc3339_ns(from)
}

within(from, until, at) if {
	from == null
	until != null
	at != null
	time.parse_rfc3339_ns(at) <= time.parse_rfc3339_ns(until)
}

within(from, until, at) if {
	from != null
	until != null
	at != null
	time.parse_rfc3339_ns(at) >= time.parse_rfc3339_ns(from)
	time.parse_rfc3339_ns(at) <= time.parse_rfc3339_ns(until)
}

# An explicit denial always wins over any broader grant, so the outcome is
# deterministic and cannot be widened by adding an allow policy.
resolve(matched) := {"effect": "deny", "reason": reason, "matched": ids} if {
	denies := [p | some p in matched; p.effect == "deny"]
	count(denies) > 0
	ids := [p.version_id | some p in denies]
	reason := sprintf("explicit deny by policy versions %v", [ids])
}

resolve(matched) := {"effect": "allow", "reason": reason, "matched": ids} if {
	allows := [p | some p in matched; p.effect == "allow"]
	count(allows) > 0
	ids := [p.version_id | some p in allows]
	reason := sprintf("allowed by policy versions %v", [ids])
}

# High and critical risk operations can never be authorised by policy alone.
requires_approval if {
	input.risk_level == "high"
}

requires_approval if {
	input.risk_level == "critical"
}
