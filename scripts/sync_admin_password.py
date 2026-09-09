# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""One-off: update the existing admin account's password to match .env.

bootstrap_admin() only fires once, on an empty users table, so rotating
ARIADNE_ADMIN_PASSWORD in .env afterward has no effect on an account created
before the rotation. This applies the new password to that existing row
using the same hash_password() the login route verifies against.

    python scripts/sync_admin_password.py
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from ariadne.auth.security import hash_password
from ariadne.config import get_settings
from ariadne.db.models import User
from ariadne.db.session import Database


async def main_async() -> int:
    settings = get_settings()
    if not (settings.admin_email and settings.admin_password):
        print("ARIADNE_ADMIN_EMAIL / ARIADNE_ADMIN_PASSWORD not set in .env")
        return 1

    database = Database(settings)
    async with database.session(bypass_rls=True) as session:
        user = await session.scalar(select(User).where(User.email == settings.admin_email.lower()))
        if user is None:
            print(f"no user found for {settings.admin_email!r}")
            return 1
        user.password_hash = hash_password(settings.admin_password)

    print(f"password updated for {settings.admin_email}")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
