# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""calibration profiles

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-05 12:00:00.000000

Adds the `calibration_profiles` table (Feature 9: Calibrated/Versioned Risk
Scores) and seeds it with one row, version "1.0.0", is_active=True, mapped
from threshold_calibration.json at the repo root -- the existing calibration
data source of truth, unmodified. That JSON is scripts/calibrate_thresholds.py's
output shape: sample_size/attack_count/benign_count, recommended_escalate/
recommended_block, a metrics dict (detection_rate/false_positive_rate), and a
per-scenario `scores` list. It carries no WARN cutoff (the script only
grid-searches ESCALATE/BLOCK) and no explicit dataset name, so both are
documented sensible defaults (see ariadne/drift/calibration.py) rather than
invented from data that doesn't inform them: recommended_warn defaults to
Ariadne's long-standing DRIFT_SCORE_WARN default (40.0), and dataset defaults
to "injecagent_v1" (the script's docstring identifies its inputs as
InjecAgent attack cases plus Ariadne's own red-team control scenarios).

The mapping itself lives in ariadne.drift.calibration.profile_fields_from_calibration_json
so the seed here and the /admin/calibration/recalibrate endpoint agree on
exactly one mapping; this migration imports it rather than duplicating it,
same as every other data-shape decision Feature 9 makes. (Earlier migrations
in this repo avoid importing ariadne.db.models to keep long-term schema
stable against future model changes; this one is a narrower exception,
importing only a pure mapping function with no ORM/session coupling, because
duplicating a several-field JSON->columns mapping in two places is a worse
long-term risk than this import.)

If threshold_calibration.json is missing (a fresh checkout that never ran the
calibration script, or a non-dev environment where that file was deliberately
excluded), the seed step is skipped with a warning rather than failing the
migration -- the table still gets created, just empty, and the first
recalibrate + activate call becomes the operator's job.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Repo root relative to this file: ariadne/db/migrations/versions/ -> up 4.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_CALIBRATION_JSON_PATH = _REPO_ROOT / "threshold_calibration.json"


def upgrade() -> None:
    op.create_table(
        "calibration_profiles",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("calibrated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dataset", sa.String(length=128), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("highest_benign_score", sa.Float(), nullable=False),
        sa.Column("measured_fpr", sa.Float(), nullable=False),
        sa.Column("measured_detection_rate", sa.Float(), nullable=False),
        sa.Column("score_to_precision", sa.JSON(), nullable=False),
        sa.Column("recommended_warn", sa.Float(), nullable=False),
        sa.Column("recommended_escalate", sa.Float(), nullable=False),
        sa.Column("recommended_block", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("calibration_profiles", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_calibration_profiles_version"), ["version"], unique=True
        )
        batch_op.create_index(
            batch_op.f("ix_calibration_profiles_is_active"), ["is_active"], unique=False
        )

    _seed_from_json()


def _seed_from_json() -> None:
    if not _CALIBRATION_JSON_PATH.exists():
        print(  # noqa: T201 - migration console output, no logger configured here
            f"[calibration_profiles migration] {_CALIBRATION_JSON_PATH} not found, "
            "skipping seed -- table created empty."
        )
        return

    from ariadne.drift.calibration import (  # noqa: PLC0415
        profile_fields_from_calibration_json,
    )

    data = json.loads(_CALIBRATION_JSON_PATH.read_text(encoding="utf-8"))
    fields = profile_fields_from_calibration_json(data)

    now = datetime.now(UTC)
    op.bulk_insert(
        sa.table(
            "calibration_profiles",
            sa.column("id", sa.String),
            sa.column("version", sa.String),
            sa.column("is_active", sa.Boolean),
            sa.column("calibrated_at", sa.DateTime(timezone=True)),
            sa.column("dataset", sa.String),
            sa.column("sample_size", sa.Integer),
            sa.column("highest_benign_score", sa.Float),
            sa.column("measured_fpr", sa.Float),
            sa.column("measured_detection_rate", sa.Float),
            sa.column("score_to_precision", sa.JSON),
            sa.column("recommended_warn", sa.Float),
            sa.column("recommended_escalate", sa.Float),
            sa.column("recommended_block", sa.Float),
            sa.column("notes", sa.Text),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": str(uuid4()),
                "version": "1.0.0",
                "is_active": True,
                "calibrated_at": now,
                "notes": "Seeded from threshold_calibration.json at Feature 9 migration time.",
                "created_at": now,
                **fields,
            }
        ],
    )


def downgrade() -> None:
    with op.batch_alter_table("calibration_profiles", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_calibration_profiles_is_active"))
        batch_op.drop_index(batch_op.f("ix_calibration_profiles_version"))
    op.drop_table("calibration_profiles")
