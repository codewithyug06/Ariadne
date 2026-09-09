# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
#
# Ariadne default hard policy.
#
# Load into OPA:
#   opa run --server --addr :8181 ariadne/enforcement/policies/
# Then set OPA_URL=http://localhost:8181 so the hard layer queries this
# instead of its built-in Python mirror of the same rules.
#
# Decision document returned at /v1/data/ariadne/allow:
#   { "allow": bool, "violations": [ {rule, description, action, matched_on,
#                                     requires_hitl_token} ] }

package ariadne

import rego.v1

default allow := false

# The call is permitted when nothing denies or escalates it.
allow if count(violations) == 0

# ---------------------------------------------------------------------------
# payment_requires_hitl
# ---------------------------------------------------------------------------
payment_patterns := ["pay", "charge", "transfer", "invoice", "wire", "refund", "checkout"]

violations contains violation if {
	some pattern in payment_patterns
	contains(lower(input.tool_name), pattern)
	violation := {
		"rule": "payment_requires_hitl",
		"description": "Money-moving tools always require an explicit human approval token.",
		"action": "ESCALATE",
		"matched_on": sprintf("tool_name~%s", [pattern]),
		"requires_hitl_token": true,
	}
}

# ---------------------------------------------------------------------------
# no_delete_without_confirmation
# ---------------------------------------------------------------------------
delete_patterns := ["delete", "drop", "remove", "destroy", "purge", "truncate"]

violations contains violation if {
	some pattern in delete_patterns
	contains(lower(input.tool_name), pattern)
	violation := {
		"rule": "no_delete_without_confirmation",
		"description": "Destructive operations require confirmation before reaching the tool.",
		"action": "ESCALATE",
		"matched_on": sprintf("tool_name~%s", [pattern]),
		"requires_hitl_token": true,
	}
}

violations contains violation if {
	some pattern in ["drop table", "rm -rf", "delete from", "--force"]
	contains(lower(json.marshal(input.arguments)), pattern)
	violation := {
		"rule": "no_delete_without_confirmation",
		"description": "Destructive payload detected in tool arguments.",
		"action": "ESCALATE",
		"matched_on": sprintf("arguments~%s", [pattern]),
		"requires_hitl_token": true,
	}
}

# ---------------------------------------------------------------------------
# no_privilege_escalation
# ---------------------------------------------------------------------------
privilege_patterns := [
	"grant_role", "add_admin", "set_permission", "escalate", "assume_role",
	"sudo", "chmod", "chown", "attach_policy", "add_user_to_group",
]

violations contains violation if {
	some pattern in privilege_patterns
	contains(lower(input.tool_name), pattern)
	violation := {
		"rule": "no_privilege_escalation",
		"description": "An agent may not grant itself roles, permissions or admin access.",
		"action": "BLOCK",
		"matched_on": sprintf("tool_name~%s", [pattern]),
		"requires_hitl_token": false,
	}
}

violations contains violation if {
	some pattern in ["admin group", "role=admin", "privilege", "is_admin"]
	contains(lower(json.marshal(input.arguments)), pattern)
	violation := {
		"rule": "no_privilege_escalation",
		"description": "Tool arguments request elevated privileges.",
		"action": "BLOCK",
		"matched_on": sprintf("arguments~%s", [pattern]),
		"requires_hitl_token": false,
	}
}

# ---------------------------------------------------------------------------
# disallowed_domains — edit this list for your deployment.
# ---------------------------------------------------------------------------
disallowed_tools := ["internal_admin_console", "billing_root", "cluster_delete"]

violations contains violation if {
	some tool in disallowed_tools
	contains(lower(input.tool_name), tool)
	violation := {
		"rule": "disallowed_domains",
		"description": "Tool is on the deployment deny list and is never callable via Ariadne.",
		"action": "BLOCK",
		"matched_on": sprintf("tool_name~%s", [tool]),
		"requires_hitl_token": false,
	}
}
