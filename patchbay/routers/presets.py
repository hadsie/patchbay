from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from patchbay.models import PresetActionInfo, PresetActivationResponse, PresetInfo
from patchbay.presets import activate_preset

router = APIRouter(prefix="/api/presets", tags=["presets"])


@router.get("")
async def list_presets(request: Request) -> list[PresetInfo]:
    config = request.app.state.config
    return [
        PresetInfo(
            name=p.name,
            description=p.description,
            icon=p.icon,
            actions=[PresetActionInfo(service=a.service, action=a.action) for a in p.actions],
        )
        for p in config.presets
    ]


@router.get("/{name}")
async def get_preset(name: str, request: Request):
    config = request.app.state.config
    for p in config.presets:
        if p.name == name:
            return PresetInfo(
                name=p.name,
                description=p.description,
                icon=p.icon,
                actions=[PresetActionInfo(service=a.service, action=a.action) for a in p.actions],
            )
    return JSONResponse(
        status_code=404,
        content={"error": f"Preset not found: {name}", "code": "PRESET_NOT_FOUND"},
    )


@router.post("/{name}/activate")
async def activate(name: str, request: Request) -> PresetActivationResponse:
    config = request.app.state.config
    backends = request.app.state.backends
    try:
        return await activate_preset(name, config, backends)
    except KeyError:
        return JSONResponse(
            status_code=404,
            content={"error": f"Preset not found: {name}", "code": "PRESET_NOT_FOUND"},
        )
