# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
#
# Multi-stage build. The builder resolves dependencies with uv into a venv the
# runtime copies wholesale, so no build toolchain ships in the final image.

# ---- Builder ---------------------------------------------------------------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer first: it only rebuilds when the manifest changes.
COPY pyproject.toml README.md ./
COPY ariadne/__init__.py ./ariadne/
RUN uv venv /opt/venv \
 && VIRTUAL_ENV=/opt/venv uv pip install --no-cache "." \
 # CPU wheels by default — the CUDA build is ~2.5 GB and is opted into at
 # runtime by mounting a GPU-enabled venv or rebuilding with TORCH_INDEX unset.
 && VIRTUAL_ENV=/opt/venv uv pip install --no-cache \
      --index-url https://download.pytorch.org/whl/cpu torch \
 && VIRTUAL_ENV=/opt/venv uv pip install --no-cache sentence-transformers

# ---- Runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

# curl is used only by the container healthcheck below.
RUN apt-get update \
 && apt-get install --no-install-recommends -y curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 ariadne

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=ariadne:ariadne ariadne ./ariadne
COPY --chown=ariadne:ariadne alembic.ini pyproject.toml README.md LICENSE ./

# Model cache and the SQLite database both live under paths the app user owns.
RUN mkdir -p /app/data /home/ariadne/.cache \
 && chown -R ariadne:ariadne /app/data /home/ariadne/.cache

USER ariadne

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/home/ariadne/.cache/huggingface \
    ARIADNE_HOST=0.0.0.0 \
    ARIADNE_PORT=8000 \
    DATABASE_URL=sqlite+aiosqlite:///./data/ariadne.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

# Single worker by default: the embedding model is held in-process and each
# worker would load its own copy. Scale with replicas, not workers.
CMD ["uvicorn", "ariadne.main:app", "--host", "0.0.0.0", "--port", "8000"]
