from __future__ import annotations

import asyncio
import json
import logging
import subprocess

from patchbay.backends.base import (
    BackendUnavailableError,
    ServiceActionError,
    ServiceBackend,
)
from patchbay.backends.util import format_uptime

logger = logging.getLogger(__name__)

TIMEOUT = 60


class ComposeBackend(ServiceBackend):
    def __init__(self) -> None:
        self.available = False
        try:
            result = subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                self.available = True
                logger.info("Compose backend initialized")
            else:
                logger.warning("docker compose not available: %s", result.stderr.strip())
        except FileNotFoundError:
            logger.warning("Compose backend unavailable (docker not found)")
        except subprocess.TimeoutExpired:
            logger.warning("Compose backend unavailable (version check timed out)")

    def _ensure_available(self) -> None:
        if not self.available:
            raise BackendUnavailableError("Compose backend is not available")

    def _run_compose(self, *args: str, cwd: str) -> subprocess.CompletedProcess[str]:
        self._ensure_available()
        cmd = ["docker", "compose", *args]
        try:
            return subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
            )
        except FileNotFoundError:
            raise ServiceActionError("docker not found")
        except subprocess.TimeoutExpired:
            raise ServiceActionError(f"Timed out running docker compose {' '.join(args)} in {cwd}")

    def _get_container_states(self, target: str) -> list[dict[str, str]]:
        result = self._run_compose("ps", "--format", "json", "-a", cwd=target)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise ServiceActionError(f"docker compose ps failed: {stderr}")
        containers = []
        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                containers.append(
                    {
                        "name": data.get("Name", ""),
                        "state": data.get("State", ""),
                    }
                )
            except json.JSONDecodeError:
                continue
        return containers

    async def get_state(self, target: str) -> str:
        containers = await asyncio.to_thread(self._get_container_states, target)
        if not containers:
            return "stopped"
        states = {c["state"] for c in containers}
        if states == {"running"}:
            return "running"
        if states <= {"exited", "dead", "created"}:
            return "stopped"
        return "partial"

    async def start(self, target: str) -> None:
        result = await asyncio.to_thread(self._run_compose, "up", "-d", cwd=target)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise ServiceActionError(f"Failed to start compose project: {stderr}")

    async def stop(self, target: str) -> None:
        result = await asyncio.to_thread(self._run_compose, "stop", cwd=target)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise ServiceActionError(f"Failed to stop compose project: {stderr}")

    async def restart(self, target: str) -> None:
        result = await asyncio.to_thread(self._run_compose, "restart", cwd=target)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise ServiceActionError(f"Failed to restart compose project: {stderr}")

    async def get_health_info(self, target: str) -> str | None:
        return None

    async def get_uptime(self, target: str) -> str | None:
        containers = await asyncio.to_thread(self._get_container_states, target)
        running_names = [c["name"] for c in containers if c["state"] == "running"]
        if not running_names:
            return None
        try:
            fmt = "{{.State.StartedAt}}"
            result = await asyncio.to_thread(
                subprocess.run,
                ["docker", "inspect", "--format", fmt, *running_names],
                capture_output=True,
                text=True,
                timeout=TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return None
        if result.returncode != 0:
            return None
        earliest: str | None = None
        for line in result.stdout.strip().splitlines():
            ts = line.strip()
            if not ts:
                continue
            if earliest is None or ts < earliest:
                earliest = ts
        if earliest:
            return format_uptime(earliest)
        return None
