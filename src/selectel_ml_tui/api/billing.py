"""Клиент Billing Statistics API Selectel (провайдер aig).

Аутентификация: статический токен в заголовке X-Token.
Данные: стоимость потребления ИИ-роутера по дням/часам.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import httpx

from selectel_ml_tui.api.client import BaseApiClient, SelectelApiError
from selectel_ml_tui.models import ConsumptionItem

BillingApiError = SelectelApiError


def normalize_dt(value: str) -> str:
    """Привести дату к формату, принимаемому Billing API.

    Billing API ожидает полный ISO-таймстамп (например
    ``2026-08-01T00:00:00.000``); короткая дата дополняется.
    """
    if "T" in value:
        return value
    return f"{value}T00:00:00.000"


class BillingClient(BaseApiClient):
    """Клиент /v1/cloud_billing/statistic/* для провайдера aig."""

    PROVIDER = "aig"

    def __init__(
        self,
        api_base_url: str,
        static_token: str,
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
        self._token = static_token

    def _headers(self) -> dict[str, str]:
        return {"X-Token": self._token, "Content-Type": "application/json"}

    async def _get(
        self, path: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        response = await self.request(
            "GET", url, params=params, headers=self._headers()
        )
        data = response.json()
        if not isinstance(data, dict) or data.get("status") != "success":
            raise BillingApiError(f"Billing API: {data}")
        return data

    async def get_consumption(
        self,
        start: str,
        end: str,
        locale: str = "ru",
        group_type: str = "metric",
        period_group_type: str = "day",
    ) -> list[ConsumptionItem]:
        """Получить потребление за период.

        group_type: project | object | metric | project_metric | region_metric
        period_group_type: hour | day | week | month | year | all
        """
        data = await self._get(
            "/v1/cloud_billing/statistic/consumption",
            params={
                "provider_keys": self.PROVIDER,
                "start": normalize_dt(start),
                "end": normalize_dt(end),
                "locale": locale,
                "group_type": group_type,
                "period_group_type": period_group_type,
            },
        )
        return [ConsumptionItem.model_validate(item) for item in data.get("data", [])]

    async def get_consumption_history(
        self,
        start: str,
        end: str,
        group: str = "day",
    ) -> list[ConsumptionItem]:
        """История потребления по дням/часам за период.

        group: hour | day | week | month | year | all
        """
        return await self.get_consumption(
            start, end, period_group_type=group, group_type="metric"
        )

    async def get_summary(
        self,
        start: str,
        end: str,
        group_type: str = "metric",
        period_group_type: str = "month",
    ) -> Decimal:
        """Суммарная стоимость за период в копейках (value)."""
        data = await self._get(
            "/v1/cloud_billing/statistic/summary_stats",
            params={
                "provider_keys": self.PROVIDER,
                "start": normalize_dt(start),
                "end": normalize_dt(end),
                "group_type": group_type,
                "period_group_type": period_group_type,
                "items_count_period_group_type": "all",
            },
        )
        rows = data.get("data", [])
        total: Decimal = Decimal("0")
        for row in cast(list[dict[str, Any]], rows):
            total += Decimal(str(row.get("value", 0)))
        return total
