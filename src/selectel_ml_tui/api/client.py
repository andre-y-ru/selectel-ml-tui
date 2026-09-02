"""Базовый HTTP-слой для клиентов API Selectel.

httpx.AsyncClient с таймаутами и лимитом соединений; единая обработка ошибок:
- 429 (rate limit) и 5xx — повтор с экспоненциальной паузой;
- сетевые ошибки httpx — повтор;
- остальные 4xx — исключение SelectelApiError с понятным текстом.

Слой отделён от TUI и тестируется моками httpx.MockTransport.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import httpx


class SelectelApiError(RuntimeError):
    """Ошибка обращения к API Selectel.

    Атрибут ``status_code`` заполнен для HTTP-ошибок (None для сетевых).
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class BaseApiClient:
    """Базовый клиент: транспорт, ретраи, понятные ошибки."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            transport=transport,
        )
        self._max_retries = max_retries
        self._sleep = sleep if sleep is not None else asyncio.sleep

    async def aclose(self) -> None:
        """Закрыть транспортные соединения."""
        await self._client.aclose()

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Выполнить запрос с повторами и понятной обработкой ошибок."""
        last_exc: SelectelApiError | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.request(
                    method, url, params=params, json=json, headers=headers
                )
            except httpx.HTTPError as exc:
                if attempt < self._max_retries:
                    await self._sleep(self._backoff_seconds(attempt))
                    continue
                raise SelectelApiError(f"Ошибка сети: {exc}") from exc

            if response.status_code < 400:
                return response

            retriable = response.status_code == 429 or response.status_code >= 500
            if retriable and attempt < self._max_retries:
                await self._sleep(self._backoff_seconds(attempt))
                continue

            raise SelectelApiError(
                f"HTTP {response.status_code}: {response.text[:300]}",
                status_code=response.status_code,
            )
        raise last_exc if last_exc else SelectelApiError("Запрос не выполнен")

    @staticmethod
    def _backoff_seconds(attempt: int) -> float:
        return float(0.5 * (2**attempt))
