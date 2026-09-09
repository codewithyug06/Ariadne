# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""auth tables

Revision ID: e1a2b3c4d5f6
Revises: 88b5def78cb1
Create Date: 2026-09-03 00:00:00.000000

Fills a gap in the migration chain: ``users``, ``refresh_tokens``, and
``runtime_overrides`` (ariadne/db/models.py) have never been created by any
migration -- only by ``Database.create_all()`` on a fresh dev/test box. That
made `alembic upgrade head` from an empty schema fail (`ALTER TABLE users`
in a1b2c3d4e5f6, which now depends on this revision instead of
88b5def78cb1). ``alembic_version`` is unstamped in every environment checked
(SQLite dev DB, fresh Postgres), so inserting a revision here is safe -- no
environment has this chain shipped yet.

``organization_id`` is intentionally omitted from ``users`` and
``refresh_tokens`` here: a1b2c3d4e5f6 adds it as nullable, backfills, then
flips it NOT NULL, and that sequence assumes the column doesn't exist yet.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1a2b3c4d5f6"
down_revision: str | None = "88b5def78cb1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_users_email"), ["email"], unique=True)

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("refresh_tokens", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_refresh_tokens_user_id"), ["user_id"], unique=False
        )

    op.create_table(
        "runtime_overrides",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=256), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("runtime_overrides")
    with op.batch_alter_table("refresh_tokens", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_refresh_tokens_user_id"))
    op.drop_table("refresh_tokens")
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_users_email"))
    op.drop_table("users")
