"""Клиент Gateway API ИИ-роутера Selectel (/aig/gateway/v1/*).

Аутентификация: IAM-токен проекта (X-Auth-Token) + X-Project-Id и др.
Данные: потребление (overview), метрики 24ч, модели, ключи.

Токен берётся из IamTokenManager; при HTTP 401 выполняется его
автоматическое обновление и один повтор запроса.
"""

from __future__ import annotations

from typing import Any, cast

import httpx

from selectel_ml_tui.api.client import BaseApiClient, SelectelApiError
from selectel_ml_tui.auth import IamTokenManager
from selectel_ml_tui.models import RouterMetrics, RouterOverview

GatewayApiError = SelectelApiError


class GatewayClient(BaseApiClient):
    """Клиент /aig/gateway/v1/*."""

    def __init__(
        self,
        api_base_url: str,
        token_provider: IamTokenManager,
        project_id: str,
        domain_id: str,
        timeout: float = 30.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Any = None,
    ) -> None:
        super().__init__(
            timeout=timeout,
            max_retries=max_retries,
            transport=transport,
            sleep=sleep,
        )
        self._base_url = api_base_url.rstrip("/")
        self._token_provider = token_provider
        self._project_id = project_id
        self._domain_id = domain_id

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "X-Auth-Token": token,
            "X-Project-Id": self._project_id,
            "X-Project-Domain-Id": self._domain_id,
            "X-Project-Domain-Name": self._domain_id,
            "X-Roles": "reader",
            "Content-Type": "application/json",
        }

    async def _get(self, path: str) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        token = await self._token_provider.get_token()
        try:
            response = await self.request("GET", url, headers=self._headers(token))
        except SelectelApiError as exc:
            if exc.status_code == 401:
                self._token_provider.invalidate()
                token = await self._token_provider.get_token()
                response = await self.request("GET", url, headers=self._headers(token))
            else:
                raise
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            raise GatewayApiError(f"Gateway API: {data['error']}")
        return cast(dict[str, Any], data)

    async def list_gateways(self) -> list[dict[str, Any]]:
        """Список ИИ-роутеров."""
        data = await self._get("/aig/gateway/v1/gateways")
        return cast(list[dict[str, Any]], data.get("data", data.get("gateways", [])))

    async def get_overview(self, router_id: str) -> RouterOverview:
        """Потребление роутера (вкладка «Обзор»)."""
        data = await self._get(f"/aig/gateway/v1/gateways/{router_id}/overview")
        return RouterOverview(raw=data)

    async def get_metrics(self, router_id: str) -> RouterMetrics:
        """Метрики роутера за 24 часа (вкладка «Метрики»)."""
        data = await self._get(f"/aig/gateway/v1/gateways/{router_id}/metrics")
        return RouterMetrics(raw=data)

    async def list_models(self) -> list[dict[str, Any]]:
        """Каталог моделей."""
        data = await self._get("/aig/gateway/v1/models")
        return cast(list[dict[str, Any]], data.get("data", data.get("models", [])))

    async def list_keys(self) -> list[dict[str, Any]]:
        """Список API-ключей роутера с лимитами."""
        data = await self._get("/aig/gateway/v1/keys")
        return cast(list[dict[str, Any]], data.get("data", data.get("keys", [])))
