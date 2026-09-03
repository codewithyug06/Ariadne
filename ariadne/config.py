# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Central configuration for Ariadne, sourced entirely from the environment."""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    cors_origins: list[str] = Field(default=["http://localhost:5173"], alias="CORS_ORIGINS")
    # "production" refuses to start with an empty api_keys list — an
    # unauthenticated firewall protecting nothing is worse than none at all.
    environment: Literal["development", "production"] = Field(
        default="development", alias="ARIADNE_ENV"
    )
    # Bearer tokens accepted on every route except /health and /metrics.
    # Comma-separated; generate with e.g. `python -c "import secrets;
    # print(secrets.token_urlsafe(32))"`.
    api_keys: list[str] = Field(default_factory=list, alias="ARIADNE_API_KEYS")
    # Requests per minute, per API key (or per client IP when unauthenticated
    # in dev mode). A leaked key shouldn't be able to hammer the proxy or the
    # embedder unbounded.
    rate_limit_per_minute: int = Field(default=120, alias="RATE_LIMIT_PER_MINUTE")

    # ---- Upstream MCP -----------------------------------------------------
    upstream_mcp_url: str = Field(default="http://localhost:9000/mcp", alias="UPSTREAM_MCP_URL")
    upstream_timeout_seconds: float = Field(default=30.0, alias="UPSTREAM_TIMEOUT_SECONDS")
    fail_mode: FailMode = Field(default=FailMode.FAIL_CLOSED, alias="FAIL_MODE")

    # ---- Persistence ------------------------------------------------------
    database_url: str = Field(default="sqlite+aiosqlite:///./ariadne.db", alias="DATABASE_URL")
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
    drift_score_escalate: float = Field(default=65.0, alias="DRIFT_SCORE_ESCALATE")
    drift_score_block: float = Field(default=85.0, alias="DRIFT_SCORE_BLOCK")

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
    disallowed_tools: list[str] = Field(default_factory=list, alias="DISALLOWED_TOOLS")

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

    @property
    def graph_backend(self) -> Literal["arcadedb", "networkx"]:
        return "arcadedb" if self.arcadedb_url else "networkx"

    @property
    def hard_layer_backend(self) -> Literal["opa", "builtin"]:
        return "opa" if self.opa_url else "builtin"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
