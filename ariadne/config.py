# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Central configuration for Ariadne, sourced entirely from the environment."""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class FailMode(str, Enum):
    """Behaviour when Ariadne's own pipeline raises.

    FAIL_CLOSED refuses the tool call (safe default); FAIL_OPEN forwards it
    unscored so an Ariadne outage cannot take the agent fleet down with it.
    """

    FAIL_CLOSED = "FAIL_CLOSED"
    FAIL_OPEN = "FAIL_OPEN"


class Settings(BaseSettings):
    """Every knob Ariadne exposes. All values are overridable via environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Server -----------------------------------------------------------
    ariadne_host: str = Field(default="0.0.0.0", alias="ARIADNE_HOST")  # noqa: S104
    ariadne_port: int = Field(default=8000, alias="ARIADNE_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:5173"], alias="CORS_ORIGINS"
    )
    # "production" refuses to start with an empty api_keys list — an
    # unauthenticated firewall protecting nothing is worse than none at all.
    environment: Literal["development", "production"] = Field(
        default="development", alias="ARIADNE_ENV"
    )
    # Bearer tokens accepted on every route except /health and /metrics.
    # Comma-separated; generate with e.g. `python -c "import secrets;
    # print(secrets.token_urlsafe(32))"`.
    api_keys: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="ARIADNE_API_KEYS"
    )
    # Requests per minute, per API key (or per client IP when unauthenticated
    # in dev mode). A leaked key shouldn't be able to hammer the proxy or the
    # embedder unbounded.
    rate_limit_per_minute: int = Field(default=120, alias="RATE_LIMIT_PER_MINUTE")

    # ---- Dashboard user auth -----------------------------------------------
    # Signs/verifies dashboard JWTs (access + refresh). Distinct from
    # api_keys, which authenticate machine callers (the orchestrator hitting
    # /mcp), not human dashboard sessions.
    jwt_secret_key: str = Field(default="", alias="JWT_SECRET_KEY")
    jwt_access_token_minutes: int = Field(default=15, alias="JWT_ACCESS_TOKEN_MINUTES")
    jwt_refresh_token_days: int = Field(default=14, alias="JWT_REFRESH_TOKEN_DAYS")
    # First-boot bootstrap: if the users table is empty, one admin account is
    # created from these. Ignored on every later boot once a user exists.
    admin_email: str | None = Field(default=None, alias="ARIADNE_ADMIN_EMAIL")
    admin_password: str | None = Field(default=None, alias="ARIADNE_ADMIN_PASSWORD")

    # ---- Google OAuth2 (optional) -----------------------------------------
    # Register a Google Cloud OAuth2 client at console.cloud.google.com and
    # add DASHBOARD_PUBLIC_URL/api/v1/auth/google/callback as an authorised
    # redirect URI. Leave both unset to disable Google sign-in.
    google_client_id: str | None = Field(default=None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: str | None = Field(default=None, alias="GOOGLE_CLIENT_SECRET")
    # Public URL of the dashboard (used as redirect_uri base for Google OAuth2).
    # In dev: http://localhost:5173 (Vite proxy forwards /api to the backend).
    # In prod: https://app.yourcompany.com (nginx proxies /api to the backend).
    dashboard_public_url: str = Field(
        default="http://localhost:5173", alias="DASHBOARD_PUBLIC_URL"
    )

    # ---- Billing ------------------------------------------------------------
    # A hosted Razorpay Payment Page link, not a secret -- there is no
    # Razorpay API key or webhook signing secret configured yet, so a
    # completed payment does not (yet) automatically flip
    # Organization.plan; see ariadne/api/billing.py's module docstring for
    # what would need to change once those credentials exist.
    razorpay_payment_link: str = Field(
        default="https://rzp.io/rzp/ariadne", alias="RAZORPAY_PAYMENT_LINK"
    )

    # The URL an agent orchestrator should point at to reach *this* Ariadne
    # instance's /mcp proxy (e.g. https://api.yourcompany.com) — distinct
    # from upstream_mcp_url below, which is the real tool server Ariadne
    # forwards to. Only the dashboard's own domain is reachable from a
    # browser via nginx (dashboard/nginx.conf.template proxies /api, /status,
    # /health, /ws but deliberately not /mcp — that's a machine-to-machine
    # endpoint, not something a browser calls), so the dashboard cannot infer
    # this from window.location; it has to be told.
    public_url: str | None = Field(default=None, alias="ARIADNE_PUBLIC_URL")

    # ---- Upstream MCP -----------------------------------------------------
    upstream_mcp_url: str = Field(default="http://localhost:9000/mcp", alias="UPSTREAM_MCP_URL")
    upstream_timeout_seconds: float = Field(default=30.0, alias="UPSTREAM_TIMEOUT_SECONDS")
    fail_mode: FailMode = Field(default=FailMode.FAIL_CLOSED, alias="FAIL_MODE")
    # Fernet key encrypting each org's own upstream auth headers at rest
    # (ariadne/api/connect.py) -- those headers may hold the customer's own
    # tool-server credentials, so they're never stored in the clear. Empty by
    # default (dev): connect.py refuses to save headers until this is set,
    # rather than silently storing them unencrypted.
    # Generate with: python -c "from cryptography.fernet import Fernet;
    # print(Fernet.generate_key().decode())"
    upstream_encryption_key: str = Field(default="", alias="UPSTREAM_ENCRYPTION_KEY")

    # ---- Persistence ------------------------------------------------------
    database_url: str = Field(default="sqlite+aiosqlite:///./ariadne.db", alias="DATABASE_URL")
    # Backs the arq job queue (ariadne/eval/job_runner.py). Unset, or set but
    # unreachable, both degrade gracefully to running jobs in-process — same
    # pattern as arcadedb_url/opa_url below.
    redis_url: str | None = Field(default=None, alias="REDIS_URL")
    arcadedb_url: str | None = Field(default=None, alias="ARCADEDB_URL")
    arcadedb_user: str = Field(default="root", alias="ARCADEDB_USER")
    arcadedb_password: str = Field(default="", alias="ARCADEDB_PASSWORD")
    arcadedb_database: str = Field(default="ariadne", alias="ARCADEDB_DATABASE")

    # ---- Embedding --------------------------------------------------------
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2", alias="EMBEDDING_MODEL"
    )
    embedding_device: Literal["cuda", "cpu", "auto"] = Field(
        default="cuda", alias="EMBEDDING_DEVICE"
    )
    # RTX 4050 Laptop ships 6 GB of VRAM; 32 keeps MiniLM batches well inside it
    # alongside a resident model and leaves headroom for a co-located LLM.
    embedding_batch_size: int = Field(default=32, alias="EMBEDDING_BATCH_SIZE")
    embedding_dimension: int = Field(default=384, alias="EMBEDDING_DIMENSION")

    # ---- Drift ------------------------------------------------------------
    drift_window_size: int = Field(default=5, alias="DRIFT_WINDOW_SIZE")
    # Tuned against measured all-MiniLM-L6-v2 geometry: genuine slow-burn
    # injections sustain ~0.10-0.20 distance/step, benign lateral exploration
    # peaks briefly around 0.20 but does not sustain it. This is the half-power
    # point of the slope ramp, not a hard cutoff.
    drift_slope_threshold: float = Field(default=0.04, alias="DRIFT_SLOPE_THRESHOLD")
    drift_score_warn: float = Field(default=40.0, alias="DRIFT_SCORE_WARN")
    # Empirically calibrated via scripts/calibrate_thresholds.py against 324
    # real samples (320 InjecAgent attacks + 4 red-team control scenarios,
    # live Ollama-backed pipeline): 91% detection at 0% FPR. Raised from the
    # earlier 65/85 pair after the live LLM intent decomposer (non-deterministic
    # goal/constraint text) pushed a legitimate "wide-ranging research" control
    # scenario's peak drift to 66.1 — just above the old ESCALATE cutoff.
    drift_score_escalate: float = Field(default=66.5, alias="DRIFT_SCORE_ESCALATE")
    drift_score_block: float = Field(default=86.5, alias="DRIFT_SCORE_BLOCK")

    # ---- Drift extrapolation (Feature 8) -----------------------------------
    # Purely mathematical linear projection of the current slope -- see
    # ariadne/drift/extrapolator.py. Below this R-squared the fitted line is
    # not trustworthy enough to extrapolate, so ExtrapolationPredictor returns
    # None rather than a confident-looking guess (same 0.70 boundary
    # TrajectoryScorer already uses internally as MIN_TREND_FIT).
    projection_min_r2: float = Field(default=0.70, alias="PROJECTION_MIN_R2")
    projection_steps_ahead: Annotated[list[int], NoDecode] = Field(
        default_factory=lambda: [1, 3], alias="PROJECTION_STEPS_AHEAD"
    )

    # ---- Intent decomposition --------------------------------------------
    ollama_url: str = Field(default="http://localhost:11434", alias="OLLAMA_URL")
    ollama_model: str = Field(default="mistral:7b-instruct", alias="OLLAMA_MODEL")
    ollama_fallback_model: str = Field(default="qwen2.5:7b", alias="OLLAMA_FALLBACK_MODEL")
    ollama_timeout_seconds: float = Field(default=30.0, alias="OLLAMA_TIMEOUT_SECONDS")
    decomposer_max_retries: int = Field(default=3, alias="DECOMPOSER_MAX_RETRIES")

    # ---- Enforcement ------------------------------------------------------
    opa_url: str | None = Field(default=None, alias="OPA_URL")
    opa_policy_path: str = Field(default="/v1/data/ariadne/allow", alias="OPA_POLICY_PATH")
    hitl_webhook_url: str | None = Field(default=None, alias="HITL_WEBHOOK_URL")
    hitl_timeout_seconds: float = Field(default=60.0, alias="HITL_TIMEOUT_SECONDS")
    max_tool_calls_per_session: int = Field(default=200, alias="MAX_TOOL_CALLS_PER_SESSION")
    disallowed_tools: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="DISALLOWED_TOOLS"
    )

    # ---- Multi-dimensional risk engine -------------------------------------
    # Weighted combination used by RiskDimensionScorer._aggregate (see
    # ariadne/enforcement/risk_dimensions.py). Must sum to 1.0 -- enforced by
    # _risk_weights_sum_to_one below.
    intent_weight: float = Field(default=0.35, alias="INTENT_WEIGHT")
    tool_weight: float = Field(default=0.20, alias="TOOL_WEIGHT")
    privilege_weight: float = Field(default=0.25, alias="PRIVILEGE_WEIGHT")
    identity_weight: float = Field(default=0.10, alias="IDENTITY_WEIGHT")
    data_weight: float = Field(default=0.10, alias="DATA_WEIGHT")
    # Feature 9 (calibrated/versioned risk scores). Bump manually whenever the
    # five weights above change in a way that would make historical
    # RiskDimensionReport.aggregate values not directly comparable to new
    # ones. Feature 2 (multi-dimensional risk engine) did not add this
    # setting -- it is introduced now because Feature 9 is the first
    # consumer (ScoringVersionStamp.risk_weights_version).
    risk_weights_version: str = Field(default="1.0.0", alias="RISK_WEIGHTS_VERSION")
    # Feature 10 (contextual tool-risk scoring). A numeric tool-call argument
    # exceeding this value adds an argument-context risk modifier (see
    # ariadne/enforcement/contextual_tool_risk.py). Default 0 disables the
    # check entirely -- most deployments have no notion of a "large
    # transaction" amount without being told one, so treating "unset" as "off"
    # avoids false positives on numeric arguments that have nothing to do with
    # money (e.g. a page size or a retry count).
    large_transaction_threshold: float = Field(
        default=0.0, alias="LARGE_TRANSACTION_THRESHOLD"
    )

    @field_validator("cors_origins", "disallowed_tools", "api_keys", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept both JSON arrays and plain comma-separated env values."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return value
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("projection_steps_ahead", mode="before")
    @classmethod
    def _split_steps_ahead(cls, value: object) -> object:
        """Accept both JSON arrays and plain comma-separated env values."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                import json  # noqa: PLC0415

                return json.loads(stripped)
            return [int(item.strip()) for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("drift_score_block")
    @classmethod
    def _thresholds_ordered(cls, value: float, info: object) -> float:
        data = getattr(info, "data", {})
        warn = data.get("drift_score_warn", 0.0)
        escalate = data.get("drift_score_escalate", 0.0)
        if not warn <= escalate <= value:
            raise ValueError(
                "drift thresholds must satisfy warn <= escalate <= block "
                f"(got {warn}, {escalate}, {value})"
            )
        return value

    @field_validator("api_keys")
    @classmethod
    def _production_requires_api_keys(cls, value: list[str], info: object) -> list[str]:
        data = getattr(info, "data", {})
        if data.get("environment") == "production" and not value:
            raise ValueError(
                "ARIADNE_ENV=production requires at least one ARIADNE_API_KEYS entry; "
                "an unauthenticated firewall protects nothing"
            )
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def _production_requires_jwt_secret(cls, value: str, info: object) -> str:
        data = getattr(info, "data", {})
        if data.get("environment") == "production" and not value:
            raise ValueError(
                "ARIADNE_ENV=production requires JWT_SECRET_KEY; generate with "
                '`python -c "import secrets; print(secrets.token_urlsafe(32))"`'
            )
        return value

    @field_validator("admin_password")
    @classmethod
    def _production_requires_admin_bootstrap(cls, value: str | None, info: object) -> str | None:
        data = getattr(info, "data", {})
        if data.get("environment") == "production" and not (data.get("admin_email") and value):
            raise ValueError(
                "ARIADNE_ENV=production requires ARIADNE_ADMIN_EMAIL and "
                "ARIADNE_ADMIN_PASSWORD to bootstrap the first dashboard account"
            )
        return value

    @model_validator(mode="after")
    def _risk_weights_sum_to_one(self) -> Settings:
        """The five risk-dimension weights must combine to a proper weighted average.

        A plain field_validator can only see fields declared *before* it via
        `info.data`, so it can't check five sibling fields against each other
        reliably regardless of declaration order. model_validator(mode="after")
        runs once every field is set and can see the whole model.
        """
        total = (
            self.intent_weight
            + self.tool_weight
            + self.privilege_weight
            + self.identity_weight
            + self.data_weight
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                "intent_weight + tool_weight + privilege_weight + identity_weight + "
                f"data_weight must sum to 1.0 (got {total})"
            )
        return self

    @property
    def graph_backend(self) -> Literal["arcadedb", "networkx"]:
        return "arcadedb" if self.arcadedb_url else "networkx"

    @property
    def hard_layer_backend(self) -> Literal["opa", "builtin"]:
        return "opa" if self.opa_url else "builtin"

    @property
    def job_backend(self) -> Literal["arq", "in_process"]:
        """Declared intent only — actual dispatch also probes connectivity
        (see ariadne.eval.job_runner.enqueue_backtest), since a configured but
        unreachable Redis must still degrade to in-process rather than fail.
        """
        return "arq" if self.redis_url else "in_process"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
