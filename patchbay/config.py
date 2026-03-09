from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, HttpUrl, field_validator, model_validator

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = "/config"


class HealthCheckConfig(BaseModel):
    endpoint: HttpUrl
    method: str = "GET"
    expected: int = 200
    timeout: int = 5
    interval: int = 30


class ServiceConfig(BaseModel):
    name: str
    type: Literal["docker", "systemd", "compose"]
    target: str
    description: str = ""
    icon: str = ""
    category: str = "Uncategorized"
    url: str | None = None
    health_check: HealthCheckConfig | None = None

    @field_validator("target")
    @classmethod
    def target_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("target must be a non-empty string")
        return v


class PresetActionConfig(BaseModel):
    service: str
    action: Literal["stop", "start", "restart"]


class PresetConfig(BaseModel):
    name: str
    description: str = ""
    icon: str = ""
    actions: list[PresetActionConfig]

    @field_validator("actions")
    @classmethod
    def actions_not_empty(cls, v: list[PresetActionConfig]) -> list[PresetActionConfig]:
        if not v:
            raise ValueError("preset must have at least one action")
        return v


class GlobalConfig(BaseModel):
    poll_interval: int = 5
    host: str = "127.0.0.1"
    port: int = 4848
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    @field_validator("poll_interval")
    @classmethod
    def poll_interval_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("poll_interval must be positive")
        return v

    @field_validator("port")
    @classmethod
    def port_in_range(cls, v: int) -> int:
        if not 1 <= v <= 65535:
            raise ValueError("port must be between 1 and 65535")
        return v


class AppConfig(BaseModel):
    global_config: GlobalConfig
    services: list[ServiceConfig]
    presets: list[PresetConfig]

    @model_validator(mode="after")
    def validate_cross_references(self) -> AppConfig:
        service_names = {s.name for s in self.services}

        # Check unique service names
        if len(service_names) != len(self.services):
            seen: set[str] = set()
            for s in self.services:
                if s.name in seen:
                    raise ValueError(f"duplicate service name: {s.name!r}")
                seen.add(s.name)

        # Drop presets that reference unknown services
        valid_presets = []
        for preset in self.presets:
            bad_refs = [a.service for a in preset.actions if a.service not in service_names]
            if bad_refs:
                logger.warning(
                    "Skipping preset %r: references unknown service(s) %s",
                    preset.name,
                    ", ".join(repr(s) for s in bad_refs),
                )
                continue
            valid_presets.append(preset)
        self.presets = valid_presets

        return self


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f)
    return data or {}


def _load_and_validate(config_dir: str | Path) -> AppConfig:
    config_dir = Path(config_dir)

    global_data = _load_yaml(config_dir / "config.yml")
    services_data = _load_yaml(config_dir / "services.yml")
    presets_data = _load_yaml(config_dir / "presets.yml")

    if not services_data.get("services"):
        logger.warning("No services defined (services.yml missing or empty)")
    if not presets_data.get("presets"):
        logger.info("No presets defined (presets.yml missing or empty)")

    global_config = GlobalConfig(**global_data)
    services = [ServiceConfig(**s) for s in services_data.get("services", [])]
    presets = [PresetConfig(**p) for p in presets_data.get("presets", [])]

    return AppConfig(global_config=global_config, services=services, presets=presets)


class ConfigHolder:
    def __init__(self) -> None:
        self._config: AppConfig | None = None

    @property
    def config(self) -> AppConfig:
        if self._config is None:
            raise RuntimeError("Config not loaded. Call load() first.")
        return self._config

    def load(self, config_dir: str | Path | None = None) -> AppConfig:
        config_dir = config_dir or os.environ.get("CONFIG_DIR", DEFAULT_CONFIG_DIR)
        self._config = _load_and_validate(config_dir)
        logger.info("Config loaded from %s", config_dir)
        return self._config

    def reload(self, config_dir: str | Path | None = None) -> AppConfig:
        config_dir = config_dir or os.environ.get("CONFIG_DIR", DEFAULT_CONFIG_DIR)
        try:
            new_config = _load_and_validate(config_dir)
        except (ValueError, yaml.YAMLError, OSError) as exc:
            logger.warning("Config reload failed, keeping old config: %s", exc)
            raise
        self._config = new_config
        logger.info("Config reloaded from %s", config_dir)
        return self._config


settings = ConfigHolder()
