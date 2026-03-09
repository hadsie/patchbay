from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

from patchbay.config import AppConfig, ServiceConfig

logger = logging.getLogger(__name__)

RUNNING_STATES = {"running", "active", "activating", "restarting"}


@dataclass
class HealthResult:
    status: str  # healthy, unhealthy, pending
    last_check: float = 0.0
    response_ms: float | None = None
    error: str | None = None


class HealthChecker:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._config: AppConfig | None = None
        self._results: dict[str, HealthResult] = {}
        self._last_checked: dict[str, float] = {}
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def results(self) -> dict[str, HealthResult]:
        return self._results

    async def start(self, config: AppConfig) -> None:
        self._client = httpx.AsyncClient()
        self._config = config
        self._running = True
        for svc in config.services:
            if svc.health_check:
                self._results[svc.name] = HealthResult(status="pending")
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()

    async def update_config(self, config: AppConfig) -> None:
        self._config = config
        self._last_checked.clear()
        for svc in config.services:
            if svc.health_check and svc.name not in self._results:
                self._results[svc.name] = HealthResult(status="pending")
        current_names = {s.name for s in config.services if s.health_check}
        for name in list(self._results):
            if name not in current_names:
                del self._results[name]

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(1)
                if not self._config:
                    continue
                now = time.monotonic()
                for svc in self._config.services:
                    if not svc.health_check:
                        continue
                    interval = svc.health_check.interval
                    last = self._last_checked.get(svc.name, 0)
                    if now - last >= interval:
                        self._last_checked[svc.name] = now
                        asyncio.create_task(self._check_service(svc))
            except asyncio.CancelledError:
                break

    async def _check_service(self, svc: ServiceConfig) -> None:
        hc = svc.health_check
        if not hc or not self._client:
            return
        start = time.monotonic()
        try:
            response = await self._client.request(
                method=hc.method,
                url=str(hc.endpoint),
                timeout=hc.timeout,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            if response.status_code == hc.expected:
                self._results[svc.name] = HealthResult(
                    status="healthy", last_check=time.time(), response_ms=elapsed_ms
                )
            else:
                self._results[svc.name] = HealthResult(
                    status="unhealthy",
                    last_check=time.time(),
                    response_ms=elapsed_ms,
                    error=f"Expected {hc.expected}, got {response.status_code}",
                )
        except httpx.TimeoutException:
            self._results[svc.name] = HealthResult(
                status="unhealthy",
                last_check=time.time(),
                error="Health check timed out",
            )
        except httpx.HTTPError as exc:
            self._results[svc.name] = HealthResult(
                status="unhealthy",
                last_check=time.time(),
                error=str(exc),
            )


def resolve_health(
    service: ServiceConfig,
    state: str,
    health_checker_result: HealthResult | None,
    docker_health: str | None,
) -> str:
    stopped_states = {"stopped", "exited", "inactive", "dead"}
    if state in stopped_states:
        return "n/a"
    if service.health_check and health_checker_result:
        return health_checker_result.status
    if docker_health:
        mapping = {"healthy": "healthy", "unhealthy": "unhealthy", "starting": "pending"}
        return mapping.get(docker_health, "unhealthy")
    if state in RUNNING_STATES:
        return "healthy"
    if state == "partial":
        return "unhealthy"
    return "n/a"
