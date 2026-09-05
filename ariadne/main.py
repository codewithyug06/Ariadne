# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""FastAPI application factory and lifespan wiring."""

from __future__ import annotations

import asyncio
import hmac
import time
import traceback
from datetime import UTC, datetime
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any, cast

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import Counter, Histogram
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import select, update

from ariadne import __version__
from ariadne.api import agents as agents_api
from ariadne.api import alerts as alerts_api
from ariadne.api import analytics as analytics_api
from ariadne.api import auth as auth_api
from ariadne.api import eval as eval_api
from ariadne.api import health as health_api
from ariadne.api import policies as policies_api
from ariadne.api import runs as runs_api
from ariadne.api import settings as settings_api
from ariadne.api import users as users_api
from ariadne.api import websocket as websocket_api
from ariadne.api import keys as keys_api
from ariadne.audit.exporter import ComplianceExporter
from ariadne.audit.recorder import AuditRecorder
from ariadne.auth.security import InvalidTokenError, verify_token, verify_token_hash
from ariadne.config import Settings, get_settings
from ariadne.db.models import LEGACY_ORG_ID, ApiKey
from ariadne.db.session import Database
from ariadne.drift.embedder import ActionEmbedder
from ariadne.drift.scorer import TrajectoryScorer
from ariadne.enforcement.engine import HybridEnforcementEngine
from ariadne.graph.builder import ProvenanceGraphBuilder
from ariadne.graph.store import create_graph_store
from ariadne.intent.anchor import IntentAnchorGenerator
from ariadne.logging import configure_logging, get_logger
from ariadne.proxy.interceptor import ToolCallInterceptor
from ariadne.proxy.mcp_proxy import MCPProxy, create_proxy_router
from ariadne.streaming import DriftStreamHub

logger = get_logger(__name__)

