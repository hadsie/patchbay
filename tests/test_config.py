from __future__ import annotations

from pathlib import Path

import pytest

from patchbay.config import AuthConfig, ConfigHolder, GlobalConfig, _load_and_validate, slugify
from tests.conftest import write_config_files


class TestSlugify:
    def test_lowercase(self):
        assert slugify("Docmill") == "docmill"

    def test_spaces_to_hyphens(self):
        assert slugify("Open WebUI") == "open-webui"

    def test_already_slugified(self):
        assert slugify("test-svc") == "test-svc"

    def test_mixed_case_with_spaces(self):
        assert slugify("Firefly III") == "firefly-iii"


class TestGlobalConfig:
    def test_defaults(self):
        cfg = GlobalConfig()
        assert cfg.poll_interval == 5
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 4848
        assert cfg.log_level == "info"

    def test_invalid_poll_interval(self):
        with pytest.raises(ValueError, match="poll_interval must be positive"):
            GlobalConfig(poll_interval=0)

    def test_invalid_port_low(self):
        with pytest.raises(ValueError, match="port must be between"):
            GlobalConfig(port=0)

    def test_invalid_port_high(self):
        with pytest.raises(ValueError, match="port must be between"):
            GlobalConfig(port=70000)

    def test_invalid_log_level(self):
        with pytest.raises(ValueError):
            GlobalConfig(log_level="verbose")


class TestConfigLoading:
    def test_loads_valid_config(self, config_dir: Path):
        config = _load_and_validate(config_dir)
        assert len(config.services) == 3
        assert len(config.presets) == 1
        assert config.global_config.poll_interval == 5

    def test_service_defaults(self, config_dir: Path):
        config = _load_and_validate(config_dir)
        svc = config.services[0]
        assert svc.name == "test-svc"
        assert svc.type == "docker"
        assert svc.category == "Test"

    def test_compose_type_accepted(self, config_dir: Path):
        config = _load_and_validate(config_dir)
        compose_svcs = [s for s in config.services if s.type == "compose"]
        assert len(compose_svcs) == 1
        assert compose_svcs[0].target == "/tmp/test-compose-project"

    def test_empty_target_rejected(self, tmp_path: Path):
        write_config_files(
            tmp_path,
            services_yml='services:\n  - name: bad\n    type: docker\n    target: ""\n',
        )
        with pytest.raises(ValueError, match="target must be a non-empty string"):
            _load_and_validate(tmp_path)

    def test_invalid_service_type_rejected(self, tmp_path: Path):
        write_config_files(
            tmp_path,
            services_yml="services:\n  - name: bad\n    type: podman\n    target: foo\n",
        )
        with pytest.raises(ValueError):
            _load_and_validate(tmp_path)

    def test_duplicate_service_names_rejected(self, tmp_path: Path):
        write_config_files(
            tmp_path,
            services_yml=(
                "services:\n"
                "  - name: dup\n    type: docker\n    target: a\n"
                "  - name: dup\n    type: docker\n    target: b\n"
            ),
            presets_yml="presets: []\n",
        )
        with pytest.raises(ValueError, match="duplicate service name"):
            _load_and_validate(tmp_path)

    def test_slug_colliding_service_names_rejected(self, tmp_path: Path):
        write_config_files(
            tmp_path,
            services_yml=(
                "services:\n"
                "  - name: My Svc\n    type: docker\n    target: a\n"
                "  - name: my-svc\n    type: docker\n    target: b\n"
            ),
            presets_yml="presets: []\n",
        )
        with pytest.raises(ValueError, match="duplicate service name"):
            _load_and_validate(tmp_path)

    def test_preset_with_unknown_service_is_skipped(self, tmp_path: Path):
        write_config_files(
            tmp_path,
            presets_yml=(
                "presets:\n"
                "  - name: Bad Preset\n"
                "    actions:\n"
                "      - service: nonexistent\n"
                "        action: start\n"
                "  - name: Good Preset\n"
                "    actions:\n"
                "      - service: test-svc\n"
                "        action: restart\n"
            ),
        )
        config = _load_and_validate(tmp_path)
        assert len(config.presets) == 1
        assert config.presets[0].name == "Good Preset"

    def test_empty_preset_actions_rejected(self, tmp_path: Path):
        write_config_files(
            tmp_path,
            presets_yml="presets:\n  - name: Empty\n    actions: []\n",
        )
        with pytest.raises(ValueError, match="at least one action"):
            _load_and_validate(tmp_path)

    def test_invalid_health_check_url(self, tmp_path: Path):
        write_config_files(
            tmp_path,
            services_yml=(
                "services:\n"
                "  - name: svc\n    type: docker\n    target: c\n"
                "    health_check:\n      endpoint: not-a-url\n"
            ),
        )
        with pytest.raises(ValueError):
            _load_and_validate(tmp_path)

    def test_missing_services_yml_loads_empty(self, tmp_path: Path):
        (tmp_path / "config.yml").write_text("poll_interval: 5\nport: 4848\n")
        (tmp_path / "presets.yml").write_text("presets: []\n")
        # no services.yml
        config = _load_and_validate(tmp_path)
        assert config.services == []

    def test_missing_presets_yml_loads_empty(self, tmp_path: Path):
        write_config_files(tmp_path, presets_yml="__SKIP__")
        (tmp_path / "presets.yml").unlink()
        config = _load_and_validate(tmp_path)
        assert config.presets == []

    def test_missing_both_services_and_presets(self, tmp_path: Path):
        (tmp_path / "config.yml").write_text("poll_interval: 5\nport: 4848\n")
        # no services.yml or presets.yml
        config = _load_and_validate(tmp_path)
        assert config.services == []
        assert config.presets == []

    def test_missing_config_yml_uses_defaults(self, tmp_path: Path):
        (tmp_path / "services.yml").write_text("services: []\n")
        (tmp_path / "presets.yml").write_text("presets: []\n")
        # no config.yml
        config = _load_and_validate(tmp_path)
        assert config.global_config.poll_interval == 5
        assert config.global_config.port == 4848


