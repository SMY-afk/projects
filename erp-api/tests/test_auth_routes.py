from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from erp_api.main import app
from erp_api.services.auth import AuthAccount, AuthService, CurrentUser, hash_password


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expirations: list[tuple[str, int]] = []

    async def set(self, key: str, value: str, *, ex: int) -> None:
        del ex
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)

    async def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)

    async def incr(self, key: str) -> int:
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> bool:
        self.expirations.append((key, seconds))
        return True


@dataclass(frozen=True)
class FakeAuthRepository:
    account: AuthAccount
    user: CurrentUser

    async def find_account_by_username(self, username: str) -> AuthAccount | None:
        return self.account if username == self.account.username else None

    async def get_current_user(
        self, user_id: UUID, tenant_id: UUID
    ) -> CurrentUser | None:
        if user_id == self.account.id and tenant_id == self.account.tenant_id:
            return self.user
        return None


def test_auth_flow_uses_password_only_and_revokes_the_server_session(
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    account = AuthAccount(
        id=user_id,
        tenant_id=tenant_id,
        username="admin",
        password_hash=hash_password("correct-password"),
    )
    current_user = CurrentUser(
        id=user_id,
        name="管理员",
        username="admin",
        roles=[{"id": str(uuid4()), "code": "admin", "name": "管理员"}],
        permissions=["dashboard:read"],
    )
    monkeypatch.setattr("erp_api.services.auth.generate_captcha_code", lambda: "ABCDE")
    monkeypatch.setattr(
        app.state,
        "auth_service",
        AuthService(FakeRedis(), captcha_hmac_secret="test-only-secret"),
    )
    monkeypatch.setattr(
        app.state, "auth_repository", FakeAuthRepository(account, current_user)
    )

    with TestClient(app) as client:
        invalid_login = client.post(
            "/api/auth/login",
            json={
                "username": "admin",
                "password": "wrong-password",
            },
            headers={"User-Agent": "pytest"},
        )
        assert invalid_login.status_code == 401
        assert invalid_login.headers["www-authenticate"] == "Bearer"
        assert invalid_login.json()["code"] == "unauthorized"

        unknown_login = client.post(
            "/api/auth/login",
            json={
                "username": "unknown-user",
                "password": "correct-password",
            },
            headers={"User-Agent": "pytest"},
        )
        assert unknown_login.status_code == 401
        login = client.post(
            "/api/auth/login",
            json={
                "username": "admin",
                "password": "correct-password",
            },
            headers={"User-Agent": "pytest"},
        )
        assert login.status_code == 200
        assert login.headers["cache-control"] == "no-store"
        token = login.json()["accessToken"]

        authorization = {"Authorization": f"Bearer {token}"}
        current = client.get("/api/auth/current-user", headers=authorization)
        assert current.status_code == 200
        assert current.json()["username"] == "admin"

        logout = client.post("/api/auth/logout", headers=authorization)
        assert logout.status_code == 204
        expired_current_user = client.get(
            "/api/auth/current-user", headers=authorization
        )
        assert expired_current_user.status_code == 401
        assert expired_current_user.json()["code"] == "unauthorized"


def test_password_only_login_still_limits_repeated_attempts(monkeypatch) -> None:
    account = AuthAccount(
        id=uuid4(),
        tenant_id=uuid4(),
        username="rate-test",
        password_hash=hash_password("correct-password"),
    )
    redis = FakeRedis()
    service = AuthService(
        redis, captcha_hmac_secret="test-only-secret", login_max_attempts=2
    )
    user = CurrentUser(
        id=account.id,
        name="Tester",
        username=account.username,
        roles=[],
        permissions=[],
    )
    monkeypatch.setattr(app.state, "auth_service", service)
    monkeypatch.setattr(app.state, "auth_repository", FakeAuthRepository(account, user))
    with TestClient(app) as client:
        for _ in range(2):
            response = client.post(
                "/api/auth/login",
                json={"username": account.username, "password": "wrong"},
            )
            assert response.status_code == 401
        blocked = client.post(
            "/api/auth/login",
            json={"username": account.username, "password": "correct-password"},
        )
        assert blocked.status_code == 401
    assert len(redis.expirations) == 1 and redis.expirations[0][1] == 60
    assert not any(key.startswith("auth:session:") for key in redis.values)


def test_authenticated_request_renews_the_session_idle_timeout(monkeypatch) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    account = AuthAccount(
        id=user_id,
        tenant_id=tenant_id,
        username="admin",
        password_hash=hash_password("correct-password"),
    )
    current_user = CurrentUser(
        id=user_id,
        name="管理员",
        username="admin",
        roles=[],
        permissions=[],
    )
    redis = FakeRedis()
    auth_service = AuthService(
        redis, captcha_hmac_secret="test-only-secret", access_token_ttl_seconds=7200
    )
    monkeypatch.setattr(app.state, "auth_service", auth_service)
    monkeypatch.setattr(
        app.state, "auth_repository", FakeAuthRepository(account, current_user)
    )

    token = asyncio.run(auth_service.create_session(account))
    redis.expirations.clear()

    with TestClient(app) as client:
        response = client.get(
            "/api/auth/current-user", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200
    assert redis.expirations == [(f"auth:session:{token}", 7200)]
