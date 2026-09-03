# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Ariadne command line: serve, inspect runs, export compliance reports."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from ariadne import __version__
from ariadne.audit.exporter import ComplianceExporter, render_markdown
from ariadne.audit.recorder import AuditRecorder
from ariadne.config import get_settings
from ariadne.db.session import Database
from ariadne.graph.builder import ProvenanceGraphBuilder
from ariadne.graph.store import create_graph_store
from ariadne.logging import configure_logging

app = typer.Typer(
    name="ariadne",
    help="Causal-provenance firewall for multi-agent AI systems.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


@app.command()
def version() -> None:
    """Print the Ariadne version."""
    console.print(f"ariadne {__version__}")


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Bind address")] = None,
    port: Annotated[int | None, typer.Option(help="Bind port")] = None,
    reload: Annotated[bool, typer.Option(help="Reload on source changes")] = False,
) -> None:
    """Run the Ariadne proxy and API."""
    import uvicorn  # noqa: PLC0415

    settings = get_settings()
    uvicorn.run(
        "ariadne.main:app",
        host=host or settings.ariadne_host,
        port=port or settings.ariadne_port,
        reload=reload,
        log_config=None,
    )


@app.command("runs")
def list_runs(
    limit: Annotated[int, typer.Option(help="Maximum runs to show")] = 20,
) -> None:
    """List recorded agent runs."""

    async def _run() -> None:
        settings = get_settings()
        configure_logging(settings.log_level, json_output=False)
        database = Database(settings)
        await database.create_all()
        recorder = AuditRecorder(database, settings)
        runs, total = await recorder.list_runs(limit=limit)

        table = Table(title=f"Agent runs ({total} total)", header_style="bold")
        table.add_column("Session")
        table.add_column("Started")
        table.add_column("Steps", justify="right")
        table.add_column("Peak drift", justify="right")
        table.add_column("Status")
        for run in runs:
            table.add_row(
                run.session_id,
                run.started_at.strftime("%Y-%m-%d %H:%M:%S"),
                str(run.total_steps),
                f"{run.max_drift_score:.1f}",
                run.final_status,
            )
        console.print(table)
        await database.close()

    asyncio.run(_run())


@app.command("report")
def export_report(
    session_id: Annotated[str, typer.Argument(help="Session to export")],
    output: Annotated[Path | None, typer.Option(help="Write to this file")] = None,
    fmt: Annotated[str, typer.Option("--format", help="json or markdown")] = "markdown",
) -> None:
    """Export a compliance report for one run."""

    async def _run() -> None:
        settings = get_settings()
        configure_logging(settings.log_level, json_output=False)
        database = Database(settings)
        await database.create_all()
        recorder = AuditRecorder(database, settings)
        store = await create_graph_store(settings)
        exporter = ComplianceExporter(recorder, ProvenanceGraphBuilder(store, settings), settings)

        try:
            report = await exporter.export_run(session_id)
        except KeyError:
            console.print(f"[red]No run recorded for session {session_id!r}[/red]")
            raise typer.Exit(code=1) from None

        rendered = report.model_dump_json(indent=2) if fmt == "json" else render_markdown(report)
        if output:
            output.write_text(rendered, encoding="utf-8")
            console.print(f"Report written to [bold]{output}[/bold]")
        else:
            console.print(rendered)

        await store.close()
        await database.close()

    asyncio.run(_run())


@app.command("check")
def check_config() -> None:
    """Print the resolved configuration and which backends are active.

    The graph and policy backends both fall back silently by design, so this
    is how an operator confirms which one is really in use.
    """
    settings = get_settings()
    table = Table(title="Ariadne configuration", header_style="bold")
    table.add_column("Setting")
    table.add_column("Value")

    rows = [
        ("listen", f"{settings.ariadne_host}:{settings.ariadne_port}"),
        ("upstream MCP", settings.upstream_mcp_url),
        ("fail mode", settings.fail_mode.value),
        ("database", settings.database_url),
        ("graph backend", settings.graph_backend),
        ("policy backend", settings.hard_layer_backend),
        ("embedding model", settings.embedding_model),
        ("embedding device", settings.embedding_device),
        ("embedding batch size", str(settings.embedding_batch_size)),
        ("drift window", str(settings.drift_window_size)),
        ("slope threshold", str(settings.drift_slope_threshold)),
        (
            "thresholds (warn/escalate/block)",
            f"{settings.drift_score_warn:.0f} / {settings.drift_score_escalate:.0f} / "
            f"{settings.drift_score_block:.0f}",
        ),
        ("HITL webhook", settings.hitl_webhook_url or "(not configured - escalations deny)"),
        ("max tool calls/session", str(settings.max_tool_calls_per_session)),
    ]
    for key, value in rows:
        table.add_row(key, value)
    console.print(table)

    try:
        import torch  # noqa: PLC0415

        cuda = torch.cuda.is_available()
        console.print(
            f"CUDA available: {cuda}"
            + (f" ({torch.cuda.get_device_name(0)})" if cuda else " - embeddings run on CPU")
        )
    except ImportError:
        console.print(
            "[yellow]torch is not installed: the hashing fallback embedder will be used. "
            "Install the embeddings extra for semantic scoring.[/yellow]"
        )


if __name__ == "__main__":
    app()