class TestAuthConfig:
    def test_enabled_with_no_roles_errors(self, tmp_path: Path):
        write_config_files(
            tmp_path,
            config_yml=("poll_interval: 5\nport: 4848\nauth:\n  enabled: true\n  roles: {}\n"),
        )
        with pytest.raises(ValueError, match="no roles are defined"):
            _load_and_validate(tmp_path)

    def test_undefined_unauthenticated_role_errors(self, tmp_path: Path):
        write_config_files(
            tmp_path,
            config_yml=(
                "poll_interval: 5\nport: 4848\n"
                "auth:\n"
                "  enabled: true\n"
                "  roles:\n    admin:\n      groups: [admins]\n"
                "  unauthenticated: nonexistent\n"
            ),
        )
        with pytest.raises(ValueError, match="undefined role"):
            _load_and_validate(tmp_path)

    def test_empty_separator_errors(self):
        with pytest.raises(ValueError, match="non-empty"):
            AuthConfig(group_separator="")

    def test_undefined_role_in_permissions_warns(self, tmp_path: Path, caplog):
        write_config_files(
            tmp_path,
            config_yml=(
                "poll_interval: 5\nport: 4848\n"
                "auth:\n"
                "  enabled: true\n"
                "  roles:\n    admin:\n      groups: [admins]\n"
                "  control:\n    allow: [admin, phantom]\n"
                "  unauthenticated: deny\n"
            ),
        )
        _load_and_validate(tmp_path)
        assert "phantom" in caplog.text

    def test_per_resource_auth_parses(self, tmp_path: Path):
        write_config_files(
            tmp_path,
            config_yml=(
                "poll_interval: 5\nport: 4848\n"
                "auth:\n"
                "  enabled: true\n"
                "  roles:\n    admin:\n      groups: [admins]\n"
                "  unauthenticated: deny\n"
            ),
            services_yml=(
                "services:\n"
                "  - name: svc\n    type: docker\n    target: c\n"
                "    auth:\n"
                "      view:\n        allow: [admin]\n"
                "      control:\n        allow: [admin]\n"
            ),
            presets_yml="presets: []\n",
        )
        config = _load_and_validate(tmp_path)
        assert config.services[0].auth is not None
        assert config.services[0].auth.view.allow == ["admin"]

    def test_auth_disabled_by_default(self, config_dir: Path):
        config = _load_and_validate(config_dir)
        assert config.global_config.auth.enabled is False

    def test_api_keys_default_to_empty(self, config_dir: Path):
        config = _load_and_validate(config_dir)
        assert config.global_config.auth.api_keys == []

    def test_api_key_undefined_role_warns(self, tmp_path: Path, caplog):
        write_config_files(
            tmp_path,
            config_yml=(
                "poll_interval: 5\nport: 4848\n"
                "auth:\n"
                "  enabled: true\n"
                "  roles:\n    admin:\n      groups: [admins]\n"
                "  unauthenticated: deny\n"
            ),
        )
        (tmp_path / "api_keys.yml").write_text(
            'api_keys:\n  - label: test\n    key_hash: "$2b$12$fake"\n    roles: [admin, phantom]\n'
        )
        _load_and_validate(tmp_path)
        assert "phantom" in caplog.text

    def test_api_key_duplicate_labels_warns(self, tmp_path: Path, caplog):
        write_config_files(
            tmp_path,
            config_yml=(
                "poll_interval: 5\nport: 4848\n"
                "auth:\n"
                "  enabled: true\n"
                "  roles:\n    admin:\n      groups: [admins]\n"
                "  unauthenticated: deny\n"
            ),
        )
        (tmp_path / "api_keys.yml").write_text(
            "api_keys:\n"
            "  - label: dupe\n"
            '    key_hash: "$2b$12$fake1"\n'
            "    roles: [admin]\n"
            "  - label: dupe\n"
            '    key_hash: "$2b$12$fake2"\n'
            "    roles: [admin]\n"
        )
        _load_and_validate(tmp_path)
        assert "Duplicate API key labels" in caplog.text


class TestConfigReload:
    def test_reload_succeeds(self, config_dir: Path):
        holder = ConfigHolder()
        holder.load(config_dir)
        config = holder.reload(config_dir)
        assert len(config.services) == 3

    def test_reload_keeps_old_on_failure(self, config_dir: Path):
        holder = ConfigHolder()
        holder.load(config_dir)

        # Break the config
        (config_dir / "services.yml").write_text(
            "services:\n  - name: dup\n    type: docker\n    target: a\n"
            "  - name: dup\n    type: docker\n    target: b\n"
        )

        with pytest.raises(ValueError):
            holder.reload(config_dir)

        # Old config still intact
        assert len(holder.config.services) == 3

    def test_load_raises_when_not_loaded(self):
        holder = ConfigHolder()
        with pytest.raises(RuntimeError, match="not loaded"):
            _ = holder.config
