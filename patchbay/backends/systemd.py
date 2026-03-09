from __future__ import annotations

import asyncio
import logging
import subprocess
from datetime import UTC, datetime

from patchbay.backends.base import (
    ServiceActionError,
    ServiceBackend,
    ServiceNotFoundError,
)

logger = logging.getLogger(__name__)

TIMEOUT = 30


def _run_systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["systemctl", *args],
            capture_output=True,
             text=True,
            timeout=TIMEOUT,
        )
    except FileNotFoundError:
        raise ServiceActionError("systemctl not found; systemd is not available on this system")

def _format_uptime(timestamp_str: str) -> str | None:
    if not timestamp_str.strip():
        return None
    try:
        start = datetime.strptime(timestamp_str.strip(), "%a %Y-%m-%d %H:%M:%S %Z")
        start = start.replace(tzinfo=UTC)
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


class SystemdBackend(ServiceBackend):
    async def get_state(self, target: str) -> str:
        try:
            result = await asyncio.to_thread(_run_systemctl, "is-active", target)
        except subprocess.TimeoutExpired:
            raise ServiceActionError(f"Timed out checking state of {target}")
        output = result.stdout.strip()
        if result.returncode == 4:
            raise ServiceNotFoundError(f"Unit not found: {target}")
        if output in ("active", "inactive", "failed", "activating", "deactivating"):
            return output
        return "unknown"

    async def _run_action(self, action: str, target: str) -> None:
        try:
            result = await asyncio.to_thread(_run_systemctl, action, target)
        except subprocess.TimeoutExpired:
            raise ServiceActionError(f"Timed out running {action} on {target}")
        if result.returncode == 4:
            raise ServiceNotFoundError(f"Unit not found: {target}")
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise ServiceActionError(f"Failed to {action} {target}: {stderr}")

    async def start(self, target: str) -> None:
        await self._run_action("start", target)

    async def stop(self, target: str) -> None:
        await self._run_action("stop", target)

    async def restart(self, target: str) -> None:
        await self._run_action("restart", target)

    async def get_health_info(self, target: str) -> str | None:
        return None

    async def get_uptime(self, target: str) -> str | None:
        try:
            result = await asyncio.to_thread(
                _run_systemctl, "show", "-p", "ActiveEnterTimestamp", target
            )
        except subprocess.TimeoutExpired:
            return None
        line = result.stdout.strip()
        prefix = "ActiveEnterTimestamp="
        if line.startswith(prefix):
            return _format_uptime(line[len(prefix) :])
        return None
