from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from uuid import UUID

from redis.asyncio import Redis

CAPTCHA_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 600_000


@dataclass(frozen=True)
class AuthAccount:
    id: UUID
    tenant_id: UUID
    username: str
    password_hash: str


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    name: str
    username: str
    roles: list[dict[str, str]]
    permissions: list[str]


@dataclass(frozen=True)
class AuthSession:
    user_id: UUID
    tenant_id: UUID


def generate_captcha_code() -> str:
    return "".join(secrets.choice(CAPTCHA_ALPHABET) for _ in range(5))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, PASSWORD_HASH_ITERATIONS
    )
    return "$".join(
        (
            PASSWORD_HASH_ALGORITHM,
            str(PASSWORD_HASH_ITERATIONS),
            _encode_base64(salt),
            _encode_base64(digest),
        )
    )


def verify_password(password: str, encoded_password: str) -> bool:
    try:
        algorithm, iterations, encoded_salt, expected_digest = encoded_password.split(
            "$", maxsplit=3
        )
        if algorithm != PASSWORD_HASH_ALGORITHM:
            return False
        salt = _decode_base64(encoded_salt)
        expected = _decode_base64(expected_digest)
        calculated = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, int(iterations)
        )
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(calculated, expected)


def _encode_base64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode_base64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _captcha_image_data_url(code: str) -> str:
    text = "".join(
        f'<tspan dx="{secrets.randbelow(5) - 2}">{character}</tspan>'
        for character in code
    )
    noise = "".join(
        f'<path d="M0 {secrets.randbelow(60)} L160 {secrets.randbelow(60)}" stroke="#d9d9d9" />'
        for _ in range(3)
    )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="60" viewBox="0 0 160 60">'
        '<rect width="160" height="60" fill="#f7f9fc" rx="4" />'
        f"{noise}"
        '<text x="18" y="39" fill="#1f3b64" font-family="monospace" font-size="28" font-weight="700" '
        f'letter-spacing="5">{text}</text></svg>'
    )
    return f"data:image/svg+xml;base64,{base64.b64encode(svg.encode()).decode()}"


class AuthService:
    def __init__(
        self,
        redis: Redis,
        *,
        captcha_hmac_secret: str,
        captcha_ttl_seconds: int = 120,
        access_token_ttl_seconds: int = 7200,
        login_max_attempts: int = 5,
        login_rate_limit_seconds: int = 60,
    ) -> None:
        self._redis = redis
        self._captcha_hmac_secret = captcha_hmac_secret.encode()
        self._captcha_ttl_seconds = captcha_ttl_seconds
        self._access_token_ttl_seconds = access_token_ttl_seconds
        self._login_max_attempts = login_max_attempts
        self._login_rate_limit_seconds = login_rate_limit_seconds

    async def create_captcha(self, fingerprint: str) -> tuple[str, str]:
        captcha_id = secrets.token_urlsafe(24)
        code = generate_captcha_code()
        record = {
            "answerHash": self._captcha_hash(captcha_id, code),
            "fingerprint": self._fingerprint_hash(fingerprint),
        }
        await self._redis.set(
            self._captcha_key(captcha_id),
            json.dumps(record, separators=(",", ":")),
            ex=self._captcha_ttl_seconds,
        )
        return captcha_id, _captcha_image_data_url(code)

    async def consume_captcha(
        self, captcha_id: str, captcha_code: str, fingerprint: str
    ) -> bool:
        raw_record = await self._redis.getdel(self._captcha_key(captcha_id))
        if not raw_record:
            return False
        try:
            record = json.loads(raw_record)
            expected_answer = record["answerHash"]
            expected_fingerprint = record["fingerprint"]
        except (TypeError, ValueError, KeyError):
            return False
        return hmac.compare_digest(
            expected_fingerprint, self._fingerprint_hash(fingerprint)
        ) and hmac.compare_digest(
            expected_answer,
            self._captcha_hash(captcha_id, captcha_code.strip().upper()),
        )

    async def allow_login_attempt(self, fingerprint: str) -> bool:
        key = f"auth:login-rate:{self._fingerprint_hash(fingerprint)}"
        attempts = await self._redis.incr(key)
        if attempts == 1:
            await self._redis.expire(key, self._login_rate_limit_seconds)
        return attempts <= self._login_max_attempts

    async def create_session(self, account: AuthAccount) -> str:
        token = secrets.token_urlsafe(32)
        record = {"userId": str(account.id), "tenantId": str(account.tenant_id)}
        await self._redis.set(
            self._session_key(token),
            json.dumps(record, separators=(",", ":")),
            ex=self._access_token_ttl_seconds,
        )
        return token

    async def get_session(self, token: str) -> AuthSession | None:
        session_key = self._session_key(token)
        raw_record = await self._redis.get(session_key)
        if not raw_record:
            return None
        try:
            record = json.loads(raw_record)
            session = AuthSession(
                user_id=UUID(record["userId"]), tenant_id=UUID(record["tenantId"])
            )
        except (TypeError, ValueError, KeyError):
            return None
        if not await self._redis.expire(session_key, self._access_token_ttl_seconds):
            return None
        return session

    async def revoke_session(self, token: str) -> None:
        await self._redis.delete(self._session_key(token))

    def _captcha_hash(self, captcha_id: str, captcha_code: str) -> str:
        return hmac.new(
            self._captcha_hmac_secret,
            f"{captcha_id}:{captcha_code.strip().upper()}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def _fingerprint_hash(self, fingerprint: str) -> str:
        return hmac.new(
            self._captcha_hmac_secret, fingerprint.encode(), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _captcha_key(captcha_id: str) -> str:
        return f"auth:captcha:{captcha_id}"

    @staticmethod
    def _session_key(token: str) -> str:
        return f"auth:session:{token}"
