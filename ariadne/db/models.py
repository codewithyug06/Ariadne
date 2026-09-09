# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""SQLAlchemy ORM models for the audit trail."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ariadne.proxy.schemas import utcnow


class Base(DeclarativeBase):
    """Declarative base for every Ariadne table."""

    type_annotation_map = {dict[str, Any]: JSON}


#: The tenant every pre-Phase-1 row (and every ARIADNE_API_KEYS fallback
#: caller) is bound to. A fixed all-zero uuid so the migration's backfill and
#: the ARIADNE_API_KEYS runtime fallback (main.py::require_api_key) always
#: agree on the same id without a DB round trip.
LEGACY_ORG_ID = "00000000-0000-0000-0000-000000000000"


class Organization(Base):
    """A tenant. Every other table's rows belong to exactly one of these."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    plan: Mapped[str] = mapped_column(String(32), default="free")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: This org's own MCP tool server -- where Ariadne would forward an
    #: intercepted call once "connect your agent" wiring exists. Not yet read
    #: by ariadne/proxy/mcp_proxy.py (which still forwards every session to
    #: the single global settings.upstream_mcp_url) -- see
    #: ariadne/api/connect.py's module docstring for what's actually live.
    upstream_mcp_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    #: Fernet-encrypted JSON blob of {header_name: header_value} for calls to
    #: upstream_mcp_url (may contain the customer's own tool-server
    #: credentials) -- never stored in the clear. Encrypted/decrypted only in
    #: ariadne/api/connect.py using settings.upstream_encryption_key.
    upstream_mcp_headers_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApiKey(Base):
    """A machine credential bound to one organization.

    Replaces the flat ARIADNE_API_KEYS list as the primary mechanism, while
    that env var keeps working as a bootstrap/dev fallback bound to
    LEGACY_ORG_ID (see main.py::require_api_key) so an existing
    single-key deployment never breaks on upgrade.
    """

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    key_hash: Mapped[str] = mapped_column(String(128))
    # The leading fixed-length segment of the raw key, stored in the clear and
    # indexed so lookup-by-prefix is a single indexed query instead of a full
    # table scan + bcrypt-verify-everything.
    prefix: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rate_limit_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Run(Base):
    """One agent session, from handshake to teardown."""

    __tablename__ = "runs"

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True, default=LEGACY_ORG_ID)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_steps: Mapped[int] = mapped_column(Integer, default=0)
    final_status: Mapped[str] = mapped_column(String(16), default="CLEAN", index=True)
    intent_summary: Mapped[str] = mapped_column(Text, default="")
    intent_goal: Mapped[str] = mapped_column(Text, default="")
    max_drift_score: Mapped[float] = mapped_column(Float, default=0.0)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0)
    escalated_count: Mapped[int] = mapped_column(Integer, default=0)
    warned_count: Mapped[int] = mapped_column(Integer, default=0)
    agent_framework: Mapped[str] = mapped_column(String(64), default="unknown")
    run_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )

    events: Mapped[list[Event]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_runs_started_at", "started_at"),
        Index("ix_runs_org_session", "organization_id", "session_id"),
    )


class Event(Base):
    """One intercepted tool call and the decision made about it."""

    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True, default=LEGACY_ORG_ID)
    session_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("runs.session_id", ondelete="CASCADE"), index=True
    )
    step_index: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(String(255), index=True)
    enforcement_action: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    triggered_rule: Mapped[str | None] = mapped_column(String(128), nullable=True)
    drift_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    slope: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[Run] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_events_session_step", "session_id", "step_index"),
        Index("ix_events_org_session", "organization_id", "session_id"),
    )


class Policy(Base):
    """A hard rule managed at runtime through the API.

    `name` stays the sole primary key rather than moving to a composite
    (organization_id, name) key: policies.py's API and the enforcement engine
    both address policies by bare name throughout, and widening the key would
    ripple into every one of those call sites. The practical effect is that
    policy names are a shared namespace across organizations (two orgs cannot
    both have a policy named "default") — a real limitation, but not an
    isolation leak: reads/writes still filter by organization_id below, so
    Org B can never read, edit, or collide with Org A's policy by name (a
    same-named create fails outright rather than silently colliding).
    """

    __tablename__ = "policies"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True, default=LEGACY_ORG_ID)
    description: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(String(16), default="BLOCK")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tool_name_patterns: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    argument_patterns: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    requires_hitl_token: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(Base):
    """A dashboard account. Machine-to-machine traffic still uses ARIADNE_API_KEYS."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True, default=LEGACY_ORG_ID)
    # Kept globally unique rather than scoped to (organization_id, email): the
    # login route (ariadne/api/auth.py) authenticates by email + password
    # alone, with no org selector on the request — multi-org login (the same
    # human, or the same email, in two orgs) is Phase-3-shaped work this
    # brief doesn't ask for. Documented deviation from a stricter per-org
    # unique constraint.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RefreshToken(Base):
    """A rotated, hashed refresh token backing one browser session."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True, default=LEGACY_ORG_ID)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RuntimeOverride(Base):
    """A key/value admin override applied on top of a Settings default.

    Only a small, explicitly whitelisted set of keys are ever read this way
    (see ariadne/enforcement/soft_layer.py) — this is not a general settings
    store, just an escape hatch for the handful of values worth changing
    without a restart.
    """

    __tablename__ = "runtime_overrides"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Alert(Base):
    """An ESCALATE or BLOCK worth surfacing to a human."""

    __tablename__ = "alerts"

    alert_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True, default=LEGACY_ORG_ID)
    session_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("runs.session_id", ondelete="CASCADE"), index=True
    )
    step_index: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    drift_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    run: Mapped[Run] = relationship(back_populates="alerts")

    __table_args__ = (Index("ix_alerts_org_session", "organization_id", "session_id"),)


class Agent(Base):
    """A named or auto-discovered calling agent, aggregated across its runs."""

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(64), index=True, default=LEGACY_ORG_ID)
    name: Mapped[str] = mapped_column(String(255))
    agent_identity: Mapped[str] = mapped_column(String(512), index=True)
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    total_blocked: Mapped[int] = mapped_column(Integer, default=0)
    total_escalated: Mapped[int] = mapped_column(Integer, default=0)
    avg_drift_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_agents_org_identity", "organization_id", "agent_identity", unique=True),
    )


class TrajectoryRecord(Base):
    """A completed session's full trajectory, persisted for the data flywheel.

    Feature 7 (Data Flywheel). Pure persistence: no ML training happens here,
    this table is the raw material a future supervised-training pipeline
    would read from. One row per completed session, written best-effort by
    TrajectoryRecorder (ariadne/audit/trajectory_recorder.py) at session end.
    """

    __tablename__ = "trajectory_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(String(64), index=True, default=LEGACY_ORG_ID)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    agent_identity: Mapped[str | None] = mapped_column(String(512), nullable=True)
    step_count: Mapped[int] = mapped_column(Integer)
    drift_curve: Mapped[list[float]] = mapped_column(JSON)
    slope_curve: Mapped[list[float]] = mapped_column(JSON)
    r2_curve: Mapped[list[float]] = mapped_column(JSON)
    final_enforcement_action: Mapped[str] = mapped_column(String(16))
    first_divergence_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    root_cause_trigger: Mapped[str | None] = mapped_column(String(256), nullable=True)
    blast_radius_count: Mapped[int] = mapped_column(Integer, default=0)
    intent_score: Mapped[float] = mapped_column(Float, default=0.0)
    tool_score: Mapped[float] = mapped_column(Float, default=0.0)
    privilege_score: Mapped[float] = mapped_column(Float, default=0.0)
    identity_score: Mapped[float] = mapped_column(Float, default=0.0)
    data_score: Mapped[float] = mapped_column(Float, default=0.0)
    confirmed_attack: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    label_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    labeled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Feature 9 (calibration) is not built yet -- always None for now, the
    #: column exists so that feature's migration doesn't need to touch this
    #: table.
    calibration_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Same as above, for whichever future feature versions the scoring algorithm.
    scoring_algorithm_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_trajectory_records_org_session", "organization_id", "session_id"),
    )


class OrgToolOverride(Base):
    """An operator-pinned tool risk score that always wins over the
    contextual scorer's computed value (Feature 10).

    Mirrors Policy's org-scoping convention: `organization_id` filters every
    read/write, so an org only ever sees or manages its own overrides.
    """

    __tablename__ = "org_tool_overrides"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    organization_id: Mapped[str] = mapped_column(String(64), index=True, default=LEGACY_ORG_ID)
    tool_name: Mapped[str] = mapped_column(String(255))
    risk_override: Mapped[float] = mapped_column(Float)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index(
            "ix_org_tool_overrides_org_tool", "organization_id", "tool_name", unique=True
        ),
    )


class CalibrationProfile(Base):
    """One empirically-derived set of drift-score thresholds (Feature 9).

    Wraps scripts/calibrate_thresholds.py's methodology and
    threshold_calibration.json's output shape as a versioned, queryable row
    rather than a single untracked JSON file. Exactly one row is
    `is_active=True` at a time (enforced by the activate endpoint, not a DB
    constraint -- SQLite's partial-unique-index support is awkward enough
    across dialects that a single-transaction "clear all, set one" write is
    simpler and just as correct for the write volume this table sees).
    """

    __tablename__ = "calibration_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid4()))
    version: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    calibrated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    dataset: Mapped[str] = mapped_column(String(128))
    sample_size: Mapped[int] = mapped_column(Integer)
    highest_benign_score: Mapped[float] = mapped_column(Float)
    measured_fpr: Mapped[float] = mapped_column(Float)
    measured_detection_rate: Mapped[float] = mapped_column(Float)
    score_to_precision: Mapped[dict[str, Any]] = mapped_column(JSON)
    recommended_warn: Mapped[float] = mapped_column(Float)
    recommended_escalate: Mapped[float] = mapped_column(Float)
    recommended_block: Mapped[float] = mapped_column(Float)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
