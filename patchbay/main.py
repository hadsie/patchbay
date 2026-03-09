from __future__ import annotations

import json
import logging
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from patchbay import __version__
from patchbay.backends.base import BackendError, BackendUnavailableError, ServiceNotFoundError
from patchbay.backends.docker import DockerBackend
from patchbay.backends.systemd import SystemdBackend
from patchbay.config import settings
from patchbay.health import HealthChecker, resolve_health
from patchbay.routers import presets, services, system

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = settings.load()
    app.state.config = config

    logging.basicConfig(level=getattr(logging, config.global_config.log_level.upper()))

    backends: dict = {
        "docker": DockerBackend(),
        "systemd": SystemdBackend(),
    }
    app.state.backends = backends

    health_checker = HealthChecker()
    app.state.health_checker = health_checker
    await health_checker.start(config)

    yield

    await health_checker.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="Patchbay", version=__version__, lifespan=lifespan)

    app.include_router(services.router)
    app.include_router(presets.router)
    app.include_router(system.router)

    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")

    @app.exception_handler(ServiceNotFoundError)
    async def service_not_found_handler(request: Request, exc: ServiceNotFoundError):
        return JSONResponse(
            status_code=404,
            content={"error": str(exc), "code": "SERVICE_NOT_FOUND"},
        )

    @app.exception_handler(BackendUnavailableError)
    async def backend_unavailable_handler(request: Request, exc: BackendUnavailableError):
        return JSONResponse(
            status_code=503,
            content={"error": str(exc), "code": "BACKEND_UNAVAILABLE"},
        )

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        config = app.state.config
        backends = app.state.backends
        health_checker = app.state.health_checker

        # Build service statuses for initial render
        service_statuses = []
        for svc in config.services:
            backend = backends[svc.type]
            try:
                state = await backend.get_state(svc.target)
            except BackendError:
                state = "unknown"
            try:
                docker_health = (
                    await backend.get_health_info(svc.target) if svc.type == "docker" else None
                )
            except BackendError:
                docker_health = None
            try:
                uptime = await backend.get_uptime(svc.target)
            except BackendError:
                uptime = None

            checker_result = health_checker.results.get(svc.name)
            health = resolve_health(svc, state, checker_result, docker_health)

            service_statuses.append(
                {
                    "name": svc.name,
                    "type": svc.type,
                    "target": svc.target,
                    "description": svc.description,
                    "category": svc.category,
                    "icon": svc.icon,
                    "url": svc.url,
                    "state": state,
                    "health": health,
                    "uptime": uptime,
                }
            )

        # Group by category preserving order
        categories: OrderedDict[str, list] = OrderedDict()
        for s in service_statuses:
            categories.setdefault(s["category"], []).append(s)

        # Build preset data
        presets_data = [
            {
                "name": p.name,
                "description": p.description,
                "icon": p.icon,
                "actions": [{"service": a.service, "action": a.action} for a in p.actions],
            }
            for p in config.presets
        ]

        init_data = json.dumps(
            {
                "services": {s["name"]: s for s in service_statuses},
                "presets": presets_data,
                "pollInterval": config.global_config.poll_interval,
                "version": __version__,
            }
        )

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "categories": categories,
                "presets": config.presets,
                "config": config.global_config,
                "version": __version__,
                "init_data": init_data,
            },
        )

    return app


app = create_app()


def run():
    """Entry point for the `patchbay` console command."""
    import uvicorn

    config = settings.load()
    uvicorn.run(
        "patchbay.main:app",
        host=config.global_config.host,
        port=config.global_config.port,
    )
