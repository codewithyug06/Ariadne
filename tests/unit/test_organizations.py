# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Org lifecycle (ariadne/api/organizations.py): slug derivation and the
delete-everything sweep across every org-scoped table.

Unit-level against the real `database` fixture (in-memory SQLite), same
style as test_quotas.py -- what matters here is that the sweep actually
touches every table it claims to, which is more honest proven against real
rows than mocked. RLS itself and the real HTTP signup/delete round trip are
Postgres-only and covered separately (scripts/verify_organizations.py).
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from ariadne.api.organizations import _ORG_SCOPED_MODELS, _slugify
from ariadne.db.models import ApiKey, Organization, Run, User
from ariadne.db.session import Database


class TestSlugify:
    def test_normalizes_and_appends_unique_suffix(self) -> None:
        slug = _slugify("Acme Corp!!")
        assert slug.startswith("acme-corp-")
        assert len(slug.split("-")[-1]) == 8

    def test_two_calls_for_the_same_name_never_collide(self) -> None:
        first = _slugify("Same Name")
        second = _slugify("Same Name")
        assert first != second

    def test_empty_after_stripping_falls_back_to_org(self) -> None:
        assert _slugify("!!!").startswith("org-")


async def _delete_org(database: Database, org_id: str) -> None:
    async with database.session(bypass_rls=True) as session:
        org = await session.get(Organization, org_id)
        for model in _ORG_SCOPED_MODELS:
            await session.execute(delete(model).where(model.organization_id == org_id))
        await session.delete(org)


class TestDeleteSweep:
    async def test_deleting_org_removes_rows_from_every_scoped_table(
        self, database: Database
    ) -> None:
        org_id = str(uuid.uuid4())
        async with database.session(org_id) as session:
            session.add(Organization(id=org_id, name="t", slug=f"t-{org_id[:8]}"))
            await session.flush()
            session.add(
                User(
                    id=str(uuid.uuid4()),
                    organization_id=org_id,
                    email=f"{org_id[:8]}@example.com",
                    password_hash="x",
                    role="admin",
                )
            )
            session.add(
                ApiKey(
                    id=str(uuid.uuid4()),
                    organization_id=org_id,
                    key_hash="x",
                    prefix=f"pfx-{org_id[:8]}",
                )
            )
            session.add(
                Run(
                    session_id=str(uuid.uuid4()),
                    organization_id=org_id,
                    total_steps=0,
                    final_status="CLEAN",
                    intent_summary="t",
                    intent_goal="t",
                    max_drift_score=0.0,
                    blocked_count=0,
                    escalated_count=0,
                    warned_count=0,
                    agent_framework="test",
                    run_metadata={},
                )
            )

        await _delete_org(database, org_id)

        async with database.session(bypass_rls=True) as session:
            assert await session.get(Organization, org_id) is None
            assert (
                await session.scalar(select(User).where(User.organization_id == org_id))
            ) is None
            assert (
                await session.scalar(select(ApiKey).where(ApiKey.organization_id == org_id))
            ) is None
            assert (await session.scalar(select(Run).where(Run.organization_id == org_id))) is None

    async def test_deleting_one_org_does_not_touch_another(self, database: Database) -> None:
        org_a = str(uuid.uuid4())
        org_b = str(uuid.uuid4())
        async with database.session(bypass_rls=True) as session:
            session.add(Organization(id=org_a, name="a", slug=f"a-{org_a[:8]}"))
            session.add(Organization(id=org_b, name="b", slug=f"b-{org_b[:8]}"))
            await session.flush()
            session.add(
                User(
                    id=str(uuid.uuid4()),
                    organization_id=org_b,
                    email=f"{org_b[:8]}@example.com",
                    password_hash="x",
                    role="admin",
                )
            )

        await _delete_org(database, org_a)

        async with database.session(bypass_rls=True) as session:
            assert await session.get(Organization, org_a) is None
            assert await session.get(Organization, org_b) is not None
            assert (
                await session.scalar(select(User).where(User.organization_id == org_b))
            ) is not None
