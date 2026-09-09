# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""The intent anchor: embedded once per session, compared against forever after."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from ariadne.config import Settings, get_settings
from ariadne.drift.embedder import ActionEmbedder
from ariadne.intent.decomposer import IntentDecomposer
from ariadne.intent.schemas import IntentAnchorSummary, RiskLevel
from ariadne.logging import get_logger
from ariadne.proxy.schemas import utcnow

logger = get_logger(__name__)

#: Anchors are small (a 384-float vector plus text) but unbounded growth in a
#: long-lived proxy is still a leak, so the cache is bounded and LRU-evicted.
DEFAULT_CACHE_SIZE = 1000


@dataclass(slots=True)
class IntentAnchor:
    """The immutable semantic reference point for one session."""

    session_id: str
    raw_text: str
    embedding: np.ndarray
    goal: str
    constraints: list[str] = field(default_factory=list)
    disallowed_actions: list[str] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    decomposition_source: str = "heuristic"
    created_at: datetime = field(default_factory=utcnow)

    def summary(self) -> IntentAnchorSummary:
        return IntentAnchorSummary(
            session_id=self.session_id,
            raw_text=self.raw_text,
            goal=self.goal,
            constraints=list(self.constraints),
            disallowed_actions=list(self.disallowed_actions),
            risk_level=self.risk_level,
            embedding_dimension=int(self.embedding.shape[0]),
            decomposition_source=self.decomposition_source,
        )

    def violated_prohibitions(self, text: str) -> list[str]:
        """Prohibitions from the anchor that `text` appears to breach.

        Token-overlap on stems rather than substring matching: "send an email
        to finance" has to match the prohibition "send emails", which a plain
        substring test misses.

        Each prohibition is split into clauses first. "Do not send emails or
        share the document with anyone" is two separate prohibitions, and
        scoring it as one long phrase buries a full match on "send emails"
        under five unmatched tokens from the other clause — which is exactly
        how a goal-hijack email slipped through in testing.
        """
        haystack = {_stem(token) for token in _tokens(text)}
        breached: list[str] = []
        for prohibition in self.disallowed_actions:
            for clause in _split_clauses(prohibition):
                needles = [token for token in _tokens(clause) if token not in _STOPWORDS]
                if not needles:
                    continue
                # The leading word of a clause carries the prohibited verb
                # ("fix", "send", "delete"); the trailing words are usually
                # just its object. Splitting "modify or fix the checkout
                # service" on "or" produces the clause "fix the checkout
                # service", whose object nouns ("checkout", "service") alone
                # matched a read-only "get service status: checkout" call,
                # tripping a false contradiction even though the call never
                # fixes or modifies anything. Requiring the verb itself to
                # appear closes that gap without weakening true matches like
                # "send emails" vs "send_email to finance".
                if _stem(needles[0]) not in haystack:
                    continue
                matched = sum(1 for token in needles if _stem(token) in haystack)
                if matched / len(needles) >= 0.6:
                    breached.append(prohibition)
                    break
        return breached


_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "to",
        "of",
        "for",
        "and",
        "or",
        "any",
        "all",
        "it",
        "this",
        "that",
        "in",
        "on",
    }
)


#: Conjunctions that join independent prohibitions in one sentence.
_CLAUSE_SEPARATORS = (" or ", " and ", ", ", ";", " nor ")


def _split_clauses(prohibition: str) -> list[str]:
    """Break a compound prohibition into independently matchable clauses."""
    clauses = [prohibition]
    for separator in _CLAUSE_SEPARATORS:
        expanded: list[str] = []
        for clause in clauses:
            expanded.extend(part for part in clause.split(separator) if part.strip())
        clauses = expanded
    return [prohibition, *[clause.strip() for clause in clauses if clause.strip()]]


def _tokens(text: str) -> list[str]:
    cleaned = "".join(char.lower() if char.isalnum() else " " for char in text)
    return cleaned.split()


def _stem(token: str) -> str:
    """Crude suffix stripping so 'emails'/'email' and 'sending'/'send' unify."""
    for suffix in ("ing", "ies", "es", "ed", "s"):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


class IntentAnchorGenerator:
    """Builds and caches one anchor per session."""

    def __init__(
        self,
        embedder: ActionEmbedder | None = None,
        decomposer: IntentDecomposer | None = None,
        settings: Settings | None = None,
        cache_size: int = DEFAULT_CACHE_SIZE,
    ) -> None:
        self._settings = settings or get_settings()
        self._embedder = embedder or ActionEmbedder.instance(self._settings)
        self._decomposer = decomposer or IntentDecomposer(self._settings)
        self._cache: OrderedDict[str, IntentAnchor] = OrderedDict()
        self._cache_size = cache_size

    async def generate(self, session_id: str, raw_text: str) -> IntentAnchor:
        """Create the anchor for a session, or return the cached one."""
        cached = self.get(session_id)
        if cached is not None:
            return cached

        decomposed, source = await self._decomposer.decompose(raw_text)

        # The goal sentence carries the mission more cleanly than the raw
        # request (which often includes pasted context), but a heuristic goal
        # is just the raw text again, so both are embedded together.
        anchor_text = raw_text if decomposed.is_heuristic else f"{decomposed.goal}\n{raw_text}"
        embedding = self._embedder.embed_text(anchor_text)

        anchor = IntentAnchor(
            session_id=session_id,
            raw_text=raw_text,
            embedding=embedding,
            goal=decomposed.goal,
            constraints=decomposed.constraints,
            disallowed_actions=decomposed.disallowed_actions,
            risk_level=decomposed.risk_level,
            decomposition_source=source,
        )
        self._put(anchor)
        logger.info(
            "intent.anchor_created",
            session_id=session_id,
            source=source,
            risk_level=decomposed.risk_level.value,
            constraint_count=len(decomposed.constraints),
            disallowed_count=len(decomposed.disallowed_actions),
            embedding_dimension=int(embedding.shape[0]),
        )
        return anchor

    def get(self, session_id: str) -> IntentAnchor | None:
        anchor = self._cache.get(session_id)
        if anchor is not None:
            self._cache.move_to_end(session_id)
        return anchor

    def _put(self, anchor: IntentAnchor) -> None:
        self._cache[anchor.session_id] = anchor
        self._cache.move_to_end(anchor.session_id)
        while len(self._cache) > self._cache_size:
            evicted_id, _ = self._cache.popitem(last=False)
            logger.debug("intent.anchor_evicted", session_id=evicted_id)

    def discard(self, session_id: str) -> None:
        self._cache.pop(session_id, None)

    async def aclose(self) -> None:
        await self._decomposer.aclose()

    def __len__(self) -> int:
        return len(self._cache)
