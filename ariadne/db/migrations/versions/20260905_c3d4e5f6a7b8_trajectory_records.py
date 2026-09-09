# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""trajectory records

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-05 00:00:00.000000

Adds the `trajectory_records` table (Feature 7: Data Flywheel / Trajectory
Store). One row per completed session, written by TrajectoryRecorder
(ariadne/audit/trajectory_recorder.py) at session end -- drift/slope/R^2
curves, the five Feature-2 risk-dimension scores, and an auto-labeling
heuristic result, kept as raw material for a future supervised training
pipeline. No ML happens in this migration or in Feature 7 generally.

`calibration_version` and `scoring_algorithm_version` are included now,
always NULL, so Feature 9 (calibration) does not need its own migration
just to add columns to this table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_ORG_ID = "00000000-0000-0000-0000-000000000000"


def upgrade() -> None:
    op.create_table(
        "trajectory_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("organization_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("agent_identity", sa.String(length=512), nullable=True),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("drift_curve", sa.JSON(), nullable=False),
        sa.Column("slope_curve", sa.JSON(), nullable=False),
        sa.Column("r2_curve", sa.JSON(), nullable=False),
        sa.Column("final_enforcement_action", sa.String(length=16), nullable=False),
        sa.Column("first_divergence_step", sa.Integer(), nullable=True),
        sa.Column("root_cause_trigger", sa.String(length=256), nullable=True),
        sa.Column("blast_radius_count", sa.Integer(), nullable=False),
        sa.Column("intent_score", sa.Float(), nullable=False),
        sa.Column("tool_score", sa.Float(), nullable=False),
        sa.Column("privilege_score", sa.Float(), nullable=False),
        sa.Column("identity_score", sa.Float(), nullable=False),
        sa.Column("data_score", sa.Float(), nullable=False),
        sa.Column("confirmed_attack", sa.Boolean(), nullable=True),
        sa.Column("label_source", sa.String(length=32), nullable=True),
        sa.Column("labeled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("calibration_version", sa.String(length=32), nullable=True),
        sa.Column("scoring_algorithm_version", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("trajectory_records", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_trajectory_records_organization_id"),
            ["organization_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_trajectory_records_session_id"), ["session_id"], unique=False
        )
        batch_op.create_index(
            "ix_trajectory_records_org_session",
            ["organization_id", "session_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("trajectory_records", schema=None) as batch_op:
        batch_op.drop_index("ix_trajectory_records_org_session")
        batch_op.drop_index(batch_op.f("ix_trajectory_records_session_id"))
        batch_op.drop_index(batch_op.f("ix_trajectory_records_organization_id"))
    op.drop_table("trajectory_records")
