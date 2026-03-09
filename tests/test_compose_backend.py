from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from patchbay.backends.base import BackendUnavailableError, ServiceActionError
from patchbay.backends.compose import ComposeBackend


def _make_backend() -> ComposeBackend:
    """Create a ComposeBackend bypassing __init__."""
    backend = object.__new__(ComposeBackend)
    backend.available = True
    return backend


def _ps_output(containers: list[dict]) -> str:
    """Build NDJSON output matching docker compose ps --format json."""
    return "\n".join(json.dumps(c) for c in containers)


class TestComposeGetState:
    @patch("patchbay.backends.compose.subprocess.run")
    def test_all_running(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_ps_output(
                [
                    {"Name": "app-web-1", "State": "running"},
                    {"Name": "app-db-1", "State": "running"},
                ]
            ),
            stderr="",
        )
        backend = _make_backend()
        state = asyncio.get_event_loop().run_until_complete(backend.get_state("/opt/app"))
        assert state == "running"

    @patch("patchbay.backends.compose.subprocess.run")
    def test_all_stopped(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_ps_output(
                [
                    {"Name": "app-web-1", "State": "exited"},
                    {"Name": "app-db-1", "State": "exited"},
                ]
            ),
            stderr="",
        )
        backend = _make_backend()
        state = asyncio.get_event_loop().run_until_complete(backend.get_state("/opt/app"))
        assert state == "stopped"

    @patch("patchbay.backends.compose.subprocess.run")
    def test_mixed_returns_partial(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_ps_output(
                [
                    {"Name": "app-web-1", "State": "running"},
                    {"Name": "app-db-1", "State": "exited"},
                ]
            ),
            stderr="",
        )
        backend = _make_backend()
        state = asyncio.get_event_loop().run_until_complete(backend.get_state("/opt/app"))
        assert state == "partial"

    @patch("patchbay.backends.compose.subprocess.run")
    def test_no_containers_returns_stopped(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        backend = _make_backend()
        state = asyncio.get_event_loop().run_until_complete(backend.get_state("/opt/app"))
        assert state == "stopped"

    @patch("patchbay.backends.compose.subprocess.run")
    def test_created_containers_count_as_stopped(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_ps_output(
                [
                    {"Name": "app-web-1", "State": "created"},
                    {"Name": "app-db-1", "State": "exited"},
                ]
            ),
            stderr="",
        )
        backend = _make_backend()
        state = asyncio.get_event_loop().run_until_complete(backend.get_state("/opt/app"))
        assert state == "stopped"


class TestComposeActions:
    @patch("patchbay.backends.compose.subprocess.run")
    def test_start_runs_up_d(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        backend = _make_backend()
        asyncio.get_event_loop().run_until_complete(backend.start("/opt/app"))
        mock_run.assert_called_once_with(
            ["docker", "compose", "up", "-d"],
            cwd="/opt/app",
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("patchbay.backends.compose.subprocess.run")
    def test_stop_runs_compose_stop(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        backend = _make_backend()
        asyncio.get_event_loop().run_until_complete(backend.stop("/opt/app"))
        mock_run.assert_called_once_with(
            ["docker", "compose", "stop"],
            cwd="/opt/app",
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("patchbay.backends.compose.subprocess.run")
    def test_restart_runs_compose_restart(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        backend = _make_backend()
        asyncio.get_event_loop().run_until_complete(backend.restart("/opt/app"))
        mock_run.assert_called_once_with(
            ["docker", "compose", "restart"],
            cwd="/opt/app",
            capture_output=True,
            text=True,
            timeout=60,
        )

    @patch("patchbay.backends.compose.subprocess.run")
    def test_start_failure_raises(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="no such directory"
        )
        backend = _make_backend()
        with pytest.raises(ServiceActionError, match="Failed to start"):
            asyncio.get_event_loop().run_until_complete(backend.start("/opt/app"))


class TestComposeHealthInfo:
    def test_returns_none(self):
        backend = _make_backend()
        result = asyncio.get_event_loop().run_until_complete(backend.get_health_info("/opt/app"))
        assert result is None


class TestComposeUptime:
    @patch("patchbay.backends.compose.subprocess.run")
    def test_returns_earliest_uptime(self, mock_run):
        early = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
        late = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        ps_output = _ps_output(
            [
                {"Name": "app-web-1", "State": "running"},
                {"Name": "app-db-1", "State": "running"},
            ]
        )
        mock_run.side_effect = [
            # First call: docker compose ps
            subprocess.CompletedProcess(args=[], returncode=0, stdout=ps_output, stderr=""),
            # Second call: docker inspect
            subprocess.CompletedProcess(
                args=[], returncode=0, stdout=f"{late}\n{early}\n", stderr=""
            ),
        ]
        backend = _make_backend()
        uptime = asyncio.get_event_loop().run_until_complete(backend.get_uptime("/opt/app"))
        assert uptime is not None
        assert "5h" in uptime

    @patch("patchbay.backends.compose.subprocess.run")
    def test_no_running_containers_returns_none(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_ps_output([{"Name": "app-web-1", "State": "exited"}]),
            stderr="",
        )
        backend = _make_backend()
        uptime = asyncio.get_event_loop().run_until_complete(backend.get_uptime("/opt/app"))
        assert uptime is None


class TestComposeAvailability:
    def test_unavailable_when_docker_compose_not_found(self):
        with patch(
            "patchbay.backends.compose.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            backend = ComposeBackend()
            assert not backend.available

    def test_unavailable_raises_on_operations(self):
        backend = object.__new__(ComposeBackend)
        backend.available = False
        with pytest.raises(BackendUnavailableError):
            asyncio.get_event_loop().run_until_complete(backend.get_state("/opt/app"))
