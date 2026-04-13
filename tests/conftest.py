from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import bcrypt
import pytest
from fastapi.testclient import TestClient

from patchbay.config import AppConfig, ConfigHolder
from patchbay.health import HealthChecker

TEST_API_KEY_ADMIN = "pb_test_admin_key_for_unit_tests"
TEST_API_KEY_ADMIN_HASH = bcrypt.hashpw(TEST_API_KEY_ADMIN.encode(), bcrypt.gensalt()).decode()
TEST_API_KEY_VIEWER = "pb_test_viewer_key_for_unit_tests"
TEST_API_KEY_VIEWER_HASH = bcrypt.hashpw(TEST_API_KEY_VIEWER.encode(), bcrypt.gensalt()).decode()


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
        if self._states.get(target) == "running":
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
  - name: test-compose
    type: compose
    target: /tmp/test-compose-project
    description: "A test compose service"
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
    return MockBackend(states={"test.service": "running"})


@pytest.fixture
def mock_compose_backend() -> MockBackend:
    return MockBackend(states={"/tmp/test-compose-project": "running"})


def _make_test_client(config_dir, mock_docker_backend, mock_systemd_backend, mock_compose_backend):
    import os

    os.environ["CONFIG_DIR"] = str(config_dir)

    from patchbay.main import create_app

    app = create_app()

    with TestClient(app) as client:
        app.state.backends = {
            "docker": mock_docker_backend,
            "systemd": mock_systemd_backend,
            "compose": mock_compose_backend,
        }
        app.state.health_checker = HealthChecker()
        yield client


@pytest.fixture
def test_client(
    config_dir: Path, mock_docker_backend, mock_systemd_backend, mock_compose_backend
) -> TestClient:
    yield from _make_test_client(
        config_dir, mock_docker_backend, mock_systemd_backend, mock_compose_backend
    )


AUTH_CONFIG_YML = """\
poll_interval: 5
port: 4848
auth:
  enabled: true
  user_header: "X-Forwarded-User"
  groups_header: "X-Forwarded-Groups"
  group_separator: "|"
  roles:
    admin:
      groups: ["patchbay-admins"]
    viewer:
      groups: ["patchbay-users"]
  view:
    allow: ["*"]
  control:
    allow: ["admin"]
  unauthenticated: deny
"""

AUTH_SERVICES_YML = """\
services:
  - name: public-svc
    type: docker
    target: public-container
    description: "Visible to all"
    category: Public
  - name: admin-only-svc
    type: docker
    target: admin-container
    description: "Hidden from viewers"
    category: Admin
    auth:
      view:
        allow: ["admin"]
  - name: viewer-control-svc
    type: docker
    target: viewer-control-container
    description: "Viewer can control"
    category: Public
    auth:
      control:
        allow: ["admin", "viewer"]
"""

AUTH_PRESETS_YML = """\
presets:
  - name: Public Preset
    description: "Visible to all"
    actions:
      - service: public-svc
        action: restart
  - name: Admin Preset
    description: "Only admin can see"
    auth:
      view:
        allow: ["admin"]
    actions:
      - service: public-svc
        action: restart
"""


def write_auth_config_files(config_dir: Path) -> None:
    (config_dir / "config.yml").write_text(AUTH_CONFIG_YML)
    (config_dir / "services.yml").write_text(AUTH_SERVICES_YML)
    (config_dir / "presets.yml").write_text(AUTH_PRESETS_YML)


@pytest.fixture
def auth_config_dir(tmp_path: Path) -> Path:
    write_auth_config_files(tmp_path)
    return tmp_path


@pytest.fixture
def auth_test_client(
    auth_config_dir: Path, mock_docker_backend, mock_systemd_backend, mock_compose_backend
) -> TestClient:
    mock_docker = MockBackend(
        states={
            "public-container": "running",
            "admin-container": "running",
            "viewer-control-container": "running",
        }
    )
    yield from _make_test_client(
        auth_config_dir, mock_docker, mock_systemd_backend, mock_compose_backend
    )


def _api_keys_yml() -> str:
    return (
        "api_keys:\n"
        '  - label: "test-admin"\n'
        f'    key_hash: "{TEST_API_KEY_ADMIN_HASH}"\n'
        '    roles: ["admin"]\n'
        '  - label: "test-viewer"\n'
        f'    key_hash: "{TEST_API_KEY_VIEWER_HASH}"\n'
        '    roles: ["viewer"]\n'
    )


@pytest.fixture
def api_key_auth_config_dir(tmp_path: Path) -> Path:
    (tmp_path / "config.yml").write_text(AUTH_CONFIG_YML)
    (tmp_path / "services.yml").write_text(AUTH_SERVICES_YML)
    (tmp_path / "presets.yml").write_text(AUTH_PRESETS_YML)
    (tmp_path / "api_keys.yml").write_text(_api_keys_yml())
    return tmp_path


@pytest.fixture
def api_key_auth_test_client(
    api_key_auth_config_dir: Path, mock_docker_backend, mock_systemd_backend, mock_compose_backend
) -> TestClient:
    mock_docker = MockBackend(
        states={
            "public-container": "running",
            "admin-container": "running",
            "viewer-control-container": "running",
        }
    )
    yield from _make_test_client(
        api_key_auth_config_dir, mock_docker, mock_systemd_backend, mock_compose_backend
    )
