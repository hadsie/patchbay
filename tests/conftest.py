from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from patchbay.config import AppConfig, ConfigHolder
from patchbay.health import HealthChecker


class MockBackend:
    """Test double for ServiceBackend that doesn't require ABC compliance."""

    def __init__(self, states: dict[str, str] | None = None):
        self._states = states or {}
        self.start = AsyncMock()
        self.stop = AsyncMock()
        self.restart = AsyncMock()

    async def get_state(self, target: str) -> str:
        return self._states.get(target, "unknown")

    async def get_health_info(self, target: str) -> str | None:
        return None

    async def get_uptime(self, target: str) -> str | None:
        if self._states.get(target) in ("running", "active"):
            return "1d 2h"
        return None


def write_config_files(
    config_dir: Path,
    config_yml: str = "",
    services_yml: str = "",
    presets_yml: str = "",
) -> None:
    (config_dir / "config.yml").write_text(config_yml or "poll_interval: 5\nport: 4848\n")
    (config_dir / "services.yml").write_text(
        services_yml
        or """
services:
  - name: test-svc
    type: docker
    target: test-container
    description: "A test service"
    category: Test
  - name: test-systemd
    type: systemd
    target: test.service
    description: "A test systemd service"
    category: Test
"""
    )
    (config_dir / "presets.yml").write_text(
        presets_yml
        or """
presets:
  - name: Test Preset
    description: "A test preset"
    actions:
      - service: test-svc
        action: restart
"""
    )


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    write_config_files(tmp_path)
    return tmp_path


@pytest.fixture
def app_config(config_dir: Path) -> AppConfig:
    holder = ConfigHolder()
    return holder.load(config_dir)


@pytest.fixture
def mock_docker_backend() -> MockBackend:
    return MockBackend(states={"test-container": "running"})


@pytest.fixture
def mock_systemd_backend() -> MockBackend:
    return MockBackend(states={"test.service": "active"})


@pytest.fixture
def test_client(config_dir: Path, mock_docker_backend, mock_systemd_backend) -> TestClient:
    import os

    os.environ["CONFIG_DIR"] = str(config_dir)

    from patchbay.main import create_app

    app = create_app()

    # Override backends and health checker after lifespan starts
    with TestClient(app) as client:
        app.state.backends = {
            "docker": mock_docker_backend,
            "systemd": mock_systemd_backend,
        }
        app.state.health_checker = HealthChecker()
        yield client
