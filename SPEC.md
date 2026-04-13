# Patchbay — Project Specification

> **A lightweight service control dashboard for resource-constrained Docker and Linux hosts.**

Patchbay gives you a single-page, mobile-first overview of your services (Docker containers, Docker Compose projects, and systemd units) with the ability to toggle them on/off, restart them, or activate **presets** --- named configurations that stop, start, and restart groups of services in a defined order. Built for homelabs and workstations where GPU-heavy or RAM-heavy services can't all run simultaneously.

**Repository:** `patchbay`
**Default port:** `4848` (a nod to the 48-point audio patchbay standard)
**License:** MIT

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Core Concepts](#2-core-concepts)
3. [Architecture](#3-architecture)
4. [Tech Stack](#4-tech-stack)
5. [Configuration Files](#5-configuration-files)
6. [API Design](#6-api-design)
7. [Web UI](#7-web-ui)
8. [CLI](#8-cli)
9. [Health Checking](#9-health-checking)
10. [Authentication](#10-authentication)
11. [Deployment](#11-deployment)
12. [Development Roadmap](#12-development-roadmap)
13. [Project Structure](#13-project-structure)

---

## 1. Problem Statement

Running multiple resource-intensive services (LLM inference, image generation, document processing) on a single host with limited GPU VRAM or RAM means constantly SSH-ing in to stop one service before starting another. Existing tools like Portainer and Dockge let you manage Docker containers, but none offer **preset-based group switching** — the ability to click "Image Generation" and have the system stop your LLM server, then start ComfyUI, in the correct order.

Patchbay solves this with:
- A unified dashboard for Docker containers, Docker Compose projects, and systemd services.
- One-click presets that orchestrate stop/start/restart sequences.
- Three interfaces (Web UI, CLI, REST API) so humans and AI agents can control services equally well.

---

## 2. Core Concepts

### Services

A **service** is a Docker container, a Docker Compose project, or a systemd unit on the host. Each service has a human-readable name, description, a type (`docker`, `compose`, or `systemd`), and the corresponding identifier (container name, compose project directory, or unit name). Services are defined in `services.yml` and displayed on the dashboard with their current status, a toggle switch, and a restart button.

### Presets

A **preset** is a named configuration that defines an ordered sequence of `stop`, `start`, and `restart` actions on specific services. When a preset is activated:

1. All actions execute sequentially, in the order listed.
2. Each action waits for confirmation before proceeding to the next.
3. Any service **not mentioned** in the preset is left in its current state.

This means always-on services (reverse proxy, file sync, databases) are never disrupted by preset activation.

### Categories

Services are grouped into **categories** (e.g., "AI", "Infrastructure", "Productivity") for visual organization on the dashboard. Categories are purely a display concept with no operational meaning.

---

## 3. Architecture

```
┌─────────────┐  ┌─────────────┐  ┌──────────────┐
│   Web UI    │  │     CLI     │  │   AI Agent   │
│  (browser)  │  │  (Python)   │  │  (tool-call) │
└──────┬──────┘  └──────┬──────┘  └──────┬───────┘
       │                │                │
       └────────────────┼────────────────┘
                        │ HTTP / JSON
                ┌───────┴────────┐
                │   REST API     │
                │   (FastAPI)    │
                │                │
                │  OpenAPI spec  │
                │  auto-generated│
                ├────────────────┤
                │  Service       │
                │  Backends:     │
                │  ┌───────────┐ │
                │  │ docker-py │ │
                │  ├───────────┤ │
                │  │ compose   │ │
                │  │ (docker   │ │
                │  │  compose  │ │
                │  │  CLI)     │ │
                │  ├───────────┤ │
                │  │ systemd   │ │
                │  │ (D-Bus /  │ │
                │  │  subprocess)│
                │  └───────────┘ │
                ├────────────────┤
                │  YAML Config   │
                │  (mounted vol) │
                └────────────────┘
                        │
              ┌─────────┼─────────┐
              │                   │
    ┌─────────┴──────┐  ┌────────┴────────┐
    │ Docker Socket  │  │ systemd D-Bus / │
    │ /var/run/      │  │ systemctl CLI   │
    │ docker.sock    │  │                 │
    └────────────────┘  └─────────────────┘
```

### Interfaces

All three interfaces call the same REST API:

1. **Web UI** — Mobile-first single-page dashboard served by FastAPI using Jinja2 templates. Alpine.js handles client-side interactivity. Tailwind CSS (CDN) for styling.

2. **CLI** — Thin Python client that calls the Patchbay API. Pip-installable or usable as a single script.

3. **REST API** — FastAPI with auto-generated OpenAPI spec. AI agents discover and call endpoints via tool-use/function-calling. Authenticated via API key for remote access.

---

## 4. Tech Stack

### Backend
- **Language:** Python 3.11+
- **Framework:** FastAPI
- **Docker integration:** docker-py (Docker SDK for Python)
- **Systemd integration:** `subprocess` calls to `systemctl` (MVP), D-Bus via `dasbus` (future)
- **Config parsing:** PyYAML
- **Template engine:** Jinja2 (via FastAPI/Starlette)
- **ASGI server:** Uvicorn

### Frontend
- **Rendering:** Jinja2 server-side templates for initial page load
- **Reactivity:** Alpine.js (CDN, ~15kb) for client-side interactivity
- **Styling:** Tailwind CSS (CDN play script, zero build step)
- **Build step:** None. The entire frontend is HTML templates + CDN scripts.

### Why this stack
- **Zero JS build pipeline.** No npm, no node_modules, no bundler. The project is pure Python.
- **Claude Code friendly.** Single-language project with small, well-documented libraries. The full API surfaces of Alpine.js and HTMX fit in context.
- **Contributor friendly.** To hack on the frontend, edit an HTML file and reload. No waiting for Vite/webpack.
- **Mobile-first by default.** Tailwind's responsive utilities and simple DOM structure work well on small screens.

---

## 5. Configuration Files

Configuration is split across three YAML files, all volume-mounted into the container at `/config/`.

### 5.1 `config.yml` — Global Settings

```yaml
# =============================================================================
# Patchbay — Global Settings
# =============================================================================

# How often the dashboard polls for service status (seconds)
poll_interval: 5

# API server bind address and port
host: "0.0.0.0"
port: 4848

# Log level: debug, info, warning, error
log_level: info
```

### 5.2 `services.yml` — Service Definitions

#### Service fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | yes | | Unique display name. Slugified (lowercased, spaces to hyphens) for API URL matching and uniqueness checks. "Open WebUI" is accessed as `/api/services/open-webui`. |
| `type` | yes | | Backend type: `"docker"`, `"compose"`, or `"systemd"`. |
| `target` | yes | | What the backend operates on. Interpretation depends on `type` (see below). |
| `description` | no | `""` | Short text shown below the service name on the dashboard. |
| `icon` | no | `""` | Emoji displayed to the left of the service name. |
| `category` | no | `"Uncategorized"` | Grouping label. Services with the same category are displayed together. |
| `url` | no | `null` | If set, the service name becomes a clickable link (opens in a new tab). |
| `health_check` | no | `null` | HTTP health check configuration (see below). |

**`target` by type:**

| Type | `target` value | Example |
|------|---------------|---------|
| `docker` | Container name (as shown by `docker ps`). | `llama-server` |
| `compose` | Absolute path to the Compose project directory (must contain a `compose.yml` / `docker-compose.yml`). | `/opt/stacks/erpnext` |
| `systemd` | Systemd unit name. The `.service` suffix is optional. | `sshd.service` |

**`health_check` sub-fields:**

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `endpoint` | yes | | Full URL to check (must be a valid URL). |
| `method` | no | `"GET"` | HTTP method. |
| `expected` | no | `200` | Expected HTTP status code. |
| `timeout` | no | `5` | Request timeout in seconds. |
| `interval` | no | `30` | How often to run the check, in seconds. |

```yaml

services:
  - name: llama-server
    type: docker
    target: llama-server
    description: "llama.cpp inference server · Qwen3.5-35B-A3B"
    icon: "🦙"
    category: AI
    url: "http://espresso.local:8081"
    health_check:
      endpoint: "http://localhost:8081/health"

  - name: ComfyUI
    type: docker
    target: comfyui
    description: "Stable Diffusion image generation interface"
    icon: "🎨"
    category: AI
    url: "http://espresso.local:8188"
    health_check:
      endpoint: "http://localhost:8188/system_stats"

  - name: Docling
    type: docker
    target: docling-serve
    description: "Document parsing and conversion service"
    icon: "📄"
    category: AI
    url: "http://espresso.local:5001"
    health_check:
      endpoint: "http://localhost:5001/health"

  - name: Open WebUI
    type: docker
    target: open-webui
    description: "Chat interface for local and remote LLMs"
    icon: "💬"
    category: AI
    url: "http://espresso.local:3000"

  - name: Ollama
    type: docker
    target: ollama
    description: "LLM model server"
    icon: "🧠"
    category: AI

  - name: Immich
    type: docker
    target: immich-server
    description: "Self-hosted photo and video management"
    icon: "📷"
    category: Media
    url: "http://espresso.local:2283"

  - name: Traefik
    type: docker
    target: traefik
    description: "Reverse proxy and SSL termination"
    icon: "🔀"
    category: Infrastructure

  - name: Authentik
    type: docker
    target: authentik-server
    description: "Identity provider and SSO"
    icon: "🔐"
    category: Infrastructure

  - name: sshd
    type: systemd
    target: sshd.service
    description: "OpenSSH server daemon"
    icon: "📡"
    category: Infrastructure

  - name: Paperless-ngx
    type: docker
    target: paperless-webserver
    description: "Document management system"
    icon: "🗃️"
    category: Productivity
    url: "http://espresso.local:8000"

  - name: Firefly III
    type: docker
    target: firefly-iii
    description: "Personal finance manager"
    icon: "🏦"
    category: Productivity

  - name: Syncthing
    type: docker
    target: syncthing
    description: "Continuous file synchronization"
    icon: "🔄"
    category: Productivity

  - name: ERPNext
    type: compose
    target: /opt/stacks/erpnext
    description: "Full-stack ERP suite"
    icon: "📊"
    category: Business
    url: "http://espresso.local:8069"
    health_check:
      endpoint: "http://localhost:8069/api/method/ping"
```

### 5.3 `presets.yml` — Preset Definitions

```yaml
# =============================================================================
# Patchbay — Preset Definitions
# =============================================================================
#
# A preset defines an ordered sequence of actions on services.
#
# When activated, actions execute sequentially in list order.
# Each action waits for confirmation before proceeding to the next.
# Services not mentioned in the preset are left in their current state.
#
# Fields:
#   name          (required)  Display name for the preset button
#   description   (optional)  Tooltip or subtitle on the dashboard
#   icon          (optional)  Emoji
#   actions       (required)  Ordered list of actions to execute
#     service     (required)  Service name (must match a name in services.yml)
#     action      (required)  "stop", "start", or "restart"

presets:
  - name: LLM Chat
    description: "Inference server + chat UI for text generation"
    icon: "💬"
    actions:
      - service: ComfyUI
        action: stop
      - service: llama-server
        action: start
      - service: Open WebUI
        action: start

  - name: Image Generation
    description: "ComfyUI for Stable Diffusion workflows"
    icon: "🎨"
    actions:
      - service: llama-server
        action: stop
      - service: Docling
        action: stop
      - service: ComfyUI
        action: start

  - name: Document Processing
    description: "Docling + llama-server for document analysis"
    icon: "📄"
    actions:
      - service: ComfyUI
        action: stop
      - service: Docling
        action: start
      - service: llama-server
        action: start

  - name: Switch LLM Model
    description: "Restart llama-server to load a different model"
    icon: "🔁"
    actions:
      - service: llama-server
        action: restart

  - name: All AI Off
    description: "Stop all GPU-intensive services to free resources"
    icon: "🔌"
    actions:
      - service: llama-server
        action: stop
      - service: ComfyUI
        action: stop
      - service: Docling
        action: stop
      - service: Ollama
        action: stop
```

### 5.4 Config Validation

On startup, Patchbay validates all three config files:

- All service `name` values must be unique.
- All `type` values must be `"docker"`, `"compose"`, or `"systemd"`.
- All `target` values must be non-empty strings.
- All preset action `service` values must reference a defined service name.
- All preset action `action` values must be `"stop"`, `"start"`, or `"restart"`.
- Health check `endpoint` values must be valid URLs.
- `poll_interval` must be a positive integer.
- `port` must be a valid port number (1-65535).

Invalid config prevents startup with a clear, specific error message indicating the file and field that failed validation.

### 5.5 Config Reloading

`POST /api/config/reload` re-reads and validates all three YAML files without restarting the container. If validation fails, the existing config is retained and the error is returned in the response.

---

## 6. API Design

Base path: `/api`

All endpoints return JSON. The web UI uses these same endpoints via Alpine.js `fetch()` calls.

### 6.1 Services

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/services` | List all services with current status |
| `GET` | `/api/services/{name}` | Get single service status and health |
| `POST` | `/api/services/{name}/start` | Start a service |
| `POST` | `/api/services/{name}/stop` | Stop a service |
| `POST` | `/api/services/{name}/restart` | Restart a service |

### 6.2 Presets

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/presets` | List all presets |
| `GET` | `/api/presets/{name}` | Get single preset definition |
| `POST` | `/api/presets/{name}/activate` | Activate a preset (execute actions sequentially) |

### 6.3 System

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | API health check (returns 200 if Patchbay itself is running) |
| `GET` | `/api/config` | Return current parsed config (read-only, all three files merged) |
| `POST` | `/api/config/reload` | Reload all config files from disk |

### 6.4 Response Schemas

**Service status object** (`GET /api/services` returns a list of these):

```json
{
  "name": "llama-server",
  "type": "docker",
  "target": "llama-server",
  "description": "llama.cpp inference server · Qwen3.5-35B-A3B",
  "category": "AI",
  "icon": "🦙",
  "url": "http://espresso.local:8081",
  "state": "running",
  "health": "healthy",
  "uptime": "2d 4h 12m"
}
```

**`state` values** (normalized across all backend types):

| State | Meaning |
|---|---|
| `running` | Service is up and operational |
| `stopped` | Service is down (normal/intentional) |
| `error` | Service has failed (Docker container dead, systemd unit failed) |
| `restarting` | Service is transitioning between states |
| `partial` | Compose projects only: some containers running, some stopped |
| `unknown` | State could not be determined |

**`health` values:**
- `healthy` — Service is running and health check passes (or no health check configured for a running service).
- `unhealthy` — Service is running but health check is failing.
- `no_check` — No health check configured (shown as healthy if running).
- `pending` — Health check hasn't completed its first run yet.
- `n/a` — Service is stopped (health is not evaluated).

**Service action response** (`POST /api/services/{name}/start|stop|restart`):

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

On failure:

```json
{
  "name": "llama-server",
  "action": "start",
  "result": "error",
  "error": "Container not found: llama-server",
  "previous_state": "unknown",
  "current_state": "unknown"
}
```

**Preset activation response** (`POST /api/presets/{name}/activate`):

```json
{
  "preset": "Image Generation",
  "status": "completed",
  "actions": [
    { "service": "llama-server", "action": "stop", "result": "success", "duration_seconds": 1.2 },
    { "service": "Docling", "action": "stop", "result": "success", "duration_seconds": 0.8 },
    { "service": "ComfyUI", "action": "start", "result": "success", "duration_seconds": 3.1 }
  ],
  "total_duration_seconds": 5.1
}
```

If any action fails, subsequent actions are **not executed** and the response indicates where it failed:

```json
{
  "preset": "Image Generation",
  "status": "failed",
  "actions": [
    { "service": "llama-server", "action": "stop", "result": "success", "duration_seconds": 1.2 },
    { "service": "Docling", "action": "stop", "result": "error", "error": "Container not found" }
  ],
  "failed_at": 1,
  "total_duration_seconds": 2.0
}
```

### 6.5 Error Responses

All errors return appropriate HTTP status codes with a consistent JSON body:

```json
{
  "error": "Service not found: nonexistent-service",
  "code": "SERVICE_NOT_FOUND"
}
```

Error codes: `SERVICE_NOT_FOUND`, `PRESET_NOT_FOUND`, `ACTION_FAILED`, `CONFIG_INVALID`, `CONFIG_RELOAD_FAILED`, `UNAUTHORIZED`.

---

## 7. Web UI

### 7.1 Overview

The web UI is a single page served at `/` by FastAPI. The initial HTML is rendered server-side via Jinja2 (fast first paint, no loading spinner). Alpine.js takes over for all interactivity: toggling services, activating presets, polling for status updates.

### 7.2 Page Structure

```
┌─────────────────────────────────────────────────┐
│  ⚡ Patchbay  :4848        espresso.local   [↻] │  ← Header (sticky)
├─────────────────────────────────────────────────┤
│                                                 │
│  PRESETS                                        │
│  [💬 LLM Chat] [🎨 Image Gen] [📄 DocProc]     │  ← Preset buttons
│  [🔁 Switch LLM] [🔌 All AI Off]               │
│                                                 │
│  AI ─────────────────────────────────────────   │  ← Category header
│  ┌─────────────────────────────────────────────┐│
│  │ 🦙 llama-server  [docker]  ● running  [↻ ━]││  ← Service row
│  │ 🎨 ComfyUI       [docker]  ○ stopped  [↻ ━]││
│  │ 📄 Docling       [docker]  ○ stopped  [↻ ━]││
│  │ 💬 Open WebUI    [docker]  ● running  [↻ ━]││
│  │ 🧠 Ollama        [docker]  ● running  [↻ ━]││
│  └─────────────────────────────────────────────┘│
│                                                 │
│  INFRASTRUCTURE ─────────────────────────────   │
│  ┌─────────────────────────────────────────────┐│
│  │ 🔀 Traefik       [docker]  ● running  [↻ ━]││
│  │ 🔐 Authentik     [docker]  ● running  [↻ ━]││
│  │ 📡 sshd          [systemd] ● running  [↻ ━]││
│  └─────────────────────────────────────────────┘│
│                                                 │
│  ...more categories...                          │
├─────────────────────────────────────────────────┤
│  Patchbay v0.1.0 · API Docs · GitHub            │  ← Footer
└─────────────────────────────────────────────────┘
```

### 7.3 UI Components and Behavior

**Service row** contains:
- Icon (emoji)
- Service name (clickable link to `url` if configured, opens new tab)
- Type badge (`docker`, `compose`, or `systemd`, visually distinct colors)
- Status chip with colored dot (green=running, grey=stopped, yellow=unhealthy/partial, red=error, blue-pulse=restarting)
- Uptime (e.g., "2d 4h" or "—" if stopped)
- Restart button (↻, disabled when service is stopped)
- Toggle switch (on/off)

**Toggle behavior:**
1. User clicks toggle.
2. Toggle enters "transitioning" state (pulsing animation).
3. Alpine.js sends POST to `/api/services/{name}/start` or `/stop`.
4. On success response, toggle and status chip update to reflect new state.
5. On error, toggle reverts and an error toast appears.

**Restart button behavior:**
1. User clicks ↻.
2. Button enters spinning animation.
3. Alpine.js sends POST to `/api/services/{name}/restart`.
4. Status chip shows "restarting" during the operation.
5. On success, status returns to "running"/"active".

**Preset button behavior:**
1. User clicks a preset button.
2. Button shows a progress bar animation.
3. All other preset buttons and service controls are disabled during execution.
4. Alpine.js sends POST to `/api/presets/{name}/activate`.
5. As the response returns, affected service rows update their state.
6. On completion, the active preset is highlighted. On failure, an error toast shows which action failed.

**Polling:**
- Alpine.js polls `GET /api/services` every `poll_interval` seconds (from config).
- On each poll response, all service states and health values are updated in the UI.
- Polling pauses during an active preset execution or service toggle to avoid state conflicts.

### 7.4 Mobile Design

The UI must be mobile-first:
- Service rows stack vertically on small screens.
- Toggle and restart controls remain easily tappable (minimum 44px touch targets).
- Preset buttons wrap and remain usable at narrow widths.
- Status information collapses gracefully (uptime may be hidden on very small screens).
- No horizontal scrolling at any viewport width.
- Test at 320px, 375px, and 414px widths.

### 7.5 Template Structure

```
templates/
├── base.html          # HTML shell, Tailwind CDN, Alpine.js CDN, shared layout
├── index.html         # Main dashboard page (extends base.html)
└── components/
    ├── header.html    # Logo, host status, reload button
    ├── presets.html   # Preset button bar
    ├── service.html   # Single service row (reused in loop)
    └── footer.html    # Version, links
```

### 7.6 Frontend File Serving

Static assets (if any, such as a favicon or custom CSS overrides) are served from a `/static/` directory by FastAPI's `StaticFiles` mount. The Tailwind CDN and Alpine.js CDN are loaded via `<script>` tags in `base.html` — no local copies needed.

### 7.7 Visual Reference

See `patchbay-mockup.html` for the reference design. Key visual decisions from the mockup:
- Dark theme (dark navy/charcoal background)
- Subtle grid texture background
- Monospace font (DM Mono) for status text, labels, and badges
- Sans-serif font (Outfit) for service names and UI text
- Green glow for running status dots
- Yellow for unhealthy, red for error states
- Blue accent for active presets and hover states
- Category sections with thin divider lines
- Rounded card containers for service groups
- Compact service rows with all controls inline

---

## 8. CLI

The CLI is a thin Python client that calls the Patchbay REST API.

### 8.1 Commands

```bash
# Service management
patchbay status                        # Table of all services with state/health
patchbay status llama-server           # Single service detail
patchbay start llama-server            # Start a service
patchbay stop comfyui                  # Stop a service
patchbay restart docling               # Restart a service

# Presets
patchbay presets                       # List available presets
patchbay activate "Image Generation"   # Activate a preset, show progress

# System
patchbay config reload                 # Reload config from disk
patchbay health                        # Check API health

# Connection options
patchbay --host http://espresso.local:4848 status
patchbay --api-key mykey123 status
```

### 8.2 CLI Configuration

Connection info is resolved in priority order:
1. `--host` and `--api-key` flags (highest priority)
2. `PATCHBAY_HOST` and `PATCHBAY_API_KEY` environment variables
3. `~/.config/patchbay/cli.yml` config file
4. Default host: `http://localhost:4848`

### 8.3 Output

- `patchbay status` outputs a formatted table to the terminal.
- `patchbay activate` shows real-time progress: each action and its result as it completes.
- All commands support `--json` flag for machine-readable JSON output (useful for scripting and agent integration).

### 8.4 Implementation

The CLI should use `httpx` (or `requests`) for HTTP and `typer` (or `click`) for the command framework. It should be pip-installable from the same repository as an optional extra or a separate entry point.

---

## 9. Health Checking

Patchbay uses a layered health checking approach.

### 9.1 Base State Check (always runs)

**Docker services:** Patchbay queries the Docker daemon for container state via docker-py. This returns the container's status: `running`, `stopped`, `restarting`, `paused`, `dead`.

**Compose services:** Patchbay runs `docker compose ps --format json` in the project directory and aggregates container states. All running = `running`, all stopped/exited = `stopped`, mixed = `partial`.

**Systemd services:** Patchbay calls `systemctl is-active {unit}` (via subprocess). This returns: `active`, `inactive`, `failed`, `activating`, `deactivating`.

These base state checks run on every poll cycle (configurable via `poll_interval`).

### 9.2 Docker Health Check (automatic for Docker services)

If a Docker container defines a `HEALTHCHECK` instruction in its Dockerfile or compose file, Docker itself tracks health status (`healthy`, `unhealthy`, `starting`). Patchbay reads this from the container's inspect data via docker-py. No additional configuration needed.

### 9.3 HTTP Health Check (optional, configured per-service)

For services that don't have a Docker `HEALTHCHECK`, or for systemd services that expose an HTTP endpoint, you can configure an HTTP health check in `services.yml`:

```yaml
health_check:
  endpoint: "http://localhost:8081/health"
  method: GET          # optional, default GET
  expected: 200        # optional, default 200
  timeout: 5           # optional, seconds, default 5
  interval: 30         # optional, seconds, default 30
```

The health check runner makes the HTTP request at the specified interval and records success/failure.

### 9.4 Health Resolution Logic

The `health` field in the API response is resolved as follows:

1. If the service is stopped/inactive → `health: "n/a"`
2. If an HTTP `health_check` is configured in services.yml → use that result (`healthy` / `unhealthy` / `pending`)
3. Else if the service is a Docker container with a built-in HEALTHCHECK → use Docker's health status
4. Else if the service is running/active → `health: "healthy"` (assume healthy if no check is configured)
5. Else if the service state is `partial` (compose only) → `health: "unhealthy"` (some containers are down)

---

## 10. Authentication

### 10.1 Web UI Authentication

Patchbay itself implements **no web authentication**. Web UI auth is handled externally via **Authentik** through Traefik's forward-auth middleware.

The Traefik configuration applies a `forwardAuth` middleware that validates sessions against an Authentik outpost before proxying requests to Patchbay. The Patchbay container is completely auth-unaware for browser requests.

This means:
- During development, the dashboard can be accessed directly on port 4848 without auth.
- In production, Traefik handles auth before requests reach Patchbay.

### 10.2 API Key Authentication (for CLI and AI Agents)

For non-browser access (CLI, AI agents, scripts), Patchbay supports API key authentication. This is needed for remote access where Traefik forward-auth may not apply.

**Implementation:**
- API keys are stored in `config.yml` as a list of hashed keys with labels.
- Requests include the key via the `Authorization: Bearer <key>` header.
- If no API keys are configured in `config.yml`, API key auth is disabled (all requests are allowed). This preserves the zero-config local development experience.

**Config example:**
```yaml
# In config.yml
api_keys:
  - label: "claude-agent"
    key_hash: "$2b$12$..."   # bcrypt hash of the actual key
  - label: "cli-laptop"
    key_hash: "$2b$12$..."
```

**Key generation helper (CLI command):**
```bash
patchbay generate-key "claude-agent"
# Output:
# API Key: pb_a1b2c3d4e5f6...  (save this, it won't be shown again)
# Hash:    $2b$12$...           (add this to config.yml)
```

### 10.3 Auth Middleware Logic

For each incoming API request:
1. If the request path starts with `/api/` and API keys are configured in `config.yml`:
   - Check for `Authorization: Bearer <key>` header.
   - Verify the key against stored hashes.
   - Reject with 401 if invalid or missing.
2. If no API keys are configured → skip auth (all requests allowed).
3. Requests to `/` (web UI) and `/static/` are never API-key-checked (they rely on Traefik/Authentik).

---

## 11. Deployment

### 11.1 Docker Compose (basic, Docker-only services)

```yaml
services:
  patchbay:
    image: patchbay:latest
    container_name: patchbay
    restart: unless-stopped
    ports:
      - "4848:4848"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./config:/config:ro
    environment:
      - CONFIG_DIR=/config
```

### 11.2 Traefik + Authentik (production)

```yaml
services:
  patchbay:
    image: patchbay:latest
    container_name: patchbay
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./config:/config:ro
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.patchbay.rule=Host(`patchbay.espresso.local`)"
      - "traefik.http.routers.patchbay.middlewares=authentik@docker"
      - "traefik.http.services.patchbay.loadbalancer.server.port=4848"
```

### 11.3 Direct Install (for systemd + Docker service support)

For managing Docker containers, Compose projects, and systemd units together, Patchbay must run directly on the host (not in a Docker container), since accessing systemd from within a container requires privileged mode and D-Bus socket mounting, which is fragile.

```bash
pip install patchbay
patchbay serve --config-dir /etc/patchbay/
```

Or as a systemd service itself:

```ini
[Unit]
Description=Patchbay Service Dashboard
After=network.target docker.service

[Service]
Type=simple
ExecStart=/usr/local/bin/patchbay serve --config-dir /etc/patchbay
Restart=always
User=patchbay

[Install]
WantedBy=multi-user.target
```

The `patchbay` user needs:
- Membership in the `docker` group (for Docker socket access).
- Sudo or polkit permissions for `systemctl start/stop/restart` on managed units.

### 11.4 Docker Socket Security

Mounting the Docker socket grants Patchbay full control over all containers. For hardened deployments, consider using **Tecnativa/docker-socket-proxy** to whitelist only the Docker API endpoints Patchbay needs:
- `GET /containers/json` (list)
- `GET /containers/{id}/json` (inspect)
- `POST /containers/{id}/start`
- `POST /containers/{id}/stop`
- `POST /containers/{id}/restart`

---

## 12. Development Roadmap

### MVP (v0.1) -- Complete

- [x] Project scaffolding (FastAPI app, directory structure, Dockerfile)
- [x] YAML config parsing and validation for all three files
- [x] Docker service backend (list, start, stop, restart via docker-py)
- [x] Systemd service backend (list, start, stop, restart via subprocess/systemctl)
- [x] Service status polling with base state + Docker HEALTHCHECK + HTTP health checks
- [x] REST API: all service, preset, and system endpoints
- [x] Preset activation engine with sequential ordered execution
- [x] Web UI: Jinja2 + Alpine.js + Tailwind CDN dashboard
- [x] Mobile-responsive layout
- [x] Auto-generated OpenAPI documentation at `/docs`
- [x] Dockerfile and compose.yml
- [x] README with setup instructions
- [x] Config reload without restart (`POST /api/config/reload`)
- [x] Error toast notifications in the web UI
- [x] Docker Compose backend (manage multi-container stacks as a single service, `partial` state aggregation)

### v0.2

- [ ] CLI tool (pip-installable, calls REST API)
- [ ] API key authentication for remote CLI/agent access
- [ ] `patchbay generate-key` CLI command
- [ ] Preset activation progress display (per-action status updates in UI)

### Future

- [ ] WebSocket for real-time status updates (replace polling)
- [ ] Docker socket proxy support for least-privilege access
- [ ] User roles and permissions (read-only vs. operator)
- [ ] Preset scheduling (activate preset X at time Y, cron-style)
- [ ] Activity log / audit trail
- [ ] Multi-host support (manage services across multiple hosts via agents)
- [ ] GPU/VRAM utilization display (nvidia-smi integration)
- [ ] Plugin system for additional service backends (Podman, LXC, etc.)
- [ ] PWA support for mobile home screen installation

---

## 13. Project Structure

```
patchbay/
├── CLAUDE.md              # Instructions for Claude Code (reference this spec + mockup)
├── README.md
├── Dockerfile
├── compose.yml
├── pyproject.toml         # Python project config (dependencies, entry point)
├── config/                # Config files (user copies examples and customizes)
│   ├── config.yml
│   ├── services.yml
│   ├── services.example.yml
│   ├── presets.yml
│   └── presets.example.yml
├── patchbay/
│   ├── __init__.py
│   ├── main.py            # FastAPI app factory, startup, route mounting
│   ├── config.py          # YAML loading, validation, reload logic
│   ├── models.py          # Pydantic models for API request/response schemas
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── services.py    # /api/services/* endpoints
│   │   ├── presets.py     # /api/presets/* endpoints
│   │   └── system.py      # /api/health, /api/config/* endpoints
│   ├── backends/
│   │   ├── __init__.py
│   │   ├── base.py        # Abstract base class for service backends
│   │   ├── compose.py     # Docker Compose backend (docker compose CLI)
│   │   ├── docker.py      # Docker backend (docker-py)
│   │   ├── systemd.py     # Systemd backend (subprocess + systemctl)
│   │   └── util.py        # Shared utilities (uptime formatting)
│   ├── health.py          # Health check runner (HTTP checks, aggregation)
│   ├── presets.py         # Preset activation engine (sequential executor)
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html
│   │   └── components/
│   │       ├── header.html
│   │       ├── presets.html
│   │       ├── service.html
│   │       └── footer.html
│   └── static/
│       └── favicon.ico
└── tests/
    ├── __init__.py
    ├── conftest.py            # Shared fixtures (mock backends, test config, test client)
    ├── test_backends.py
    ├── test_compose_backend.py
    ├── test_config.py
    ├── test_services.py
    ├── test_presets.py
    └── test_health.py
```