ENFORCEMENT_DECISIONS = Counter(
    "ariadne_enforcement_decisions_total",
    "Enforcement decisions by action and layer.",
    labelnames=("action", "layer"),
)
DRIFT_SCORE_HISTOGRAM = Histogram(
    "ariadne_drift_score",
    "Distribution of composite drift scores.",
    buckets=(10, 20, 30, 40, 50, 60, 65, 70, 80, 85, 90, 95, 100),
)
INTERCEPTION_LATENCY = Histogram(
    "ariadne_interception_latency_seconds",
    "End-to-end interception latency, excluding upstream tool execution.",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Warm every component, in dependency order, with timings."""
    settings: Settings = app.state.settings
    configure_logging(settings.log_level)
    logger.info("ariadne.starting", version=__version__, fail_mode=settings.fail_mode.value)

    started = time.perf_counter()
    database = Database(settings)
    await database.create_all()
    _log_step("database", started)

    step = time.perf_counter()
    recorder = AuditRecorder(database, settings)
    await recorder.start()
    _log_step("audit_recorder", step)

    step = time.perf_counter()
    embedder = ActionEmbedder.instance(settings)
    # Warm the model: the first encode allocates CUDA buffers and would
    # otherwise land on a real user's first tool call.
    embedder.embed_text("Ariadne startup warmup")
    _log_step("embedder", step, backend=embedder.backend, degraded=embedder.is_degraded)

    step = time.perf_counter()
    graph_store = await create_graph_store(settings)
    graph_builder = ProvenanceGraphBuilder(graph_store, settings)
    _log_step("graph_store", step, backend=getattr(graph_store, "backend", "unknown"))

    step = time.perf_counter()
    engine = HybridEnforcementEngine(settings=settings)
    anchors = IntentAnchorGenerator(embedder=embedder, settings=settings)
    scorer = TrajectoryScorer(settings)
    stream_hub = DriftStreamHub()
    http_client = httpx.AsyncClient(timeout=settings.upstream_timeout_seconds)
    interceptor = ToolCallInterceptor(
        embedder=embedder,
        scorer=scorer,
        graph_builder=graph_builder,
        engine=engine,
        anchors=anchors,
        recorder=recorder,
        stream_hub=stream_hub,
        settings=settings,
    )
    proxy = MCPProxy(
        interceptor=interceptor,
        anchors=anchors,
        graph_builder=graph_builder,
        recorder=recorder,
        stream_hub=stream_hub,
        http_client=http_client,
        settings=settings,
        database=database,
    )
    _log_step("enforcement", step, policy_backend=settings.hard_layer_backend)

    app.state.database = database
    app.state.recorder = recorder
    app.state.embedder = embedder
    app.state.graph_store = graph_store
    app.state.graph_builder = graph_builder
    app.state.engine = engine
    app.state.anchors = anchors
    app.state.scorer = scorer
    app.state.stream_hub = stream_hub
    app.state.http_client = http_client
    app.state.interceptor = interceptor
    app.state.proxy = proxy
    app.state.exporter = ComplianceExporter(recorder, graph_builder, settings)

    loaded = await policies_api.load_persisted_policies(app.state)
    await auth_api.bootstrap_admin(app.state)
    await settings_api.load_persisted_overrides(app.state)
    logger.info(
        "ariadne.ready",
        startup_ms=round((time.perf_counter() - started) * 1000.0, 1),
        persisted_policies=loaded,
        upstream_mcp_url=settings.upstream_mcp_url,
        graph_backend=getattr(graph_store, "backend", "unknown"),
        embedder_backend=embedder.backend,
    )

    try:
        yield
    finally:
        logger.info("ariadne.stopping")
        await recorder.stop()
        await engine.aclose()
        await anchors.aclose()
        await http_client.aclose()
        await graph_store.close()
        await database.close()
        ActionEmbedder.reset()
        logger.info("ariadne.stopped")


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header or not header.lower().startswith("bearer "):
        return None
    return header[7:].strip() or None


def _log_step(component: str, started: float, **fields: Any) -> None:
    logger.info(
        "ariadne.component_ready",
        component=component,
        elapsed_ms=round((time.perf_counter() - started) * 1000.0, 1),
        **fields,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the Ariadne ASGI application."""
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)

    app = FastAPI(
        title="Ariadne",
        version=__version__,
        summary="Causal-provenance firewall for multi-agent AI systems",
        description=(
            "Ariadne intercepts every tool call in an agent execution chain, scores its "
            "semantic drift from the user's original intent, records a causal provenance "
            "graph, and enforces hybrid soft/hard policy before the call reaches the real "
            "tool."
        ),
        lifespan=lifespan,
    )
    app.state.settings = resolved

    def _rate_limit_key(request: Request) -> str:
        """Key by presented API key so one leaked/misbehaving client is
        throttled without penalising every other caller sharing an IP
        (common behind a corporate NAT or shared dashboard host)."""
        presented = request.headers.get("x-api-key") or _bearer_token(request)
        return presented or get_remote_address(request)

    limiter = Limiter(
        key_func=_rate_limit_key,
        default_limits=[f"{resolved.rate_limit_per_minute}/minute"],
    )
    app.state.limiter = limiter
    # slowapi's handler is typed against `RateLimitExceeded` specifically;
    # Starlette's registry wants `Exception`, which is safe here since this
    # handler is only ever invoked for that one exception type.
    app.add_exception_handler(
        RateLimitExceeded,
        cast(
            Callable[[Request, Exception], Response],
            _rate_limit_exceeded_handler,
        ),
    )
    app.add_middleware(SlowAPIMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Ariadne-Decision",
            "X-Ariadne-Drift-Score",
            "X-Ariadne-Warning",
            "X-Ariadne-Node-Id",
            "X-Ariadne-Session-Id",
        ],
    )

    app.include_router(create_proxy_router(), prefix="/mcp")
    app.include_router(health_api.router)
    app.include_router(runs_api.router, prefix="/api/v1")
    app.include_router(policies_api.router, prefix="/api/v1")
    app.include_router(auth_api.router, prefix="/api/v1")
    app.include_router(alerts_api.router, prefix="/api/v1")
    app.include_router(analytics_api.router, prefix="/api/v1")
    app.include_router(settings_api.router, prefix="/api/v1")
    app.include_router(users_api.router, prefix="/api/v1")
    app.include_router(keys_api.router, prefix="/api/v1")
    app.include_router(agents_api.router, prefix="/api/v1")
    app.include_router(eval_api.router, prefix="/api/v1")
    app.include_router(websocket_api.router, prefix="/ws")

    # Probe endpoints stay open (load balancers/orchestrators hit these
    # without credentials); the login route has to be reachable by definition
    # of being how you get a token. Everything else requires either a static
    # API key (machine callers — the orchestrator hitting /mcp) or a valid
    # dashboard JWT (a human at the browser) when either is configured.
    _UNAUTHENTICATED_PATHS = {
        "/health",
        "/metrics",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        # Logout validates the refresh cookie itself; gating it behind a
        # possibly-already-expired access token would strand a client that
        # can't log out of a session it can no longer authenticate for.
        "/api/v1/auth/logout",
    }
    _valid_keys = set(resolved.api_keys)

    async def _lookup_db_api_key(request: Request, presented: str) -> bool:
        """Try the ApiKey table: single indexed prefix lookup + bcrypt verify."""
        from ariadne.auth.api_keys import PREFIX_LENGTH, verify_api_key  # noqa: PLC0415

        database: Database = request.app.state.database
        prefix = presented[:PREFIX_LENGTH]
        async with database.session() as session:
            row = await session.scalar(
                select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.revoked_at.is_(None))
            )
            if row is None or not verify_api_key(presented, row.key_hash):
                return False
            request.state.api_key_org_id = row.organization_id
            key_id = row.id

        async def _touch_last_used() -> None:
            try:
                async with database.session() as touch_session:
                    await touch_session.execute(
                        update(ApiKey)
                        .where(ApiKey.id == key_id)
                        .values(last_used_at=datetime.now(UTC))
                    )
            except Exception:  # noqa: BLE001 - best-effort bookkeeping, never blocks auth
                logger.debug("auth.api_key_touch_failed", key_id=key_id)

        # Fire-and-forget: the caller's request must never wait on this write.
        asyncio.create_task(_touch_last_used())
        return True

    @app.middleware("http")
    async def require_api_key(request: Request, call_next: Any) -> Any:
        auth_required = _valid_keys or resolved.jwt_secret_key
        if auth_required and request.url.path not in _UNAUTHENTICATED_PATHS:
            presented = request.headers.get("x-api-key") or _bearer_token(request)

            if presented is not None and await _lookup_db_api_key(request, presented):
                return await call_next(request)

            # Legacy fallback: a raw value from ARIADNE_API_KEYS, bound to the
            # Legacy Org — keeps a deployment that hasn't provisioned real
            # per-tenant ApiKey rows working exactly as before.
            if presented is not None and any(
                hmac.compare_digest(presented, key) for key in _valid_keys
            ):
                request.state.api_key_org_id = LEGACY_ORG_ID
                return await call_next(request)

            if presented is not None and resolved.jwt_secret_key:
                try:
                    request.state.user = verify_token(
                        resolved, presented, expected_type="access"
                    )
                    return await call_next(request)
                except InvalidTokenError:
                    pass

            logger.warning(
                "ariadne.unauthenticated_request",
                path=request.url.path,
                client=request.client.host if request.client else None,
            )
            return JSONResponse(
                status_code=401,
                content={"error": "unauthorized", "detail": "missing or invalid credentials"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

    @app.middleware("http")
    async def observe_decisions(request: Request, call_next: Any) -> Any:
        started = time.perf_counter()
        response = await call_next(request)
        decision = response.headers.get("X-Ariadne-Decision")
        if decision:
            ENFORCEMENT_DECISIONS.labels(
                action=decision, layer=response.headers.get("X-Ariadne-Layer", "unknown")
            ).inc()
            INTERCEPTION_LATENCY.observe(time.perf_counter() - started)
            raw_score = response.headers.get("X-Ariadne-Drift-Score")
            if raw_score:
                with suppress(ValueError):
                    DRIFT_SCORE_HISTOGRAM.observe(float(raw_score))
        return response

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "ariadne.unhandled_exception",
            path=request.url.path,
            method=request.method,
            error=str(exc),
            error_type=type(exc).__name__,
            traceback=traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "detail": f"{type(exc).__name__}: {exc}",
                "path": request.url.path,
            },
        )

    Instrumentator(
        should_group_status_codes=False,
        excluded_handlers=["/metrics", "/health"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=True, tags=["health"])

    return app


app = create_app()
