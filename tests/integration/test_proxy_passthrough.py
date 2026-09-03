# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""A clean run must pass through Ariadne unmodified.

Transparency is the deployment precondition: if the firewall alters or delays
legitimate traffic, nobody puts it in front of production agents.
"""

from __future__ import annotations

from tests.integration.conftest import Stack, call_tool, initialize_session, rendering

SESSION = "passthrough-session"
USER_REQUEST = "Summarise the quarterly sales report for the leadership team."

BENIGN_STEPS: list[tuple[str, dict[str, object]]] = [
    ("read_file", {"path": "/reports/q3_sales.pdf"}),
    ("extract_text", {"document_id": "q3_sales"}),
    ("summarize_text", {"text": "Q3 sales grew 12 percent"}),
    ("format_summary", {"style": "executive brief"}),
    ("echo", {"message": "summary complete"}),
]


def pin_benign(stack: Stack) -> None:
    stack.on_mission(
        *[rendering(index, name, args) for index, (name, args) in enumerate(BENIGN_STEPS, start=1)]
    )


class TestTransparency:
    async def test_handshake_result_is_relayed_verbatim(self, stack: Stack) -> None:
        response = await initialize_session(stack, SESSION, USER_REQUEST)
        assert response.status_code == 200
        body = response.json()
        assert body["result"]["serverInfo"]["name"] == "mock-upstream"
        assert body["result"]["protocolVersion"] == "2024-11-05"

    async def test_tool_discovery_is_relayed_verbatim(self, stack: Stack) -> None:
        await initialize_session(stack, SESSION, USER_REQUEST)
        response = await stack.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"X-Ariadne-Session-Id": SESSION},
        )
        tools = {tool["name"] for tool in response.json()["result"]["tools"]}
        assert tools == {"echo", "read_file"}

    async def test_clean_run_returns_exactly_what_upstream_returned(
        self, stack: Stack
    ) -> None:
        await initialize_session(stack, SESSION, USER_REQUEST)
        pin_benign(stack)

        for index, (name, args) in enumerate(BENIGN_STEPS, start=1):
            response = await call_tool(stack, SESSION, name, args, request_id=index)
            body = response.json()

            assert response.status_code == 200
            assert "error" not in body, f"step {index} ({name}) was not passed through: {body}"
            assert body["id"] == index
            assert body["result"]["isError"] is False
            assert body["result"]["content"][0]["text"] == f"echo:{args}"
            assert response.headers["X-Ariadne-Decision"] == "ALLOW"

    async def test_upstream_receives_the_original_request(self, stack: Stack) -> None:
        """Ariadne must not rewrite arguments on the way through."""
        await initialize_session(stack, SESSION, USER_REQUEST)
        pin_benign(stack)
        await call_tool(stack, SESSION, "echo", {"message": "hello", "count": 3})

        forwarded = [
            call for call in stack.upstream.state.calls if call.get("method") == "tools/call"
        ]
        assert forwarded[-1]["params"]["arguments"] == {"message": "hello", "count": 3}

    async def test_decision_headers_are_present_for_observability(
        self, stack: Stack
    ) -> None:
        await initialize_session(stack, SESSION, USER_REQUEST)
        pin_benign(stack)
        response = await call_tool(stack, SESSION, "read_file", {"path": "/reports/q3_sales.pdf"})

        assert response.headers["X-Ariadne-Session-Id"] == SESSION
        assert response.headers["X-Ariadne-Decision"] == "ALLOW"
        assert float(response.headers["X-Ariadne-Drift-Score"]) < 40.0
        assert response.headers["X-Ariadne-Node-Id"]


class TestAuditTrail:
    async def test_clean_run_is_recorded_as_CLEAN(self, stack: Stack) -> None:
        await initialize_session(stack, SESSION, USER_REQUEST)
        pin_benign(stack)
        for index, (name, args) in enumerate(BENIGN_STEPS, start=1):
            await call_tool(stack, SESSION, name, args, request_id=index)

        end = await stack.client.post(f"/mcp/sessions/{SESSION}/end")
        assert end.status_code == 200
        assert end.json()["final_status"] == "CLEAN"

        await stack.app.state.recorder.flush()
        run = await stack.client.get(f"/api/v1/runs/{SESSION}")
        assert run.status_code == 200
        payload = run.json()
        assert payload["run"]["final_status"] == "CLEAN"
        assert payload["run"]["total_steps"] == len(BENIGN_STEPS)
        assert payload["run"]["blocked_count"] == 0
        assert len(payload["events"]) == len(BENIGN_STEPS)
        assert {event["enforcement_action"] for event in payload["events"]} == {"ALLOW"}

    async def test_run_appears_in_the_run_list(self, stack: Stack) -> None:
        await initialize_session(stack, SESSION, USER_REQUEST)
        pin_benign(stack)
        await call_tool(stack, SESSION, "echo", {"message": "hi"})
        await stack.client.post(f"/mcp/sessions/{SESSION}/end")

        listing = await stack.client.get("/api/v1/runs")
        assert listing.status_code == 200
        assert any(item["session_id"] == SESSION for item in listing.json()["items"])

    async def test_provenance_graph_is_built_for_a_clean_run(self, stack: Stack) -> None:
        await initialize_session(stack, SESSION, USER_REQUEST)
        pin_benign(stack)
        for index, (name, args) in enumerate(BENIGN_STEPS[:3], start=1):
            await call_tool(stack, SESSION, name, args, request_id=index)

        graph = (await stack.client.get(f"/api/v1/runs/{SESSION}/graph")).json()
        types = [node["node_type"] for node in graph["nodes"]]

        assert types.count("user_request") == 1
        assert types.count("tool_call") == 3
        assert types.count("tool_result") == 3
        assert graph["root_cause_node_id"] is None
        assert all(node["enforcement_action"] != "PENDING" for node in graph["nodes"]
                   if node["node_type"] == "tool_call")


class TestOperationalEndpoints:
    async def test_health_reports_ok(self, stack: Stack) -> None:
        response = await stack.client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    async def test_status_exposes_the_active_backends(self, stack: Stack) -> None:
        payload = (await stack.client.get("/status")).json()
        assert payload["graph_backend"] == "networkx"
        assert payload["policy_backend"] == "builtin"
        assert payload["fail_mode"] == "FAIL_CLOSED"
        assert payload["drift_thresholds"] == {"warn": 40.0, "escalate": 65.0, "block": 85.0}

    async def test_openapi_documents_every_surface(self, stack: Stack) -> None:
        schema = (await stack.client.get("/openapi.json")).json()
        paths = set(schema["paths"])
        assert "/mcp" in paths
        assert "/api/v1/runs" in paths
        assert "/api/v1/policies" in paths
        assert "/health" in paths
        assert "/metrics" in paths

    async def test_metrics_endpoint_serves_prometheus_text(self, stack: Stack) -> None:
        response = await stack.client.get("/metrics")
        assert response.status_code == 200
        assert "ariadne_" in response.text or "http_request" in response.text


class TestUpstreamFailures:
    async def test_unknown_method_error_is_relayed_not_swallowed(
        self, stack: Stack
    ) -> None:
        await initialize_session(stack, SESSION, USER_REQUEST)
        response = await stack.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 9, "method": "resources/list", "params": {}},
            headers={"X-Ariadne-Session-Id": SESSION},
        )
        assert response.json()["error"]["code"] == -32601

    async def test_malformed_body_is_rejected_cleanly(self, stack: Stack) -> None:
        response = await stack.client.post(
            "/mcp", content=b"{not json", headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == -32700

    async def test_missing_method_is_rejected_as_invalid_request(self, stack: Stack) -> None:
        response = await stack.client.post("/mcp", json={"jsonrpc": "2.0", "id": 1})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == -32600
