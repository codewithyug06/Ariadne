# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""org tool overrides

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-05 13:00:00.000000

Adds the `org_tool_overrides` table (Feature 10: Contextual Tool-Risk
Scoring). Each row pins one org's risk score for one named tool, always
overriding the contextual scorer's computed value for that (org, tool) pair.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "org_tool_overrides",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("risk_override", sa.Float(), nullable=False),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("org_tool_overrides", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_org_tool_overrides_organization_id"),
            ["organization_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_org_tool_overrides_org_tool",
            ["organization_id", "tool_name"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("org_tool_overrides", schema=None) as batch_op:
        batch_op.drop_index("ix_org_tool_overrides_org_tool")
        batch_op.drop_index(batch_op.f("ix_org_tool_overrides_organization_id"))
    op.drop_table("org_tool_overrides")
