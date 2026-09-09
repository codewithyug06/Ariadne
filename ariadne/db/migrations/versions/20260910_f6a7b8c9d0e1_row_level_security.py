# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""row-level security

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-09-10 00:00:00.000000

Second, database-enforced layer under the application-level
`WHERE organization_id = ...` filtering every route already does (see
ariadne/auth/org_scope.py, ariadne/db/session.py). Postgres-only -- RLS
doesn't exist on SQLite, so this is a clean no-op there (dev/test keep
running exactly as before).

Mechanism: `Database.session()` issues `SELECT set_config(...)` as the
first statement in each session, setting one of two transaction-local
GUCs that every policy below reads:

  - app.current_org_id -- set when the caller's org is known up front
    (the overwhelming majority of call sites: any route behind
    require_org_scope, any internal method that already takes
    organization_id as a parameter).
  - app.bypass_rls -- set only by the handful of call sites that must
    legitimately see across orgs before a request's org is knowable
    (login/API-key authentication by a global lookup key, the audit
    recorder's per-item drain, startup bootstrap paths). Never derived
    from caller-controlled input.

Neither GUC set (a session opened via plain `database.session()` with no
args) means every policy below evaluates to NULL/false and the session
sees zero rows on these tables -- by design, for tables like
`calibration_profiles` and `runtime_overrides` that intentionally carry
no policy at all (no organization_id column) and are unaffected by this
migration.

FORCE ROW LEVEL SECURITY is included for correctness in the standard
production shape (an application role that doesn't own its own tables),
even though it has no effect against the Postgres superuser this project's
local dev/CI Postgres container currently connects as -- superusers always
bypass RLS regardless of FORCE. Verifying these policies therefore
requires a dedicated non-superuser role (see
scripts/verify_rls.py's role-provisioning step), not a check against the
default `postgres` connection.

`users` carries a policy like every other table here, but it protects
nothing against the login path specifically: auth.py's `login` reads
`users` by a globally-unique email with `bypass_rls=True`, since no org is
known before that lookup succeeds. The policy still isolates every other
access to `users` (list/create/reset-password/delete teammates, `/me`,
password change).

`policies` is deliberately excluded from this table list. Its primary key
is the bare `name` column (global, not per-org -- see policies.py's
module note), and Postgres enforces PRIMARY KEY/UNIQUE constraints
regardless of RLS visibility (unlike FK checks, which the docs explicitly
exempt, uniqueness enforcement always sees every physical row). Verified
empirically (scripts/verify_rls_app.py): with a policy applied here, two
orgs racing to create the same policy name went from a clean 409 (the
app-level check in upsert_policy sees the other org's row and returns a
normal conflict response) to an unhandled IntegrityError, because RLS hid
that row from the very check meant to catch it. `policies` keeps
app-level-only isolation (`WHERE organization_id = ...`, same as every
route before this migration) -- one table without a second enforcement
layer, not silently dropped, tracked here as the reason. A composite
`(organization_id, name)` primary key is the real fix if DB-enforced
isolation on this table is ever needed; larger change, not done here.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Every table with an organization_id column that gets DB-enforced RLS.
#: Deliberately excludes `organizations` (its own id IS the org id),
#: `calibration_profiles` and `runtime_overrides` (both global, no
#: organization_id column), and `policies` (see the module docstring --
#: its global `name` primary key collides with RLS's SELECT-hiding when
#: two orgs use the same name, turning a clean 409 into an IntegrityError).
_ORG_SCOPED_TABLES = (
    "api_keys",
    "runs",
    "events",
    "alerts",
    "users",
    "refresh_tokens",
    "agents",
    "trajectory_records",
    "org_tool_overrides",
)

_POLICY_NAME = "org_isolation"

_POLICY_EXPRESSION = (
    "current_setting('app.bypass_rls', true) = 'on' "
    "OR organization_id = current_setting('app.current_org_id', true)"
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in _ORG_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")  # noqa: S608
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")  # noqa: S608
        op.execute(  # noqa: S608
            f"CREATE POLICY {_POLICY_NAME} ON {table} USING ({_POLICY_EXPRESSION})"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in reversed(_ORG_SCOPED_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {_POLICY_NAME} ON {table}")  # noqa: S608
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")  # noqa: S608
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")  # noqa: S608
