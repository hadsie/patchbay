from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from patchbay import __version__
from patchbay.config import settings
from patchbay.models import ConfigResponse, HealthResponse

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@router.get("/config")
async def get_config(request: Request) -> ConfigResponse:
    config = request.app.state.config
    return ConfigResponse(
        poll_interval=config.global_config.poll_interval,
        host=config.global_config.host,
        port=config.global_config.port,
        log_level=config.global_config.log_level,
        services_count=len(config.services),
        presets_count=len(config.presets),
    )


@router.post("/config/reload")
async def reload_config(request: Request):
    try:
        new_config = settings.reload()
        request.app.state.config = new_config
        if hasattr(request.app.state, "health_checker"):
            await request.app.state.health_checker.update_config(new_config)
        return {"status": "ok", "message": "Config reloaded successfully"}
    except (ValueError, OSError) as exc:
        return JSONResponse(
            status_code=400,
            content={"error": str(exc), "code": "CONFIG_RELOAD_FAILED"},
        )
