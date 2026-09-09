# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""One-off: prove GET /api/v1/billing/upgrade (ariadne/api/billing.py) works
through the real HTTP route against Postgres.

There is no Razorpay API key or webhook secret configured (see
billing.py's module docstring for why nothing beyond serving the static
payment link is implemented yet), so there's nothing to test but the one
thing that exists: an org-scoped caller gets back their real plan and the
configured payment link.

    DATABASE_URL=postgresql+asyncpg://ariadne_verify:verifypass@localhost:5432/ariadne \\
        python scripts/verify_billing.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid

import httpx

from ariadne.config import Settings
from ariadne.main import create_app


async def main_async() -> int:
    database_url = Settings(_env_file=None).database_url
    if not database_url.startswith("postgresql"):
        print("DATABASE_URL must point at Postgres for this check", file=sys.stderr)
        return 1

    settings = Settings(
        _env_file=None,
        DATABASE_URL=database_url,
        UPSTREAM_MCP_URL="http://upstream.test/mcp",
        EMBEDDING_DEVICE="cpu",
        OLLAMA_URL="http://localhost:1",
        ARCADEDB_URL=None,
        OPA_URL=None,
        HITL_WEBHOOK_URL=None,
        LOG_LEVEL="WARNING",
        ARIADNE_API_KEYS=["unused-legacy-fallback"],
    )

    app = create_app(settings)
    failures: list[str] = []
    email = f"verify-billing-{uuid.uuid4().hex[:8]}@example.com"

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://ariadne.test"
        ) as client:
            signup = await client.post(
                "/api/v1/orgs",
                json={
                    "organization_name": "Billing Verify Org",
                    "admin_email": email,
                    "admin_password": "correct horse battery staple",
                },
            )
            if signup.status_code != 201:
                failures.append(f"signup failed: {signup.status_code} {signup.text}")
                return _report(failures)
            raw_key = signup.json()["api_key"]

            response = await client.get(
                "/api/v1/billing/upgrade", headers={"X-Api-Key": raw_key}
            )
            if response.status_code != 200:
                failures.append(f"upgrade info failed: {response.status_code} {response.text}")
            else:
                body = response.json()
                if body.get("plan") != "free":
                    failures.append(
                        f"fresh org should default to plan 'free', got {body.get('plan')!r}"
                    )
                if body.get("payment_link") != settings.razorpay_payment_link:
                    failures.append(
                        f"payment_link mismatch: got {body.get('payment_link')!r}, "
                        f"expected {settings.razorpay_payment_link!r}"
                    )
                if not failures:
                    print(
                        f"  (confirmed: GET /api/v1/billing/upgrade returned "
                        f"plan={body['plan']!r}, payment_link={body['payment_link']!r})"
                    )

    if failures:
        return _report(failures)

    print("Billing verification passed: the upgrade endpoint returns the org's real plan")
    print("and the configured Razorpay payment link, against Postgres over real HTTP.")
    return 0


def _report(failures: list[str]) -> int:
    print("BILLING VERIFICATION FAILED:")
    for f in failures:
        print(f"  - {f}")
    return 1


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
