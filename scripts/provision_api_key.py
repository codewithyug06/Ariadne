# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""One-off: mint a real Legacy-Org API key for local/demo use.

Reuses the same ApiKey model and hashing helpers the production
POST /api/v1/keys route uses, so the resulting key authenticates exactly
like one issued through the API -- this just doesn't require an existing
admin session to bootstrap the very first key.

    python scripts/provision_api_key.py
"""

from __future__ import annotations

import asyncio
import uuid

from ariadne.auth.api_keys import generate_api_key, hash_api_key
from ariadne.config import get_settings
from ariadne.db.models import LEGACY_ORG_ID, ApiKey
from ariadne.db.session import Database


async def main_async() -> int:
    settings = get_settings()
    database = Database(settings)
    await database.create_all()

    raw_key, prefix = generate_api_key(LEGACY_ORG_ID)
    row = ApiKey(
        id=uuid.uuid4().hex,
        organization_id=LEGACY_ORG_ID,
        key_hash=hash_api_key(raw_key),
        prefix=prefix,
    )
    async with database.session() as session:
        session.add(row)

    print(f"organization_id: {LEGACY_ORG_ID}")
    print(f"api_key_id: {row.id}")
    print(f"raw_key (save this now, it is never shown again): {raw_key}")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
