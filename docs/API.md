# Patchbay API Reference

Base URL: `http://<host>:4848`

All endpoints return JSON. Authentication is via `Authorization: Bearer <key>` header (see [AUTH.md](AUTH.md) for setup).

---

## Quick start

```bash
# List all services
curl -H "Authorization: Bearer $PATCHBAY_KEY" http://localhost:4848/api/services

# Start a service
curl -X POST -H "Authorization: Bearer $PATCHBAY_KEY" http://localhost:4848/api/services/llama-server/start

# Activate a preset (names are slug-matched: lowercase, spaces to hyphens)
curl -X POST -H "Authorization: Bearer $PATCHBAY_KEY" http://localhost:4848/api/presets/llm-chat/activate
```

---

## Authentication

If API keys are configured and auth is enabled, every `/api/` request must include a valid Bearer token. Requests without a token (or with an invalid token) receive `401`.

If auth is disabled (the default), no token is needed.

See [AUTH.md](AUTH.md) for key generation and configuration.

---

## Service states

All backends (Docker, Docker Compose, systemd) return the same normalized state values:

| State | Meaning |
|---|---|
| `running` | Service is up and operational |
| `stopped` | Service is down (normal/intentional) |
| `error` | Service has failed (Docker container dead, systemd unit failed) |
| `restarting` | Service is transitioning between states |
| `partial` | Compose projects only: some containers running, some stopped |
| `unknown` | State could not be determined |

A service is considered "on" if its state is `running`, `restarting`, or `partial`. It is "off" if `stopped`, `error`, or `unknown`.

To toggle a service: if `state` is `running`, POST `/stop`; otherwise POST `/start`.

## Health values

| Health | Meaning |
|---|---|
| `healthy` | Running and health check passes (or no check configured) |
| `unhealthy` | Running but health check is failing |
| `pending` | Health check hasn't completed its first run yet |
| `n/a` | Service is not running; health is not evaluated |

---

## Endpoints

### GET /api/services

List all services the authenticated user can view.

**Response:** `200 OK`

```json
[
  {
    "name": "llama-server",
    "type": "docker",
    "target": "llama-server",
    "description": "llama.cpp inference server",
    "category": "AI",
    "icon": "",
    "url": "http://espresso.local:8081",
    "state": "running",
    "health": "healthy",
    "uptime": "2d 4h 12m",
    "can_control": true
  }
]
```

| Field | Type | Description |
|---|---|---|
| `name` | string | Display name. For URL paths, use the slug form (lowercase, spaces to hyphens): "Open WebUI" becomes `open-webui`. |
| `type` | string | Backend type: `docker`, `compose`, or `systemd` |
| `target` | string | Backend-specific identifier (container name, compose project path, systemd unit) |
| `description` | string | Human-readable description |
| `category` | string | Grouping label for display |
| `icon` | string | Emoji icon (may be empty) |
| `url` | string or null | Web UI link for the service, if configured |
| `state` | string | Normalized state (see table above) |
| `health` | string | Health status (see table above) |
| `uptime` | string or null | Human-readable uptime (e.g., "2d 4h 12m"), null if not running |
| `can_control` | boolean | Whether the authenticated user can start/stop/restart this service |

### GET /api/services/{name}

Get a single service by name.

**Response:** `200 OK` -- same object as above.

**Errors:**
- `404` if the service does not exist or the user cannot view it.

### POST /api/services/{name}/start

Start a stopped service.

**Response:** `200 OK`

```json
{
  "name": "llama-server",
  "action": "start",
  "result": "success",
  "previous_state": "stopped",
  "current_state": "running",
  "duration_seconds": 2.3
}
```

**Errors:**
- `403` with `{"error": "...", "code": "FORBIDDEN"}` if the user lacks control permission.
- `404` if the service does not exist or the user cannot view it.
- `500` with `{"error": "...", "code": "ACTION_FAILED"}` if the backend action fails.

### POST /api/services/{name}/stop

