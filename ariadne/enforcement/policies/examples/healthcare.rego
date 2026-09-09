# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
#
# Example domain policy: clinical support agents.
#
# Demonstrates the two shapes most deployments need beyond the defaults —
# a per-record data-egress rule, and a rule that keys off the calling agent's
# identity rather than the tool name.
#
#   opa run --server --addr :8181 ariadne/enforcement/policies/examples/healthcare.rego

package ariadne

import rego.v1

# Patient data may be read, never sent outside the clinical network.
external_sinks := ["email", "webhook", "upload", "s3", "slack", "sms"]

violations contains violation if {
	some sink in external_sinks
	contains(lower(input.tool_name), sink)
	contains(lower(json.marshal(input.arguments)), "patient")
	violation := {
		"rule": "no_phi_egress",
		"description": "Patient data may not leave the clinical network through this tool.",
		"action": "BLOCK",
		"matched_on": sprintf("tool_name~%s+arguments~patient", [sink]),
		"requires_hitl_token": false,
	}
}

# Prescription changes are clinician decisions, never agent decisions.
violations contains violation if {
	contains(lower(input.tool_name), "prescription")
	some verb in ["write", "update", "create", "cancel"]
	contains(lower(input.tool_name), verb)
	violation := {
		"rule": "prescription_requires_clinician",
		"description": "Prescription changes require a licensed clinician's approval token.",
		"action": "ESCALATE",
		"matched_on": "tool_name~prescription",
		"requires_hitl_token": true,
	}
}

# Research sub-agents are read-only regardless of what tools they discover.
violations contains violation if {
	startswith(lower(input.calling_agent_id), "research-")
	some verb in ["write", "delete", "update", "send", "create"]
	contains(lower(input.tool_name), verb)
	violation := {
		"rule": "research_agents_are_read_only",
		"description": "Research sub-agents hold read-only capability in this deployment.",
		"action": "BLOCK",
		"matched_on": sprintf("calling_agent_id~research-*+tool_name~%s", [verb]),
		"requires_hitl_token": false,
	}
}
