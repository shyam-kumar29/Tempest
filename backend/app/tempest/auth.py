"""Small JSON-backed auth store and signed session helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


SESSION_COOKIE_NAME = "tempest_session"
SESSION_TTL_HOURS = 24 * 14
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.@-]{3,80}$")
PASSWORD_ITERATIONS = 210_000


class AuthError(ValueError):
    """Raised for auth validation or credential failures."""


class AuthStoreError(RuntimeError):
    """Raised for auth store I/O or format failures."""


@dataclass(slots=True)
class AuthUser:
    user_id: str
    username: str
    created_at: str

    def to_public_dict(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "created_at": self.created_at,
        }


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def normalize_username(username: str) -> str:
    normalized = username.strip().lower()
    if not USERNAME_RE.fullmatch(normalized):
        raise AuthError("username must be 3-80 letters, numbers, dots, dashes, underscores, or @")
    return normalized


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise AuthError("password must be at least 8 characters")


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    validate_password(password)
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_raw.encode("ascii"))
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def session_secret() -> str:
    return os.environ.get("TEMPEST_SESSION_SECRET", "dev-insecure-change-me")


def sign_session(user_id: str, *, now: datetime | None = None, secret: str | None = None) -> str:
    now = now or datetime.now(UTC)
    expires_at = now + timedelta(hours=SESSION_TTL_HOURS)
    payload = {
        "user_id": user_id,
        "exp": int(expires_at.timestamp()),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_token = base64.urlsafe_b64encode(payload_bytes).decode("ascii")
    secret_bytes = (secret or session_secret()).encode("utf-8")
    signature = hmac.new(secret_bytes, payload_token.encode("ascii"), hashlib.sha256).digest()
    signature_token = base64.urlsafe_b64encode(signature).decode("ascii")
    return f"{payload_token}.{signature_token}"


def _strict_urlsafe_b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)


def verify_session(token: str, *, now: datetime | None = None, secret: str | None = None) -> str | None:
    if "." not in token:
        return None
    payload_token, signature_token = token.split(".", 1)
    secret_bytes = (secret or session_secret()).encode("utf-8")
    expected = hmac.new(secret_bytes, payload_token.encode("ascii"), hashlib.sha256).digest()
    try:
        actual = _strict_urlsafe_b64decode(signature_token)
        payload = json.loads(_strict_urlsafe_b64decode(payload_token).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    if not hmac.compare_digest(actual, expected):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("user_id"), str):
        return None
    now = now or datetime.now(UTC)
    if int(payload.get("exp", 0)) <= int(now.timestamp()):
        return None
    return payload["user_id"]


class JsonUserStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def create_user(self, username: str, password: str) -> AuthUser:
        username = normalize_username(username)
        encoded_password = hash_password(password)
        data = self._load_raw()
        users = self._users_raw(data)
        if any(str(item.get("username", "")).lower() == username for item in users.values()):
            raise AuthError("username is already registered")

        user_id = secrets.token_urlsafe(16)
        created_at = utc_now_iso()
        users[user_id] = {
            "user_id": user_id,
            "username": username,
            "password_hash": encoded_password,
            "created_at": created_at,
        }
        self._save_raw(data)
        return AuthUser(user_id=user_id, username=username, created_at=created_at)

    def authenticate(self, username: str, password: str) -> AuthUser | None:
        username = normalize_username(username)
        data = self._load_raw()
        for raw in self._users_raw(data).values():
            if str(raw.get("username", "")).lower() != username:
                continue
            if not verify_password(password, str(raw.get("password_hash", ""))):
                return None
            return self._user_from_raw(raw)
        return None

    def get_user(self, user_id: str) -> AuthUser | None:
        data = self._load_raw()
        raw = self._users_raw(data).get(user_id)
        if raw is None:
            return None
        return self._user_from_raw(raw)

    def _user_from_raw(self, raw: dict[str, Any]) -> AuthUser:
        return AuthUser(
            user_id=str(raw["user_id"]),
            username=str(raw["username"]),
            created_at=str(raw.get("created_at") or ""),
        )

    def _users_raw(self, data: dict[str, Any]) -> dict[str, Any]:
        users = data.get("users")
        if users is None:
            users = {}
            data["users"] = users
        if not isinstance(users, dict):
            raise AuthStoreError("Invalid auth store format: users must be an object")
        return users

    def _load_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"users": {}}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AuthStoreError(f"Auth store is not valid JSON: {self.path}") from exc
        except OSError as exc:
            raise AuthStoreError(f"Failed reading auth store: {self.path}") from exc
        if not isinstance(raw, dict):
            raise AuthStoreError("Invalid auth store format: root must be an object")
        return raw

    def _save_raw(self, data: dict[str, Any]) -> None:
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self.path.parent),
                prefix=f"{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp_path = Path(tmp.name)
                json.dump(data, tmp, indent=2, sort_keys=True)
                tmp.write("\n")
            os.replace(tmp_path, self.path)
        except OSError as exc:
            raise AuthStoreError(f"Failed writing auth store: {self.path}") from exc
