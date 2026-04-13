# CLAUDE.md — Patchbay

## What is this project?

Patchbay is a lightweight, mobile-first service control dashboard for Docker containers, Docker Compose projects, and systemd units. It lets users toggle services on/off, restart them, and activate presets (named configurations that orchestrate stop/start/restart sequences across multiple services). It's designed for homelabs and workstations where GPU-heavy or RAM-heavy services compete for resources.

## Key references

- **Full specification:** `SPEC.md` — the authoritative source for all architecture, API, config, and UI decisions. Read this before making any implementation decisions.
- **Auth spec:** `specs/auth.md` — specification for role-based access control via forward auth.
- **UI mockup:** `patchbay-mockup.html` — visual reference for the dashboard design (dark theme, layout, component styling, color scheme, status indicators, interactions). The mockup is static HTML; the real implementation uses Alpine.js + Jinja2 + Tailwind.

## Tech stack

- **Backend:** Python 3.11+, FastAPI, docker-py, PyYAML, Jinja2, uvicorn
- **Frontend:** Jinja2 server-side templates, Alpine.js (CDN), Tailwind CSS (CDN play script)
- **No JS build step.** No npm, no node_modules, no bundler. Pure Python project.
- **Port:** 4848

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running the dev server

```bash
uvicorn patchbay.main:app --reload --host 0.0.0.0 --port 4848
```

## Running tests

```bash
pytest
```

## Linting

```bash
ruff check .
ruff format .
```

## Project structure

```
patchbay/
├── CLAUDE.md
├── SPEC.md
├── patchbay-mockup.html
├── README.md
├── Dockerfile
├── compose.yml
├── pyproject.toml
├── docs/
│   └── AUTH.md             # Auth configuration and setup guide
├── config/
│   ├── config.example.yml
│   ├── services.example.yml
│   └── presets.example.yml
├── patchbay/
│   ├── __init__.py
│   ├── main.py            # FastAPI app factory, startup, route mounting
│   ├── config.py          # YAML loading, validation, reload logic
│   ├── models.py          # Pydantic models for API request/response schemas
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py        # /api/auth/* endpoints
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
│   ├── auth.py            # Auth context resolution and permission checks
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
    ├── test_auth.py
    ├── test_services.py
    ├── test_presets.py
    └── test_health.py
```

## Architecture rules

1. **All state changes go through the REST API.** The web UI, CLI, and AI agents all use the same `/api/*` endpoints. No shortcuts.
1. **Service and preset names are slug-matched in URLs.** `slugify()` in `config.py` lowercases and replaces spaces with hyphens. "Open WebUI" matches `/api/services/open-webui`. Config uniqueness checks also use slugs.
2. **The web UI is server-rendered on first load** (Jinja2), then **Alpine.js handles all interactivity** (toggles, preset activation, polling). The UI calls the JSON API via `fetch()`.
3. **Config is split into three YAML files:** `config.yml` (global settings), `services.yml` (service definitions), `presets.yml` (preset definitions). See SPEC.md Section 5 for schemas and examples.
4. **Services have a `type` field:** `"docker"`, `"compose"`, or `"systemd"`. The backend dispatches to the appropriate handler based on type.
5. **Presets execute actions sequentially** in the order listed. Each action waits for confirmation before proceeding. If any action fails, subsequent actions are not executed.
6. **Tailwind CSS and Alpine.js are loaded from CDN.** No local copies, no build step. Use the Tailwind CDN play script (`<script src="https://cdn.tailwindcss.com">`).

## Implementation status

The MVP (v0.1) is complete plus RBAC. All phases are implemented and tested (135 tests).

### What's built
- Config loading and validation with hot-reload (`POST /api/config/reload`)
- Docker, Compose, and systemd backends with error handling and sudo support
- Full REST API: services, presets, system/health endpoints
- Background health check runner (HTTP checks, Docker HEALTHCHECK, caching)
- Preset activation engine with sequential execution and failure tracking
- Web UI: Jinja2 + Alpine.js + Tailwind CDN with polling, optimistic updates, error toasts
- Mobile-responsive layout, dark theme matching mockup
- Dockerfile and compose.yml
- Role-based access control via forward auth headers (see `specs/auth.md`, `docs/AUTH.md`)

