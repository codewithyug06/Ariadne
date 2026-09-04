# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""Password hashing and JWT issue/verify — ariadne/auth/security.py."""

from __future__ import annotations

import time

import pytest

from ariadne.auth.security import (
    InvalidTokenError,
    hash_password,
    hash_token,
    issue_token,
    verify_password,
    verify_token,
    verify_token_hash,
)
from ariadne.config import Settings


@pytest.fixture
def auth_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "jwt_secret_key": "test-only-secret-do-not-use-in-production",
            "jwt_access_token_minutes": 15,
            "jwt_refresh_token_days": 14,
        }
    )


class TestPasswordHashing:
    def test_correct_password_verifies(self) -> None:
        hashed = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", hashed)

    def test_wrong_password_is_rejected(self) -> None:
        hashed = hash_password("correct horse battery staple")
        assert not verify_password("wrong password", hashed)

    def test_hash_is_never_the_plaintext(self) -> None:
        hashed = hash_password("hunter2")
        assert hashed != "hunter2"

    def test_malformed_stored_hash_denies_rather_than_crashes(self) -> None:
        assert not verify_password("anything", "not-a-real-bcrypt-hash")


class TestTokenHashing:
    def test_correct_token_verifies(self) -> None:
        hashed = hash_token("some-refresh-token-value")
        assert verify_token_hash("some-refresh-token-value", hashed)

    def test_wrong_token_is_rejected(self) -> None:
        hashed = hash_token("some-refresh-token-value")
        assert not verify_token_hash("a-different-token", hashed)


class TestJWT:
    def test_issued_access_token_verifies(self, auth_settings: Settings) -> None:
        token, payload = issue_token(
            auth_settings, user_id="u1", role="admin", token_type="access"
        )
        verified = verify_token(auth_settings, token, expected_type="access")
        assert verified.user_id == "u1"
        assert verified.role == "admin"
        assert verified.jti == payload.jti

    def test_refresh_token_rejected_as_access(self, auth_settings: Settings) -> None:
        token, _ = issue_token(auth_settings, user_id="u1", role="viewer", token_type="refresh")
        with pytest.raises(InvalidTokenError):
            verify_token(auth_settings, token, expected_type="access")

    def test_tampered_token_is_rejected(self, auth_settings: Settings) -> None:
        token, _ = issue_token(auth_settings, user_id="u1", role="admin", token_type="access")
        tampered = token[:-4] + ("A" if token[-4] != "A" else "B") + token[-3:]
        with pytest.raises(InvalidTokenError):
            verify_token(auth_settings, tampered, expected_type="access")

    def test_expired_token_is_rejected(self, auth_settings: Settings) -> None:
        short_lived = auth_settings.model_copy(
            update={"jwt_access_token_minutes": 0}
        )
        token, _ = issue_token(short_lived, user_id="u1", role="admin", token_type="access")
        time.sleep(1.1)
        with pytest.raises(InvalidTokenError):
            verify_token(short_lived, token, expected_type="access")

    def test_token_signed_with_a_different_secret_is_rejected(self, auth_settings: Settings) -> None:
        token, _ = issue_token(auth_settings, user_id="u1", role="admin", token_type="access")
        other = auth_settings.model_copy(update={"jwt_secret_key": "a-completely-different-secret"})
        with pytest.raises(InvalidTokenError):
            verify_token(other, token, expected_type="access")
