"""IAM-авторизация Selectel.

Получение и кэширование IAM-токена проекта через
POST {identity_url}/auth/tokens (сервисный пользователь, scope project).
Время жизни токена — 24 часа; IamTokenManager автоматически обновляет токен
при приближении к истечению (запас 5 минут).
"""

from __future__ import annotations

import datetime as dt
from typing import cast

import httpx
from pydantic import BaseModel, ConfigDict, Field

from selectel_ml_tui.config import Credentials, Settings


class IamToken(BaseModel):
    """IAM-токен с временем жизни."""

    model_config = ConfigDict(populate_by_name=True)

    value: str = Field(alias="X-Subject-Token")
    issued_at: dt.datetime = Field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc)
    )
    expires_at: dt.datetime = Field(alias="expires_at")


class IamAuthError(RuntimeError):
    """Ошибка получения IAM-токена."""


def _parse_expires_at(raw: str) -> dt.datetime:
    """Распарсить expires_at из ответа IAM (ISO8601, возможно с 'Z')."""
    text = raw.replace("Z", "+00:00")
    return dt.datetime.fromisoformat(text)


class IamClient:
    """Клиент получения IAM-токена проекта."""

    def __init__(
        self,
        settings: Settings,
        credentials: Credentials,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._credentials = credentials
        self._transport = transport

    async def get_token(self) -> IamToken:
        """Получить IAM-токен проекта для аккаунта/домена."""
        if not self._credentials.service_user or not self._credentials.password:
            raise IamAuthError(
                "Не заданы логин/пароль сервисного пользователя. "
                "Выполните: selectel-ml-tui config"
            )
        body = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": self._credentials.service_user,
                            "domain": {"name": self._credentials.domain_id},
                            "password": self._credentials.password,
                        }
                    },
                },
                "scope": {"project": {"id": self._credentials.project_id}},
            }
        }
        url = f"{self._settings.identity_url}/auth/tokens"
        try:
            async with httpx.AsyncClient(
                timeout=30, transport=self._transport
            ) as client:
                response = await client.post(url, json=body)
        except httpx.HTTPError as exc:
            raise IamAuthError(f"Ошибка сети при обращении к {url}: {exc}") from exc
        if response.status_code not in (200, 201):
            raise IamAuthError(
                f"IAM: HTTP {response.status_code}: {response.text[:300]}"
            )
        token = cast(str | None, response.headers.get("X-Subject-Token"))
        if not token:
            raise IamAuthError("IAM: отсутствует заголовок X-Subject-Token в ответе")
        data = response.json()
        expires_raw = (
            data.get("token", {}).get("expires_at") if isinstance(data, dict) else None
        )
        if not isinstance(expires_raw, str):
            raise IamAuthError("IAM: отсутствует поле token.expires_at в ответе")
        return IamToken.model_validate(
            {
                "X-Subject-Token": token,
                "expires_at": _parse_expires_at(expires_raw),
            }
        )


class IamTokenManager:
    """Кэширует IAM-токен и обновляет его по истечении TTL.

    Позволяет разделить получение токена и его использование клиентами.
    """

    SAFETY_MARGIN = dt.timedelta(minutes=5)

    def __init__(self, client: IamClient) -> None:
        self._client = client
        self._token: str | None = None
        self._expires_at: dt.datetime | None = None

    def invalidate(self) -> None:
        """Сбросить кэш (например, после HTTP 401)."""
        self._token = None
        self._expires_at = None

    def is_valid(self) -> bool:
        if self._token is None or self._expires_at is None:
            return False
        now = dt.datetime.now(dt.timezone.utc)
        return self._expires_at > now + self.SAFETY_MARGIN

    async def get_token(self) -> str:
        """Вернуть валидный токен, при необходимости обновив его."""
        if self.is_valid():
            return cast(str, self._token)
        iam_token = await self._client.get_token()
        self._token = iam_token.value
        self._expires_at = iam_token.expires_at
        return iam_token.value