Stop a running service. Same response format as start.

### POST /api/services/{name}/restart

Restart a service. Same response format as start.

---

### GET /api/presets

List all presets the authenticated user can view.

**Response:** `200 OK`

```json
[
  {
    "name": "LLM Chat",
    "description": "Start the LLM inference stack",
    "icon": "",
    "actions": [
      {"service": "llama-server", "action": "start"},
      {"service": "open-webui", "action": "start"}
    ],
    "can_control": true
  }
]
```

### GET /api/presets/{name}

Get a single preset by name.

**Errors:**
- `404` if the preset does not exist or the user cannot view it.

### POST /api/presets/{name}/activate

Execute all actions in the preset sequentially. Each action waits for the previous one to complete. If any action fails, execution stops.

**Response:** `200 OK`

```json
{
  "preset": "LLM Chat",
  "status": "completed",
  "actions": [
    {"service": "llama-server", "action": "start", "result": "success", "duration_seconds": 2.1},
    {"service": "open-webui", "action": "start", "result": "success", "duration_seconds": 1.4}
  ],
  "total_duration_seconds": 3.5
}
```

On partial failure:

```json
{
  "preset": "LLM Chat",
  "status": "failed",
  "actions": [
    {"service": "llama-server", "action": "start", "result": "success", "duration_seconds": 2.1},
    {"service": "open-webui", "action": "start", "result": "error", "error": "Container not found"}
  ],
  "failed_at": 1,
  "total_duration_seconds": 2.5
}
```

**Errors:**
- `403` if the user lacks control permission on the preset.
- `404` if the preset does not exist or the user cannot view it.

---

### GET /api/auth/me

Returns the authenticated user's identity and roles.

**Response:** `200 OK`

```json
{"username": "api:claude-agent", "roles": ["admin"], "authenticated": true}
```

When auth is disabled:

```json
{"username": null, "roles": ["*"], "authenticated": false}
```

---

### GET /api/health

Simple liveness check for Patchbay itself.

**Response:** `200 OK`

```json
{"status": "ok"}
```

### POST /api/config/reload

Reload all config files from disk. New services, presets, auth settings, and API keys take effect immediately.

**Response:** `200 OK`

```json
{"status": "ok"}
```

**Errors:**
- `400` with `{"error": "...", "code": "CONFIG_RELOAD_FAILED"}` if config validation fails. The previous config remains active.

---

## Error format

All errors use a consistent format:

```json
{
  "error": "Human-readable error message",
  "code": "ERROR_CODE"
}
```

| Code | HTTP Status | Meaning |
|---|---|---|
| `SERVICE_NOT_FOUND` | 404 | Service name not recognized |
| `PRESET_NOT_FOUND` | 404 | Preset name not recognized |
| `ACTION_FAILED` | 500 | Backend action (start/stop/restart) failed |
| `FORBIDDEN` | 403 | Authenticated but lacking permission |
| `UNAUTHORIZED` | 401 | Missing or invalid authentication |
| `CONFIG_INVALID` | 400 | Config file has validation errors |
| `CONFIG_RELOAD_FAILED` | 400 | Config reload failed |

---

## Notes for AI agents

- **Service and preset names are slug-matched.** The API converts names to slugs (lowercase, spaces to hyphens) for matching. "Open WebUI" can be accessed as `/api/services/open-webui`. URL-encoding also works (`Open%20WebUI`), but slugs are simpler.
- **Presets are the preferred way to switch between resource-heavy workloads.** Rather than manually stopping and starting individual services, look for a preset that does what you need.
- **`can_control: false`** means the API key's roles don't have permission for that resource. Don't attempt start/stop/restart -- it will 403.
- **Polling:** `GET /api/services` is the way to check current state. There are no WebSockets or event streams.
- **After activating a preset**, poll `GET /api/services` to confirm all services reached their expected states.
- **State transitions are not instant.** After a start/stop/restart, the response includes the new state, but health checks may take a few seconds to update. Poll if you need to confirm health.
