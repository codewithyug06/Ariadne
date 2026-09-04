# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Machine API key generation and hashing.

Kept separate from ariadne/auth/security.py (dashboard JWT/password
concerns) even though it reuses the same bcrypt hash-token pattern, because
this module also owns the raw-key format and prefix derivation that both
ariadne/main.py's per-request lookup and ariadne/api/keys.py's issuance
route need to agree on.
"""

from __future__ import annotations

import secrets

from ariadne.auth.security import hash_token, verify_token_hash

#: Leading, deterministic substring of every raw key — stored in the clear,
#: indexed, and used as the lookup key so verifying a presented key is one
#: indexed SELECT + one bcrypt compare, never a scan-and-verify over every
#: key in the table. Must extend past the fixed "ariadne_live_org_<8 hex>_"
#: header (26 chars) into the random suffix, or every key issued to the same
#: org would share an identical prefix and collide on the unique index.
PREFIX_LENGTH = 40


def generate_api_key(organization_id: str) -> tuple[str, str]:
    """Return (raw_key, prefix). The raw key is shown to the caller exactly once."""
    org_short = organization_id.replace("-", "")[:8]
    raw_key = f"ariadne_live_org_{org_short}_{secrets.token_urlsafe(24)}"
    return raw_key, raw_key[:PREFIX_LENGTH]


def hash_api_key(raw_key: str) -> str:
    return hash_token(raw_key)


def verify_api_key(raw_key: str, key_hash: str) -> bool:
    return verify_token_hash(raw_key, key_hash)
