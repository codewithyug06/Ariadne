# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Billing: today, a link out to a hosted Razorpay Payment Page.

This is deliberately the whole feature for now. There is no Razorpay API
key and no webhook signing secret configured (RAZORPAY_PAYMENT_LINK in
config.py is a public page URL, not a credential), so:

  - There is no server-to-server call to Razorpay anywhere in this module.
  - A completed payment does NOT automatically change
    Organization.plan -- Razorpay's webhook payload can't be verified
    without a signing secret, and accepting an unverified "payment
    succeeded" webhook would let anyone flip their own org to a paid plan
    by POSTing a forged payload. That would be worse than not automating
    it at all.

Once a Razorpay key id/secret and a webhook signing secret exist, the real
next step is: a `/api/v1/billing/webhook` route verifying
`X-Razorpay-Signature` (HMAC-SHA256 over the raw body with the webhook
secret) before trusting `payment.captured`, and using the API key to
create Payment Links per-organization (so `notes.organization_id` on the
webhook payload tells you which org to upgrade) instead of one shared
static link. Until then, upgrading is a human process: a customer pays via
the shared link below, and an admin manually raises their plan/quota
settings (see ariadne/billing/quotas.py) the same way any other
Organization.settings value is changed today.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ariadne.auth.org_scope import require_org_scope
from ariadne.db.models import Organization

router = APIRouter(prefix="/billing", tags=["billing"])


class UpgradeInfo(BaseModel):
    plan: str
    payment_link: str


@router.get("/upgrade", response_model=UpgradeInfo, summary="This org's plan and payment link")
async def get_upgrade_info(
    request: Request, organization_id: str = Depends(require_org_scope)
) -> UpgradeInfo:
    database = request.app.state.database
    async with database.session(organization_id) as session:
        org = await session.get(Organization, organization_id)
        plan = org.plan if org is not None else "free"
    return UpgradeInfo(plan=plan, payment_link=request.app.state.settings.razorpay_payment_link)
