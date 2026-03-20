from __future__ import annotations

import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from patchbay.auth import can_control, can_view, resolve_user
from patchbay.backends.base import BackendError, ServiceBackend
from patchbay.config import AppConfig, ServiceConfig
from patchbay.health import HealthChecker, resolve_health
from patchbay.models import ErrorResponse, HealthDetail, ServiceActionResponse, ServiceStatus

router = APIRouter(prefix="/api/services", tags=["services"])


def _get_deps(request: Request) -> tuple[AppConfig, dict[str, ServiceBackend], HealthChecker]:
    return (
        request.app.state.config,
        request.app.state.backends,
        request.app.state.health_checker,
    )


def _find_service(config: AppConfig, name: str) -> ServiceConfig | None:
    for svc in config.services:
        if svc.name == name:
            return svc
    return None


async def _build_service_status(
    svc: ServiceConfig,
    backends: dict[str, ServiceBackend],
    health_checker: HealthChecker,
) -> ServiceStatus:
    backend = backends[svc.type]
    try:
        state = await backend.get_state(svc.target)
    except BackendError:
        state = "unknown"

    try:
        docker_health = await backend.get_health_info(svc.target)
    except BackendError:
        docker_health = None

    try:
        uptime = await backend.get_uptime(svc.target)
    except BackendError:
        uptime = None

    checker_result = health_checker.results.get(svc.name)
    health = resolve_health(svc, state, checker_result, docker_health)

    health_detail = None
    if checker_result and checker_result.status != "pending":
        ms = checker_result.response_ms
        health_detail = HealthDetail(
            error=checker_result.error,
            response_ms=round(ms, 1) if ms is not None else None,
            last_check=checker_result.last_check or None,
        )

    return ServiceStatus(
        name=svc.name,
        type=svc.type,
        target=svc.target,
        description=svc.description,
        category=svc.category,
        icon=svc.icon,
        url=svc.url,
        state=state,
        health=health,
        health_detail=health_detail,
        uptime=uptime,
    )


@router.get("")
async def list_services(request: Request) -> list[ServiceStatus]:
    config, backends, health_checker = _get_deps(request)
    auth_config = config.global_config.auth
    auth_ctx = resolve_user(request, auth_config)
    statuses = []
    for svc in config.services:
        if not can_view(auth_ctx, svc, auth_config):
            continue
        status = await _build_service_status(svc, backends, health_checker)
        status.can_control = can_control(auth_ctx, svc, auth_config)
        statuses.append(status)
    return statuses


@router.get("/{name}")
async def get_service(name: str, request: Request) -> ServiceStatus | ErrorResponse:
    config, backends, health_checker = _get_deps(request)
    auth_config = config.global_config.auth
    auth_ctx = resolve_user(request, auth_config)
    svc = _find_service(config, name)
    if not svc or not can_view(auth_ctx, svc, auth_config):
        return JSONResponse(
            status_code=404,
            content={"error": f"Service not found: {name}", "code": "SERVICE_NOT_FOUND"},
        )
    status = await _build_service_status(svc, backends, health_checker)
    status.can_control = can_control(auth_ctx, svc, auth_config)
    return status


async def _perform_action(name: str, action: str, request: Request) -> ServiceActionResponse:
    config, backends, _ = _get_deps(request)
    auth_config = config.global_config.auth
    auth_ctx = resolve_user(request, auth_config)
    svc = _find_service(config, name)
    if not svc or not can_view(auth_ctx, svc, auth_config):
        return JSONResponse(
            status_code=404,
            content={"error": f"Service not found: {name}", "code": "SERVICE_NOT_FOUND"},
        )
    if not can_control(auth_ctx, svc, auth_config):
        return JSONResponse(
            status_code=403,
            content={"error": "Permission denied", "code": "FORBIDDEN"},
        )

    backend = backends[svc.type]

    try:
        previous_state = await backend.get_state(svc.target)
    except BackendError:
        previous_state = "unknown"

    start = time.monotonic()
    try:
        method = getattr(backend, action)
        await method(svc.target)
        duration = time.monotonic() - start

        try:
            current_state = await backend.get_state(svc.target)
        except BackendError:
            current_state = "unknown"

        return ServiceActionResponse(
            name=name,
            action=action,
            result="success",
            previous_state=previous_state,
            current_state=current_state,
            duration_seconds=round(duration, 2),
        )
    except BackendError as exc:
        duration = time.monotonic() - start
        return ServiceActionResponse(
            name=name,
            action=action,
            result="error",
            previous_state=previous_state,
            current_state="unknown",
            duration_seconds=round(duration, 2),
            error=str(exc),
        )


@router.post("/{name}/start")
async def start_service(name: str, request: Request):
    return await _perform_action(name, "start", request)


@router.post("/{name}/stop")
async def stop_service(name: str, request: Request):
    return await _perform_action(name, "stop", request)


@router.post("/{name}/restart")
async def restart_service(name: str, request: Request):
    return await _perform_action(name, "restart", request)
