# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Structured decomposition of a user request into goal, constraints and prohibitions."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import ValidationError

from ariadne.config import Settings, get_settings
from ariadne.intent.schemas import DecomposedIntent, RiskLevel
from ariadne.logging import get_logger

logger = get_logger(__name__)

EXTRACTION_PROMPT = """You are a security analyst. Extract the structured intent from a user's \
request to an AI agent.

Return ONLY valid JSON, no prose, no markdown fences, with exactly these keys:
{{
  "goal": "<one sentence describing the primary goal>",
  "constraints": ["<constraint the agent must respect>", ...],
  "disallowed_actions": ["<action the user has explicitly or implicitly prohibited>", ...],
  "risk_level": "low" | "medium" | "high"
}}

Rules:
- "constraints" are limits on HOW the goal may be achieved (budgets, scopes, read-only).
- "disallowed_actions" are concrete operations the agent must never perform for this request.
- If the request is read-only in nature, include write/send/delete operations as disallowed.
- risk_level is "high" when the request touches money, credentials, or destructive operations.

User request:
\"\"\"{request}\"\"\"

JSON:"""

#: Phrases that mark a prohibition in plain English, used by the offline fallback.
_PROHIBITION_PATTERNS = (
    r"\bdo not\s+([^.;,\n]+)",
    r"\bdon't\s+([^.;,\n]+)",
    r"\bnever\s+([^.;,\n]+)",
    r"\bmust not\s+([^.;,\n]+)",
    r"\bwithout\s+([^.;,\n]+)",
    r"\bno\s+(writes?|deletes?|purchases?|payments?|emails?)\b",
)

_CONSTRAINT_PATTERNS = (
    r"\bonly\s+([^.;,\n]+)",
    r"\bmust\s+(?!not)([^.;,\n]+)",
    r"\bunder\s+(\$?\d[^.;,\n]*)",
    r"\bwithin\s+([^.;,\n]+)",
    r"\bat most\s+([^.;,\n]+)",
    r"\bread[- ]only\b",
)

_HIGH_RISK_TERMS = (
    "payment",
    "pay ",
    "charge",
    "transfer",
    "invoice",
    "wire",
    "refund",
    "delete",
    "drop",
    "destroy",
    "credential",
    "password",
    "api key",
    "secret",
    "admin",
    "root",
    "production",
)
_MEDIUM_RISK_TERMS = ("write", "update", "send", "email", "post", "deploy", "modify")


class IntentDecomposer:
    """Extracts structured intent, preferring a local LLM and degrading cleanly.

    Ollama is optional by design: Ariadne must protect a run even on a host
    with no LLM available, so failure here downgrades extraction quality
    rather than failing the request.
    """

    def __init__(
        self, settings: Settings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None
        self._model = self._settings.ollama_model
        self._llm_available = True

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._settings.ollama_timeout_seconds)
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def decompose(self, raw_text: str) -> tuple[DecomposedIntent, str]:
        """Return the decomposition and the source that produced it."""
        if not raw_text.strip():
            return DecomposedIntent(goal="[heuristic] (empty request)"), "heuristic"

        if self._llm_available:
            decomposed = await self._decompose_via_llm(raw_text)
            if decomposed is not None:
                return decomposed, f"ollama:{self._model}"

        return self._heuristic(raw_text), "heuristic"

    async def _decompose_via_llm(self, raw_text: str) -> DecomposedIntent | None:
        prompt = EXTRACTION_PROMPT.format(request=raw_text)
        client = await self._get_client()
        models = [self._settings.ollama_model, self._settings.ollama_fallback_model]

        for model in models:
            for attempt in range(1, self._settings.decomposer_max_retries + 1):
                try:
                    response = await client.post(
                        f"{self._settings.ollama_url.rstrip('/')}/api/generate",
                        json={
                            "model": model,
                            "prompt": prompt,
                            "stream": False,
                            "format": "json",
                            "options": {"temperature": 0.0},
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                    logger.warning(
                        "decomposer.ollama_unreachable",
                        url=self._settings.ollama_url,
                        error=str(exc),
                        fallback="heuristic",
                    )
                    # No LLM on this host: stop trying for the process lifetime.
                    self._llm_available = False
                    return None
                except httpx.HTTPStatusError as exc:
                    logger.warning(
                        "decomposer.ollama_http_error",
                        model=model,
                        status_code=exc.response.status_code,
                        attempt=attempt,
                    )
                    break  # try the next model
                except (httpx.HTTPError, json.JSONDecodeError) as exc:
                    logger.warning(
                        "decomposer.ollama_request_failed",
                        model=model,
                        attempt=attempt,
                        error=str(exc),
                        error_type=type(exc).__name__,
                    )
                    continue

                parsed = self._parse_response(payload.get("response", ""))
                if parsed is not None:
                    self._model = model
                    logger.info(
                        "decomposer.extracted",
                        model=model,
                        attempt=attempt,
                        risk_level=parsed.risk_level.value,
                        constraint_count=len(parsed.constraints),
                    )
                    return parsed

                logger.warning("decomposer.parse_failed", model=model, attempt=attempt)

        logger.warning("decomposer.exhausted_retries", fallback="heuristic")
        return None

    @staticmethod
    def _parse_response(text: str) -> DecomposedIntent | None:
        """Extract and validate the JSON object from a model response."""
        if not text:
            return None
        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.MULTILINE)
        start, end = candidate.find("{"), candidate.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data: Any = json.loads(candidate[start : end + 1])
            return DecomposedIntent.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            return None

    @staticmethod
    def _heuristic(raw_text: str) -> DecomposedIntent:
        """Regex-based extraction used when no LLM is reachable.

        Deliberately conservative: it mines only unambiguous prohibition and
        limitation phrasing, because a wrong constraint here becomes a wrong
        `contradicts` edge in the provenance graph.
        """
        lowered = raw_text.lower()

        disallowed: list[str] = []
        for pattern in _PROHIBITION_PATTERNS:
            disallowed.extend(match.strip() for match in re.findall(pattern, lowered))

        constraints: list[str] = []
        for pattern in _CONSTRAINT_PATTERNS:
            found = re.findall(pattern, lowered)
            constraints.extend(
                (match if isinstance(match, str) else " ".join(match)).strip() for match in found
            )

        if any(term in lowered for term in _HIGH_RISK_TERMS):
            risk = RiskLevel.HIGH
        elif any(term in lowered for term in _MEDIUM_RISK_TERMS):
            risk = RiskLevel.MEDIUM
        else:
            risk = RiskLevel.LOW

        return DecomposedIntent(
            goal=f"[heuristic] {raw_text.strip()}",
            constraints=_dedupe(constraints),
            disallowed_actions=_dedupe(disallowed),
            risk_level=risk,
        )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
