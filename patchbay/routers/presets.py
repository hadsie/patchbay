from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from patchbay.auth import can_control, can_view, resolve_user
from patchbay.models import PresetActionInfo, PresetActivationResponse, PresetInfo
from patchbay.presets import activate_preset

router = APIRouter(prefix="/api/presets", tags=["presets"])


def _find_preset(config, name):
    for p in config.presets:
        if p.name == name:
            return p
    return None


@router.get("")
async def list_presets(request: Request) -> list[PresetInfo]:
    config = request.app.state.config
    auth_config = config.global_config.auth
    auth_ctx = resolve_user(request, auth_config)
    result = []
    for p in config.presets:
        if not can_view(auth_ctx, p, auth_config):
            continue
        result.append(
            PresetInfo(
                name=p.name,
                description=p.description,
                icon=p.icon,
                actions=[PresetActionInfo(service=a.service, action=a.action) for a in p.actions],
                can_control=can_control(auth_ctx, p, auth_config),
            )
        )
    return result


@router.get("/{name}")
async def get_preset(name: str, request: Request):
    config = request.app.state.config
    auth_config = config.global_config.auth
    auth_ctx = resolve_user(request, auth_config)
    p = _find_preset(config, name)
    if not p or not can_view(auth_ctx, p, auth_config):
        return JSONResponse(
            status_code=404,
            content={"error": f"Preset not found: {name}", "code": "PRESET_NOT_FOUND"},
        )
    return PresetInfo(
        name=p.name,
        description=p.description,
        icon=p.icon,
        actions=[PresetActionInfo(service=a.service, action=a.action) for a in p.actions],
        can_control=can_control(auth_ctx, p, auth_config),
    )


@router.post("/{name}/activate")
async def activate(name: str, request: Request) -> PresetActivationResponse:
    config = request.app.state.config
    auth_config = config.global_config.auth
    auth_ctx = resolve_user(request, auth_config)
    backends = request.app.state.backends
    p = _find_preset(config, name)
    if not p or not can_view(auth_ctx, p, auth_config):
        return JSONResponse(
            status_code=404,
            content={"error": f"Preset not found: {name}", "code": "PRESET_NOT_FOUND"},
        )
    if not can_control(auth_ctx, p, auth_config):
        return JSONResponse(
            status_code=403,
            content={"error": "Permission denied", "code": "FORBIDDEN"},
        )
    return await activate_preset(name, config, backends)
