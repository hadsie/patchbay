from __future__ import annotations

import time

from patchbay.backends.base import BackendError, ServiceBackend
from patchbay.config import AppConfig
from patchbay.models import PresetActionResult, PresetActivationResponse


async def activate_preset(
    preset_name: str,
    config: AppConfig,
    backends: dict[str, ServiceBackend],
) -> PresetActivationResponse:
    preset = None
    for p in config.presets:
        if p.name == preset_name:
            preset = p
            break

    if preset is None:
        raise KeyError(f"Preset not found: {preset_name}")

    service_map = {s.name: s for s in config.services}
    results: list[PresetActionResult] = []
    failed_at: int | None = None
    total_start = time.monotonic()

    for i, action in enumerate(preset.actions):
        svc = service_map[action.service]
        backend = backends[svc.type]
        action_start = time.monotonic()

        try:
            method = getattr(backend, action.action)
            await method(svc.target)
            duration = time.monotonic() - action_start
            results.append(
                PresetActionResult(
                    service=action.service,
                    action=action.action,
                    result="success",
                    duration_seconds=round(duration, 2),
                )
            )
        except BackendError as exc:
            duration = time.monotonic() - action_start
            results.append(
                PresetActionResult(
                    service=action.service,
                    action=action.action,
                    result="error",
                    duration_seconds=round(duration, 2),
                    error=str(exc),
                )
            )
            failed_at = i
            break

    total_duration = time.monotonic() - total_start
    return PresetActivationResponse(
        preset=preset_name,
        status="failed" if failed_at is not None else "completed",
        actions=results,
        failed_at=failed_at,
        total_duration_seconds=round(total_duration, 2),
    )
