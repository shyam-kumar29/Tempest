from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tempest.auth import (
    JsonUserStore,
    hash_password,
    sign_session,
    verify_password,
    verify_session,
)


def test_password_hashing_verifies_without_plaintext() -> None:
    encoded = hash_password("correct horse battery staple")

    assert "correct horse battery staple" not in encoded
    assert verify_password("correct horse battery staple", encoded) is True
    assert verify_password("wrong password", encoded) is False


def test_session_signature_and_expiry() -> None:
    now = datetime(2026, 4, 4, 18, tzinfo=UTC)
    token = sign_session("user-123", now=now, secret="secret")

    assert verify_session(token, now=now + timedelta(minutes=1), secret="secret") == "user-123"
    assert verify_session(token, now=now + timedelta(days=20), secret="secret") is None
    assert verify_session(token + "tampered", now=now, secret="secret") is None


def test_json_user_store_signup_and_authenticate(tmp_path) -> None:
    store = JsonUserStore(tmp_path / "users.json")

    user = store.create_user("Pilot.One", "correct horse battery staple")

    assert user.username == "pilot.one"
    assert store.authenticate("pilot.one", "correct horse battery staple") == user
    assert store.authenticate("pilot.one", "wrong password") is None
    assert store.get_user(user.user_id) == user
