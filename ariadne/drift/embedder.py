# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Action embedding.

The primary backend is sentence-transformers on the GPU. Ariadne sits on the
hot path of every tool call, so it must still start and score when the ML
stack or the GPU is unavailable — hence the deterministic hashing backend,
which is a real (if semantically weaker) embedding, not a stub. Which backend
is live is logged loudly at startup and exposed on /health.
"""

from __future__ import annotations

import hashlib
import threading
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import numpy as np

from ariadne.config import Settings, get_settings
from ariadne.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ariadne.proxy.schemas import ToolCall, ToolResult

logger = get_logger(__name__)


@runtime_checkable
class EmbedderProtocol(Protocol):
    """Everything the scorer needs from an embedding backend."""

    @property
    def dimension(self) -> int: ...

    @property
    def backend(self) -> str: ...

    def embed_text(self, text: str) -> np.ndarray: ...

    def embed_texts(self, texts: list[str]) -> np.ndarray: ...


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (vectors / norms).astype(np.float32)


class HashingEmbedder:
    """Deterministic bag-of-token hashing embedder.

    Signed feature hashing over lowercased word tokens, L2-normalised. It has
    no semantic generalisation, but it is stable, dependency-free, and yields
    genuine cosine geometry — enough to keep the firewall enforcing (and the
    test suite honest) when the transformer stack is absent.
    """

    def __init__(self, dimension: int = 384) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def backend(self) -> str:
        return "hashing"

    def embed_text(self, text: str) -> np.ndarray:
        vector = np.zeros(self._dimension, dtype=np.float32)
        tokens = [token for token in _tokenize(text) if token]
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self._dimension
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign
        return _l2_normalize(vector)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        return np.vstack([self.embed_text(text) for text in texts])


def _tokenize(text: str) -> list[str]:
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in text)
    return cleaned.split()


class SentenceTransformerEmbedder:
    """sentence-transformers backend, pinned to CUDA when one is available."""

    def __init__(self, settings: Settings) -> None:
        import torch  # noqa: PLC0415
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        cuda_available = bool(torch.cuda.is_available())
        requested = settings.embedding_device
        if requested == "cuda" and not cuda_available:
            logger.warning(
                "embedder.cuda_unavailable",
                requested_device="cuda",
                resolved_device="cpu",
                hint="install a CUDA build of torch to use the GPU",
            )
            device = "cpu"
        elif requested == "auto":
            device = "cuda" if cuda_available else "cpu"
        else:
            device = requested

        self._device = device
        self._batch_size = settings.embedding_batch_size
        self._model = SentenceTransformer(settings.embedding_model, device=device)
        # fp16 halves VRAM on the 6 GB RTX 4050 and measurably shortens
        # encode latency; MiniLM's cosine geometry is unaffected in practice.
        if device == "cuda":
            self._model = self._model.half()
        # Renamed in sentence-transformers 5.x; support both without pinning.
        get_dimension: Any = (
            getattr(self._model, "get_embedding_dimension", None)
            or self._model.get_sentence_embedding_dimension
        )
        dimension = get_dimension()
        if dimension is None:
            raise RuntimeError(
                f"model {settings.embedding_model!r} did not report an embedding dimension"
            )
        self._dimension = int(dimension)

        logger.info(
            "embedder.loaded",
            backend="sentence-transformers",
            model=settings.embedding_model,
            device=device,
            gpu_name=torch.cuda.get_device_name(0) if device == "cuda" else None,
            batch_size=self._batch_size,
            dimension=self._dimension,
            precision="fp16" if device == "cuda" else "fp32",
        )

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def backend(self) -> str:
        return f"sentence-transformers[{self._device}]"

    def embed_text(self, text: str) -> np.ndarray:
        vector: np.ndarray = self.embed_texts([text])[0]
        return vector

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        vectors = self._model.encode(
            texts,
            batch_size=self._batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


class ActionEmbedder:
    """Process-wide embedding singleton used by the interception hot path."""

    _instance: ActionEmbedder | None = None
    _lock = threading.Lock()

    def __init__(
        self, backend: EmbedderProtocol | None = None, settings: Settings | None = None
    ) -> None:
        self._settings = settings or get_settings()
        self._backend: EmbedderProtocol = backend or self._build_backend(self._settings)

    @staticmethod
    def _build_backend(settings: Settings) -> EmbedderProtocol:
        try:
            return SentenceTransformerEmbedder(settings)
        except ImportError as exc:
            logger.warning(
                "embedder.transformers_unavailable",
                error=str(exc),
                fallback="hashing",
                hint="uv sync --extra embeddings  # installs sentence-transformers + torch",
            )
        except (OSError, RuntimeError, ValueError) as exc:
            # Model download failures, corrupt caches, CUDA init errors.
            logger.error(
                "embedder.load_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                fallback="hashing",
            )
        embedder = HashingEmbedder(settings.embedding_dimension)
        logger.info(
            "embedder.loaded",
            backend="hashing",
            dimension=embedder.dimension,
            degraded=True,
        )
        return embedder

    @classmethod
    def instance(cls, settings: Settings | None = None) -> ActionEmbedder:
        """Return the shared embedder, constructing it on first use."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(settings=settings)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the singleton. Used by tests and by hot-reload paths."""
        with cls._lock:
            cls._instance = None

    @property
    def dimension(self) -> int:
        return self._backend.dimension

    @property
    def backend(self) -> str:
        return self._backend.backend

    @property
    def is_degraded(self) -> bool:
        return self._backend.backend == "hashing"

    def embed_text(self, text: str) -> np.ndarray:
        return self._backend.embed_text(text)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """Batch encode. Used by the eval harness and offline scoring."""
        return self._backend.embed_texts(texts)

    def embed(self, tool_call: ToolCall) -> np.ndarray:
        """Embed a tool call via its natural-language rendering."""
        return self.embed_text(tool_call.to_natural_language())

    def embed_result(self, tool_result: ToolResult) -> np.ndarray:
        """Embed a tool result. Result content is where injections arrive."""
        return self.embed_text(tool_result.to_natural_language())

    def embed_calls(self, tool_calls: list[ToolCall]) -> np.ndarray:
        return self.embed_texts([call.to_natural_language() for call in tool_calls])
