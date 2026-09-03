# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Entry point for the scenario evaluation.

Thin wrapper over the red-team runner so the eval harness and the test suite
measure exactly the same thing — a separate implementation here would let the
two drift apart, and the numbers in the README would stop meaning anything.
"""

from __future__ import annotations

from tests.red_team.run_scenarios import main

if __name__ == "__main__":
    raise SystemExit(main())
