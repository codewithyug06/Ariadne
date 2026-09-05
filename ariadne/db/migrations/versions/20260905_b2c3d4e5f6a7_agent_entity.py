# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""agent entity

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-05 00:00:00.000000

Adds the `agents` table (Feature 3: Agent Entity) plus a nullable
`agent_id` foreign key on `runs`. Agents are aggregated, org-scoped
rows keyed on (organization_id, agent_identity) — see
ariadne/proxy/mcp_proxy.py for how agent_identity is derived and how
an Agent row is looked up or created at session start.

`agent_id` on `runs` is added nullable with no backfill: every
pre-existing run predates agent resolution and simply has no agent
association, which is a legitimate state (not an omission that needs
fixing) — unlike the Phase-1 multi-tenancy migration's organization_id,
there is no "correct" agent to backfill existing rows to.

SQLite cannot ALTER COLUMN / ADD CONSTRAINT in place, so the column
add on `runs` goes through batch_alter_table, which also happens to be
correct on Postgres (it just runs the plain ALTER TABLE there).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_ORG_ID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("agent_identity", sa.String(length=512), nullable=False),
        sa.Column("total_runs", sa.Integer(), nullable=False),
        sa.Column("total_blocked", sa.Integer(), nullable=False),
        sa.Column("total_escalated", sa.Integer(), nullable=False),
        sa.Column("avg_drift_score", sa.Float(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_agents_organization_id"), ["organization_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_agents_agent_identity"), ["agent_identity"], unique=False
        )
        batch_op.create_index(
            "ix_agents_org_identity", ["organization_id", "agent_identity"], unique=True
        )

    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("agent_id", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_runs_agent_id"), ["agent_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_runs_agent_id_agents", "agents", ["agent_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_constraint("fk_runs_agent_id_agents", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_runs_agent_id"))
        batch_op.drop_column("agent_id")

    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.drop_index("ix_agents_org_identity")
        batch_op.drop_index(batch_op.f("ix_agents_agent_identity"))
        batch_op.drop_index(batch_op.f("ix_agents_organization_id"))
    op.drop_table("agents")
