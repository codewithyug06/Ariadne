# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Feature 9: the version stamp attached to every scored event.

Placement note: the spec's suggested home for this module is a new
`ariadne/config/` package, conditional on `ariadne/config.py` being a plain
module rather than a package. It is a plain module here (see
ariadne/config.py), so creating `ariadne/config/` alongside it is not
possible without renaming/relocating that existing file -- out of scope for
this feature and a needless blast radius for a two-function module. This
lives in `ariadne/drift/` instead: drift scoring is the thing being
versioned/stamped (DriftScore gets `calibration_version`,
TrajectoryScorer's formula is `scorer_algorithm_version`), and
`ariadne/drift/schemas.py` / `ariadne/drift/scorer.py` already live here, so
importers of drift internals gain this without a new top-level package.
"""

from __future__ import annotations

from pydantic import BaseModel

from ariadne.config import Settings, get_settings

#: Bump this manually whenever TrajectoryScorer's scoring formula changes in
#: a way that would make historical scores not directly comparable to new
#: ones (e.g. a change to the multiplicative distance/slope combination in
#: ariadne/drift/scorer.py). "2.0.0" is the current multiplicative formula.
SCORER_ALGORITHM_VERSION = "2.0.0"


class ScoringVersionStamp(BaseModel):
    """Everything needed to reproduce -- or explain -- one scored event.

    Attached to every AuditEvent at write time (see
    ariadne/proxy/interceptor.py) so a historical decision can always be
    traced back to exactly which embedding model, calibration profile, risk
    weight set, and scorer formula version produced it, even after any of
    those four things has since changed.
    """

    embedding_model_version: str
    calibration_version: str
    risk_weights_version: str
    scorer_algorithm_version: str


def current_stamp(
    calibration_version: str, settings: Settings | None = None
) -> ScoringVersionStamp:
    """Build the stamp for a score being computed right now.

    `calibration_version` is passed in rather than resolved here because
    resolving it requires a DB lookup (the active CalibrationProfile) and
    this function is meant to be cheap/sync -- callers that have already
    fetched the active profile (or fell back to a documented default) pass
    its version string straight through.
    """
    resolved = settings or get_settings()
    return ScoringVersionStamp(
        embedding_model_version=resolved.embedding_model,
        calibration_version=calibration_version,
        risk_weights_version=resolved.risk_weights_version,
        scorer_algorithm_version=SCORER_ALGORITHM_VERSION,
    )
