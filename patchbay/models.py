from __future__ import annotations

from pydantic import BaseModel


class HealthDetail(BaseModel):
    error: str | None = None
    response_ms: float | None = None
    last_check: float | None = None


class ServiceStatus(BaseModel):
    name: str
    type: str
    target: str
    description: str
    category: str
    icon: str
    url: str | None
    state: str
    health: str
    health_detail: HealthDetail | None = None
    uptime: str | None
    can_control: bool = True


class ServiceActionResponse(BaseModel):
    name: str
    action: str
    result: str
    previous_state: str | None = None
    current_state: str | None = None
    duration_seconds: float | None = None
    error: str | None = None


class PresetActionInfo(BaseModel):
    service: str
    action: str


class PresetInfo(BaseModel):
    name: str
    description: str
    icon: str
    actions: list[PresetActionInfo]
    can_control: bool = True


class PresetActionResult(BaseModel):
    service: str
    action: str
    result: str
    duration_seconds: float | None = None
    error: str | None = None


class PresetActivationResponse(BaseModel):
    preset: str
    status: str
    actions: list[PresetActionResult]
    failed_at: int | None = None
    total_duration_seconds: float


class HealthResponse(BaseModel):
    status: str
    version: str


class ConfigResponse(BaseModel):
    poll_interval: int
    host: str
    port: int
    log_level: str
    services_count: int
    presets_count: int


class ErrorResponse(BaseModel):
    error: str
    code: str
