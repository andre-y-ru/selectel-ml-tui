"""Unit-тесты IAM-авторизации и кэша токена."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

from selectel_ml_tui.auth import (
    IamAuthError,
    IamClient,
    IamToken,
    IamTokenManager,
)
from selectel_ml_tui.config import Credentials, Settings


class FakeIamClient:
    """Заглушка IamClient для проверки логики кэширования."""

    def __init__(self, token: IamToken) -> None:
        self._token = token
        self.calls = 0

    async def get_token(self) -> IamToken:
        self.calls += 1
        return self._token


def _far_future() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=23)


def _expired() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)


async def test_iam_get_token_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert '"name":"svc-user"' in body
        assert '"password":"secret"' in body
        assert '"id":"proj-1"' in body
        return httpx.Response(
            201,
            headers={"X-Subject-Token": "iam-token-abc"},
            json={
                "token": {
                    "expires_at": "2026-08-20T10:00:00.000000Z",
                }
            },
        )

    client = IamClient(
        Settings(),
        Credentials(
            service_user="svc-user",
            password="secret",
            domain_id="239633",
            project_id="proj-1",
        ),
        transport=httpx.MockTransport(handler),
    )
    token = await client.get_token()
    assert token.value == "iam-token-abc"
    assert token.expires_at == dt.datetime(2026, 8, 20, 10, 0, tzinfo=dt.timezone.utc)


async def test_iam_get_token_missing_credentials() -> None:
    client = IamClient(Settings(), Credentials())
    with pytest.raises(IamAuthError, match="логин/пароль"):
        await client.get_token()


async def test_iam_get_token_missing_subject_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201, json={"token": {"expires_at": "2026-08-20T10:00:00Z"}}
        )

    client = IamClient(
        Settings(),
        Credentials(
            service_user="svc", password="pwd", domain_id="239633", project_id="p"
        ),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(IamAuthError, match="X-Subject-Token"):
        await client.get_token()


async def test_iam_token_manager_caches() -> None:
    fake = FakeIamClient(IamToken(value="t1", expires_at=_far_future()))
    manager = IamTokenManager(fake)  # type: ignore[arg-type]
    assert await manager.get_token() == "t1"
    assert await manager.get_token() == "t1"
    assert fake.calls == 1
    assert manager.is_valid()


async def test_iam_token_manager_refreshes_after_expiry() -> None:
    fake = FakeIamClient(IamToken(value="t-expired", expires_at=_expired()))
    manager = IamTokenManager(fake)  # type: ignore[arg-type]
    assert await manager.get_token() == "t-expired"
    assert not manager.is_valid()
    assert await manager.get_token() == "t-expired"
    assert fake.calls == 2


async def test_iam_token_manager_invalidate() -> None:
    fake = FakeIamClient(IamToken(value="t1", expires_at=_far_future()))
    manager = IamTokenManager(fake)  # type: ignore[arg-type]
    await manager.get_token()
    assert manager.is_valid()
    manager.invalidate()
    assert not manager.is_valid()
    await manager.get_token()
    assert fake.calls == 2
