# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Hard policy, human-in-the-loop escalation, and runtime policy management."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from ariadne.config import FailMode, Settings
from tests.integration.conftest import Stack, call_tool, initialize_session, rendering

SESSION = "enforcement-session"
USER_REQUEST = "Reconcile the outstanding supplier invoices and report the totals."


class TestHardPolicyBlocking:
    async def test_privilege_escalation_is_blocked_regardless_of_drift(
        self, stack: Stack
    ) -> None:
        """Pinned on-mission, so only the hard layer can stop this."""
        await initialize_session(stack, SESSION, USER_REQUEST)
        args = {"user": "agent-svc", "role": "admin"}
        stack.on_mission(rendering(1, "grant_role", args))

        response = await call_tool(stack, SESSION, "grant_role", args)

        assert response.headers["X-Ariadne-Decision"] == "BLOCK"
        assert response.headers["X-Ariadne-Layer"] == "hard"
        assert float(response.headers["X-Ariadne-Drift-Score"]) < 40.0
        details = response.json()["error"]["data"]["ariadne"]
        assert details["triggered_rule"] == "no_privilege_escalation"

    async def test_disallowed_payload_is_caught_under_a_benign_tool_name(
        self, stack: Stack
    ) -> None:
        await initialize_session(stack, SESSION, USER_REQUEST)
        args = {"sql": "DROP TABLE invoices"}
        stack.on_mission(rendering(1, "run_query", args))

        response = await call_tool(stack, SESSION, "run_query", args)
        assert response.headers["X-Ariadne-Decision"] == "ESCALATE"

    async def test_session_budget_blocks_a_runaway_loop(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        # Exercised directly against the engine: driving 200 HTTP calls would
        # add a minute to the suite to prove an arithmetic comparison.
        from ariadne.enforcement.engine import HybridEnforcementEngine  # noqa: PLC0415
        from ariadne.proxy.schemas import ToolCall  # noqa: PLC0415

        settings = Settings(
            DATABASE_URL=f"sqlite+aiosqlite:///{tmp_path.as_posix()}/t.db",
            MAX_TOOL_CALLS_PER_SESSION=3,
        )
        engine = HybridEnforcementEngine(settings=settings)
        decision = await engine.decide(
            ToolCall(session_id=SESSION, step_index=4, tool_name="list_files"),
            None,
            tool_call_count=4,
        )
        assert decision.action == "BLOCK"
        assert decision.triggered_rule == "max_tool_calls_per_session"
        await engine.aclose()


class TestHumanInTheLoop:
    async def test_escalation_without_a_webhook_is_denied(self, stack: Stack) -> None:
        """Fail-safe: with nobody to ask, an escalation must not proceed."""
        await initialize_session(stack, SESSION, USER_REQUEST)
        args = {"invoice": "INV-2291", "amount": "4200.00"}
        stack.on_mission(rendering(1, "make_payment", args))

        response = await call_tool(stack, SESSION, "make_payment", args)

        assert response.headers["X-Ariadne-Decision"] == "ESCALATE"
        assert response.json()["error"]["code"] == -32002
        forwarded = [c for c in stack.upstream.state.calls if c.get("method") == "tools/call"]
        assert not forwarded, "an unapproved escalation must never reach the tool"

    async def test_approved_escalation_proceeds_to_the_tool(
        self, stack: Stack
    ) -> None:
        """The webhook approves out-of-band; the call then completes normally."""
        approvals: list[dict[str, object]] = []

        async def approve(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            approvals.append(payload)
            # Approve asynchronously, exactly as a human console would.
            asyncio.get_running_loop().call_soon(
                stack.app.state.proxy.approvals.resolve, str(payload["approval_id"]), True
            )
            return httpx.Response(200, json={"received": True})

        stack.settings.hitl_webhook_url = "http://hitl.test/approve"
        stack.app.state.proxy._client = httpx.AsyncClient(  # noqa: SLF001
            transport=_RoutingTransport(approve, stack)
        )

        await initialize_session(stack, SESSION, USER_REQUEST)
        args = {"invoice": "INV-2291", "amount": "4200.00"}
        stack.on_mission(rendering(1, "make_payment", args))

        response = await call_tool(stack, SESSION, "make_payment", args)

        assert approvals, "the HITL webhook was never called"
        assert approvals[0]["tool_name"] == "make_payment"
        assert response.headers.get("X-Ariadne-Approved") == "true"
        assert "error" not in response.json()

    async def test_denied_escalation_is_refused(self, stack: Stack) -> None:
        async def deny(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            asyncio.get_running_loop().call_soon(
                stack.app.state.proxy.approvals.resolve, str(payload["approval_id"]), False
            )
            return httpx.Response(200, json={"received": True})

        stack.settings.hitl_webhook_url = "http://hitl.test/approve"
        stack.app.state.proxy._client = httpx.AsyncClient(  # noqa: SLF001
            transport=_RoutingTransport(deny, stack)
        )

        await initialize_session(stack, SESSION, USER_REQUEST)
        args = {"invoice": "INV-2291", "amount": "4200.00"}
        stack.on_mission(rendering(1, "make_payment", args))

        response = await call_tool(stack, SESSION, "make_payment", args)
        assert response.json()["error"]["code"] == -32002

    async def test_escalation_times_out_into_a_denial(self, stack: Stack) -> None:
        async def never_answer(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"received": True})

        stack.settings.hitl_webhook_url = "http://hitl.test/approve"
        stack.settings.hitl_timeout_seconds = 0.2
        stack.app.state.proxy._client = httpx.AsyncClient(  # noqa: SLF001
            transport=_RoutingTransport(never_answer, stack)
        )

        await initialize_session(stack, SESSION, USER_REQUEST)
        args = {"invoice": "INV-9", "amount": "10.00"}
        stack.on_mission(rendering(1, "make_payment", args))

        response = await call_tool(stack, SESSION, "make_payment", args)
        assert response.json()["error"]["code"] == -32002

    async def test_approval_endpoint_rejects_unknown_tokens(self, stack: Stack) -> None:
        response = await stack.client.post("/mcp/hitl/not-a-real-approval")
        assert response.status_code == 404


class TestFailModes:
    async def test_fail_closed_blocks_when_the_pipeline_raises(
        self, stack: Stack, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await initialize_session(stack, SESSION, USER_REQUEST)

        def explode(*args: object, **kwargs: object) -> None:
            raise RuntimeError("embedding backend unavailable")

        monkeypatch.setattr(stack.app.state.embedder, "embed", explode)
        response = await call_tool(stack, SESSION, "echo", {"message": "hi"})

        assert response.headers["X-Ariadne-Decision"] == "BLOCK"
        assert "internal error" in response.json()["error"]["message"].lower()

    async def test_fail_open_forwards_when_the_pipeline_raises(
        self, stack: Stack, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await initialize_session(stack, SESSION, USER_REQUEST)
        stack.settings.fail_mode = FailMode.FAIL_OPEN

        def explode(*args: object, **kwargs: object) -> None:
            raise RuntimeError("embedding backend unavailable")

        monkeypatch.setattr(stack.app.state.embedder, "embed", explode)
        response = await call_tool(stack, SESSION, "echo", {"message": "hi"})

        assert response.headers["X-Ariadne-Decision"] == "ALLOW"
        assert "error" not in response.json()


class TestPolicyManagement:
    async def test_default_rules_are_listed(self, stack: Stack) -> None:
        payload = (await stack.client.get("/api/v1/policies")).json()
        names = {rule["name"] for rule in payload["items"]}
        assert {"payment_requires_hitl", "no_privilege_escalation"} <= names
        assert payload["backend"] == "builtin"

    async def test_new_rule_takes_effect_on_the_next_call(self, stack: Stack) -> None:
        created = await stack.client.post(
            "/api/v1/policies",
            json={
                "name": "no_external_uploads",
                "description": "This deployment never uploads to third-party storage.",
                "action": "BLOCK",
                "tool_name_patterns": ["upload_to_"],
                "argument_patterns": [],
                "requires_hitl_token": False,
            },
        )
        assert created.status_code == 201

        await initialize_session(stack, SESSION, USER_REQUEST)
        args = {"bucket": "public"}
        stack.on_mission(rendering(1, "upload_to_s3", args))

        response = await call_tool(stack, SESSION, "upload_to_s3", args)
        assert response.headers["X-Ariadne-Decision"] == "BLOCK"
        assert response.json()["error"]["data"]["ariadne"]["triggered_rule"] == "no_external_uploads"

    async def test_deleted_rule_stops_applying(self, stack: Stack) -> None:
        deleted = await stack.client.delete("/api/v1/policies/payment_requires_hitl")
        assert deleted.status_code == 204

        await initialize_session(stack, SESSION, USER_REQUEST)
        args = {"invoice": "INV-1", "amount": "5.00"}
        stack.on_mission(rendering(1, "make_payment", args))

        response = await call_tool(stack, SESSION, "make_payment", args)
        assert response.headers["X-Ariadne-Decision"] == "ALLOW"

    async def test_deleting_an_unknown_rule_is_404(self, stack: Stack) -> None:
        assert (await stack.client.delete("/api/v1/policies/nope")).status_code == 404


class TestComplianceExport:
    async def test_report_covers_decisions_and_obligations(self, stack: Stack) -> None:
        await initialize_session(stack, SESSION, USER_REQUEST)
        args = {"user": "agent-svc", "role": "admin"}
        stack.on_mission(rendering(1, "grant_role", args))
        await call_tool(stack, SESSION, "grant_role", args)
        await stack.client.post(f"/mcp/sessions/{SESSION}/end")

        report = (await stack.client.get(f"/api/v1/runs/{SESSION}/report")).json()

        assert report["run"]["final_status"] == "BLOCKED"
        assert len(report["events"]) == 1
        assert report["root_cause_findings"], "a blocked run must carry a root-cause finding"
        articles = {entry["article"] for entry in report["eu_ai_act_mapping"]}
        assert articles == {"Article 9", "Article 13", "Article 14"}

    async def test_markdown_export_is_a_readable_document(self, stack: Stack) -> None:
        await initialize_session(stack, SESSION, USER_REQUEST)
        stack.on_mission(rendering(1, "echo", {"message": "hi"}))
        await call_tool(stack, SESSION, "echo", {"message": "hi"})
        await stack.client.post(f"/mcp/sessions/{SESSION}/end")

        response = await stack.client.get(
            f"/api/v1/runs/{SESSION}/report", params={"format": "markdown"}
        )
        assert response.status_code == 200
        assert "text/markdown" in response.headers["content-type"]
        body = response.text
        assert "# Ariadne Compliance Report" in body
        assert "## 6. EU AI Act evidence mapping" in body
        assert "attachment;" in response.headers["content-disposition"]

    async def test_unknown_session_report_is_404(self, stack: Stack) -> None:
        assert (await stack.client.get("/api/v1/runs/nope/report")).status_code == 404


class _RoutingTransport(httpx.AsyncBaseTransport):
    """Routes HITL calls to a handler and everything else to the mock upstream."""

    def __init__(self, hitl_handler, stack: Stack) -> None:  # type: ignore[no-untyped-def]
        self._hitl = httpx.MockTransport(hitl_handler)
        self._upstream = httpx.ASGITransport(app=stack.upstream)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if "hitl" in request.url.host:
            return await self._hitl.handle_async_request(request)
        return await self._upstream.handle_async_request(request)
