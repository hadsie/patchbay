from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from patchbay.backends.base import (
    BackendUnavailableError,
    ServiceActionError,
    ServiceNotFoundError,
)
from patchbay.backends.docker import DockerBackend, _format_uptime
from patchbay.backends.systemd import SystemdBackend


class TestDockerFormatUptime:
    def test_formats_days_and_hours(self):
        ts = (datetime.now(UTC) - timedelta(days=2, hours=4)).isoformat()
        result = _format_uptime(ts)
        assert result is not None
        assert "2d" in result

    def test_formats_hours_and_minutes(self):
        ts = (datetime.now(UTC) - timedelta(hours=3, minutes=15)).isoformat()
        result = _format_uptime(ts)
        assert result is not None
        assert "3h" in result

    def test_formats_minutes_only(self):
        ts = (datetime.now(UTC) - timedelta(minutes=42)).isoformat()
        result = _format_uptime(ts)
        assert result is not None
        assert "42m" in result

    def test_returns_none_for_invalid(self):
        assert _format_uptime("not-a-date") is None


def _make_docker_backend(client: MagicMock) -> DockerBackend:
    """Create a DockerBackend with a mocked client, bypassing __init__."""
    backend = object.__new__(DockerBackend)
    backend.available = True
    backend._client = client
    return backend


class TestDockerBackend:
    def test_get_state_returns_container_status(self):
        container = MagicMock()
        container.status = "running"
        client = MagicMock()
        client.containers.get.return_value = container
        backend = _make_docker_backend(client)

        state = asyncio.get_event_loop().run_until_complete(backend.get_state("test"))
        assert state == "running"

    def test_not_found_raises(self):
        import docker.errors

        client = MagicMock()
        client.containers.get.side_effect = docker.errors.NotFound("gone")
        backend = _make_docker_backend(client)

        with pytest.raises(ServiceNotFoundError, match="Container not found"):
            asyncio.get_event_loop().run_until_complete(backend.get_state("missing"))

    def test_api_error_raises(self):
        import docker.errors

        client = MagicMock()
        client.containers.get.side_effect = docker.errors.APIError("api fail")
        backend = _make_docker_backend(client)

        with pytest.raises(ServiceActionError, match="Docker API error"):
            asyncio.get_event_loop().run_until_complete(backend.get_state("bad"))

    def test_start_calls_container_start(self):
        container = MagicMock()
        client = MagicMock()
        client.containers.get.return_value = container
        backend = _make_docker_backend(client)

        asyncio.get_event_loop().run_until_complete(backend.start("test"))
        container.start.assert_called_once()

    def test_stop_calls_container_stop(self):
        container = MagicMock()
        client = MagicMock()
        client.containers.get.return_value = container
        backend = _make_docker_backend(client)

        asyncio.get_event_loop().run_until_complete(backend.stop("test"))
        container.stop.assert_called_once()

    def test_restart_calls_container_restart(self):
        container = MagicMock()
        client = MagicMock()
        client.containers.get.return_value = container
        backend = _make_docker_backend(client)

        asyncio.get_event_loop().run_until_complete(backend.restart("test"))
        container.restart.assert_called_once()

    def test_get_health_info(self):
        container = MagicMock()
        container.attrs = {"State": {"Health": {"Status": "healthy"}}}
        client = MagicMock()
        client.containers.get.return_value = container
        backend = _make_docker_backend(client)

        health = asyncio.get_event_loop().run_until_complete(backend.get_health_info("test"))
        assert health == "healthy"

    def test_get_health_info_no_healthcheck(self):
        container = MagicMock()
        container.attrs = {"State": {}}
        client = MagicMock()
        client.containers.get.return_value = container
        backend = _make_docker_backend(client)

        health = asyncio.get_event_loop().run_until_complete(backend.get_health_info("test"))
        assert health is None

    def test_unavailable_raises(self):
        backend = object.__new__(DockerBackend)
        backend.available = False
        backend._client = None

        with pytest.raises(BackendUnavailableError):
            asyncio.get_event_loop().run_until_complete(backend.get_state("test"))


class TestSystemdBackend:
    @patch("patchbay.backends.systemd._run_systemctl")
    def test_get_state_active(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="active\n", stderr=""
        )
        backend = SystemdBackend()
        state = asyncio.get_event_loop().run_until_complete(backend.get_state("sshd.service"))
        assert state == "active"

    @patch("patchbay.backends.systemd._run_systemctl")
    def test_get_state_inactive(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=3, stdout="inactive\n", stderr=""
        )
        backend = SystemdBackend()
        state = asyncio.get_event_loop().run_until_complete(backend.get_state("stopped.service"))
        assert state == "inactive"

    @patch("patchbay.backends.systemd._run_systemctl")
    def test_unit_not_found(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=4, stdout="", stderr="Unit not found."
        )
        backend = SystemdBackend()
        with pytest.raises(ServiceNotFoundError, match="Unit not found"):
            asyncio.get_event_loop().run_until_complete(backend.get_state("nope.service"))

    @patch("patchbay.backends.systemd._run_systemctl")
    def test_start_calls_systemctl(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        backend = SystemdBackend()
        asyncio.get_event_loop().run_until_complete(backend.start("sshd.service"))
        mock_run.assert_called_with("start", "sshd.service")

    @patch("patchbay.backends.systemd._run_systemctl")
    def test_action_failure(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Permission denied"
        )
        backend = SystemdBackend()
        with pytest.raises(ServiceActionError, match="Permission denied"):
            asyncio.get_event_loop().run_until_complete(backend.stop("sshd.service"))

    @patch("patchbay.backends.systemd._run_systemctl")
    def test_timeout_raises(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="systemctl", timeout=30)
        backend = SystemdBackend()
        with pytest.raises(ServiceActionError, match="Timed out"):
            asyncio.get_event_loop().run_until_complete(backend.restart("sshd.service"))
