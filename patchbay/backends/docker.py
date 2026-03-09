from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from patchbay.backends.base import (
    BackendUnavailableError,
    ServiceActionError,
    ServiceBackend,
    ServiceNotFoundError,
)

logger = logging.getLogger(__name__)


def _format_uptime(started_at: str) -> str | None:
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        delta = datetime.now(UTC) - start
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return None
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"
    except (ValueError, TypeError):
        return None


class DockerBackend(ServiceBackend):
    def __init__(self) -> None:
        self.available = False
        self._client = None
        try:
            import docker

            self._client = docker.DockerClient.from_env()
            self._client.ping()
            self.available = True
            logger.info("Docker backend initialized")
        except Exception:
            logger.warning("Docker backend unavailable (no socket or daemon not running)")

    def _ensure_available(self) -> None:
        if not self.available or self._client is None:
            raise BackendUnavailableError("Docker backend is not available")

    def _get_container(self, target: str):
        import docker.errors

        self._ensure_available()
        try:
            return self._client.containers.get(target)
        except docker.errors.NotFound:
            raise ServiceNotFoundError(f"Container not found: {target}")
        except docker.errors.APIError as exc:
            raise ServiceActionError(f"Docker API error: {exc}")

    async def get_state(self, target: str) -> str:
        container = await asyncio.to_thread(self._get_container, target)
        return container.status

    async def start(self, target: str) -> None:
        import docker.errors

        container = await asyncio.to_thread(self._get_container, target)
        try:
            await asyncio.to_thread(container.start)
        except docker.errors.APIError as exc:
            raise ServiceActionError(f"Failed to start {target}: {exc}")

    async def stop(self, target: str) -> None:
        import docker.errors

        container = await asyncio.to_thread(self._get_container, target)
        try:
            await asyncio.to_thread(container.stop)
        except docker.errors.APIError as exc:
            raise ServiceActionError(f"Failed to stop {target}: {exc}")

    async def restart(self, target: str) -> None:
        import docker.errors

        container = await asyncio.to_thread(self._get_container, target)
        try:
            await asyncio.to_thread(container.restart)
        except docker.errors.APIError as exc:
            raise ServiceActionError(f"Failed to restart {target}: {exc}")

    async def get_health_info(self, target: str) -> str | None:
        container = await asyncio.to_thread(self._get_container, target)
        try:
            health = container.attrs.get("State", {}).get("Health", {})
            return health.get("Status")
        except (KeyError, TypeError):
            return None

    async def get_uptime(self, target: str) -> str | None:
        container = await asyncio.to_thread(self._get_container, target)
        if container.status != "running":
            return None
        started_at = container.attrs.get("State", {}).get("StartedAt", "")
        return _format_uptime(started_at)
