# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""multi-tenancy foundation

Revision ID: a1b2c3d4e5f6
Revises: 88b5def78cb1
Create Date: 2026-09-04 00:00:00.000000

Migration strategy for ARIADNE_API_KEYS
----------------------------------------
Rather than seeding one ApiKey row per value currently configured in
ARIADNE_API_KEYS (which would require reading process environment from
inside a migration and would hash secrets the operator may rotate before the
next deploy anyway), this migration seeds only the Legacy Org and leaves
ARIADNE_API_KEYS working exactly as before, as a literal fallback bound to
LEGACY_ORG_ID (see ariadne/main.py::require_api_key). That keeps zero-downtime
upgrade a one-step migration + restart: an operator who has not yet
provisioned real ApiKey rows keeps authenticating exactly as before, silently
scoped to the Legacy Org, with no action required. Provisioning real
per-tenant ApiKey rows (via POST /api/v1/keys) is an operator choice made
after upgrade, not a migration-time requirement.

Every existing row (runs/events/alerts/policies/users/refresh_tokens) is
backfilled to LEGACY_ORG_ID before organization_id is made NOT NULL, so no
pre-existing data becomes orphaned or inaccessible.

SQLite cannot ALTER COLUMN in place, so every column add + not-null flip
below goes through batch_alter_table, which also happens to be correct on
Postgres (it just runs the plain ALTER TABLE there).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "e1a2b3c4d5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_ORG_ID = "00000000-0000-0000-0000-000000000000"

_ORG_SCOPED_TABLES_WITH_SESSION = ("runs", "events", "alerts")
_ORG_SCOPED_TABLES = (*_ORG_SCOPED_TABLES_WITH_SESSION, "policies", "users", "refresh_tokens")


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_organizations_slug"), ["slug"], unique=True
        )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("key_hash", sa.String(length=128), nullable=False),
        sa.Column("prefix", sa.String(length=64), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rate_limit_override", sa.Integer(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_api_keys_organization_id"), ["organization_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_api_keys_prefix"), ["prefix"], unique=True)

    # Seed the Legacy Org every pre-existing row is backfilled to.
    op.execute(
        sa.text(
            "INSERT INTO organizations (id, name, slug, plan, created_at, settings) "
            "VALUES (:id, :name, :slug, :plan, CURRENT_TIMESTAMP, :settings)"
        ).bindparams(
            sa.bindparam("id", value=LEGACY_ORG_ID),
            sa.bindparam("name", value="Legacy Org"),
            sa.bindparam("slug", value="legacy"),
            sa.bindparam("plan", value="enterprise"),
            sa.bindparam("settings", value={}, type_=sa.JSON()),
        )
    )

    # Add organization_id nullable, backfill, then flip to NOT NULL — the
    # only way to widen an existing table without an outage window where
    # existing rows would otherwise violate the new constraint.
    for table in _ORG_SCOPED_TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column("organization_id", sa.String(length=64), nullable=True)
            )

    for table in _ORG_SCOPED_TABLES:
        op.execute(
            sa.text(f"UPDATE {table} SET organization_id = :org_id").bindparams(  # noqa: S608
                org_id=LEGACY_ORG_ID
            )
        )

    for table in _ORG_SCOPED_TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column(
                "organization_id", existing_type=sa.String(length=64), nullable=False
            )
            batch_op.create_index(
                batch_op.f(f"ix_{table}_organization_id"), ["organization_id"], unique=False
            )

    for table in _ORG_SCOPED_TABLES_WITH_SESSION:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.create_index(
                f"ix_{table}_org_session", ["organization_id", "session_id"], unique=False
            )


def downgrade() -> None:
    for table in _ORG_SCOPED_TABLES_WITH_SESSION:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(f"ix_{table}_org_session")

    for table in _ORG_SCOPED_TABLES:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_index(batch_op.f(f"ix_{table}_organization_id"))
            batch_op.drop_column("organization_id")

    with op.batch_alter_table("api_keys", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_api_keys_prefix"))
        batch_op.drop_index(batch_op.f("ix_api_keys_organization_id"))
    op.drop_table("api_keys")

    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_organizations_slug"))
    op.drop_table("organizations")
