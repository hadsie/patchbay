from __future__ import annotations

from fastapi import APIRouter, Request

from patchbay.auth import resolve_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
async def me(request: Request):
    auth_config = request.app.state.config.global_config.auth
    auth_ctx = resolve_user(request, auth_config)
    return {
        "username": auth_ctx.username,
        "roles": sorted(auth_ctx.roles),
        "authenticated": auth_ctx.authenticated,
    }