### What's NOT built yet (v0.2+)
- CLI tool (`cli/` directory does not exist)
- API key authentication (separate from RBAC -- see SPEC.md Section 10.2)
- Preset activation progress display (per-action status updates in UI)
- WebSocket support, multi-host, GPU metrics

## Key implementation details

### Config loading (`config.py`)
- Read `CONFIG_DIR` env var (default `/config`)
- Load and validate all three files on startup
- Expose a `reload()` function that re-reads from disk and swaps the config atomically
- If any file fails validation on reload, keep the old config and return the error

### Docker backend (`backends/docker.py`)
- Initialize a `docker.DockerClient.from_env()` on startup
- `get_state()`: Call `client.containers.get(target)` and read `.status`. Also read `.attrs['State']['Health']['Status']` if available for Docker HEALTHCHECK.
- `start()`, `stop()`, `restart()`: Call the corresponding container methods. Catch `docker.errors.NotFound` and `docker.errors.APIError`.
- Return uptime by computing the delta from `.attrs['State']['StartedAt']`.

### Compose backend (`backends/compose.py`)
- Uses `docker compose` CLI via `subprocess.run()` with `cwd=target` (the project directory).
- `get_state()`: Runs `docker compose ps --format json -a`, parses NDJSON, aggregates: all running = `"running"`, all stopped/exited/created = `"stopped"`, mixed = `"partial"`.
- `start()`: Runs `docker compose up -d` (creates containers if needed).
- `stop()`, `restart()`: Runs the corresponding `docker compose` command.
- `get_health_info()`: Returns `None` (compose-level health uses HTTP checks in config).
- `get_uptime()`: Inspects running containers, returns uptime from the earliest `StartedAt`.
- Checks `docker compose version` on init to set `self.available`.

### Systemd backend (`backends/systemd.py`)
- `get_state()`: Run `systemctl is-active {target}` and parse output.
- `start()`, `stop()`, `restart()`: Run `systemctl {action} {target}`.
- All subprocess calls should use `subprocess.run(..., capture_output=True, text=True, timeout=30)`.
- Return uptime by parsing `systemctl show -p ActiveEnterTimestamp {target}`.

### Health checks (`health.py`)
- Run HTTP health checks in a background `asyncio` task.
- Use `httpx.AsyncClient` with configured timeout.
- Store results in a dict keyed by service name.
- Check interval is per-service (from `health_check.interval` in services.yml, default 30s).
- Resolution logic (see SPEC.md Section 9.4): HTTP check > Docker HEALTHCHECK > assume healthy if running > `partial` state defaults to unhealthy.

### Preset execution (`presets.py`)
- Accept a preset name, look up its actions.
- Execute each action sequentially using `await`.
- Record result of each action (service name, action type, success/error, duration).
- On failure, stop execution and return partial results with `failed_at` index.
- The web UI should disable all controls during preset execution.

### Alpine.js integration (`templates/index.html`)
- Render initial service and preset data into a `<script>` tag as JSON, consumed by Alpine's `x-data`.
- Alpine polls `GET /api/services` on an interval (from config's `poll_interval`).
- Toggle clicks send `POST /api/services/{name}/start` or `/stop` via `fetch()`, update local state optimistically, revert on error.
- Preset activation sends `POST /api/presets/{name}/activate`, disables controls during execution, updates all affected services on completion.
- Pause polling during any active operation to avoid state conflicts.

### Mobile responsiveness
- All touch targets must be at least 44px.
- Service rows should reflow on narrow screens (controls below info).
- Preset buttons wrap naturally.
- Test at 320px, 375px, 414px viewport widths.
- No horizontal scrolling.

## Out of scope

- No WebSocket support -- polling is sufficient
- No API key authentication -- that's v0.2
- No CLI tool -- that's v0.2
- No preset scheduling or cron
- No multi-host support
- No GPU/VRAM metrics
- No audit logging
