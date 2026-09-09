# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""org upstream config

Revision ID: a2b3c4d5e6f7
Revises: f6a7b8c9d0e1
Create Date: 2026-09-11 00:00:00.000000

Adds `upstream_mcp_url` / `upstream_mcp_headers_encrypted` to
`organizations` (ariadne/api/connect.py). Both nullable -- most orgs have
neither configured yet, and ariadne/proxy/mcp_proxy.py does not read these
columns (it still forwards every session to the single global
settings.upstream_mcp_url); see connect.py's module docstring for scope.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("upstream_mcp_url", sa.String(length=2048), nullable=True))
        batch_op.add_column(
            sa.Column("upstream_mcp_headers_encrypted", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.drop_column("upstream_mcp_headers_encrypted")
        batch_op.drop_column("upstream_mcp_url")
