# Patchbay

A lightweight, mobile-first service control dashboard for Docker containers and systemd units. Toggle services on/off, restart them, and activate presets -- named configurations that orchestrate stop/start/restart sequences across multiple services.

Built for homelabs and workstations where GPU-heavy or RAM-heavy services compete for resources and can't all run simultaneously.

## Features

- Unified dashboard for both Docker containers and systemd units
- One-click presets that orchestrate ordered stop/start/restart sequences
- Mobile-first responsive UI (dark theme, works at 320px+)
- REST API with auto-generated OpenAPI docs at `/docs`
- HTTP health checks, Docker HEALTHCHECK integration, and status polling
- Hot-reload configuration without restarting the server

## Requirements

- Python 3.11+
- Docker (for managing Docker containers)
- systemd (for managing systemd units, Linux only)

## Quick Start

```bash
git clone https://github.com/hadsie/patchbay.git
cd patchbay
python -m venv .venv
source .venv/bin/activate
pip install .
```

Edit the YAML files in `config/`. See the `.example.yml` files for reference:

```bash
cp config/services.example.yml config/services.yml
cp config/presets.example.yml config/presets.yml
$EDITOR config/config.yml config/services.yml config/presets.yml
```

Start the server:

```bash
CONFIG_DIR=./config .venv/bin/patchbay
```

Open the dashboard at http://localhost:4848 and the API docs at http://localhost:4848/docs.

### Updating

```bash
git pull
.venv/bin/pip install .
sudo systemctl restart patchbay  # if running as a service
```

### Configuration reload

Config can also be reloaded without restarting:

```bash
curl -X POST http://localhost:4848/api/config/reload
```

## API

All endpoints return JSON. The web UI uses these same endpoints.

```bash
# List all services with current state and health
curl http://localhost:4848/api/services

# Get a single service
curl http://localhost:4848/api/services/llama-server

# Start / stop / restart
curl -X POST http://localhost:4848/api/services/llama-server/start
curl -X POST http://localhost:4848/api/services/llama-server/stop
curl -X POST http://localhost:4848/api/services/llama-server/restart

# List presets
curl http://localhost:4848/api/presets

# Activate a preset (runs actions sequentially)
curl -X POST http://localhost:4848/api/presets/LLM%20Chat/activate

# Health / config / reload
curl http://localhost:4848/api/health
curl http://localhost:4848/api/config
curl -X POST http://localhost:4848/api/config/reload
```

Full interactive API documentation is available at http://localhost:4848/docs (Swagger UI).

## Health Checking

Patchbay resolves service health using a priority chain:

1. **Stopped/inactive** -- health is `"n/a"`
2. **HTTP health check** configured in `services.yml` -- uses the check result
3. **Docker HEALTHCHECK** defined in the container's Dockerfile/compose -- uses Docker's built-in health status
4. **Running with no check configured** -- assumes `"healthy"`

HTTP health checks run in the background at the configured interval and only target services that are currently running.

## Deployment

### Docker

The included `compose.yml` mounts the Docker socket so Patchbay can manage containers:

```bash
docker compose up -d --build
```

When running in Docker, Patchbay can only manage Docker containers. For systemd unit management, run Patchbay directly on the host.

### Direct install (Docker + systemd)

To manage both Docker containers and systemd units, run directly on the host as a systemd service:

```ini
[Unit]
Description=Patchbay Service Dashboard
After=network.target docker.service

[Service]
Type=simple
Environment=CONFIG_DIR=/opt/patchbay/config
ExecStart=/opt/patchbay/.venv/bin/patchbay
WorkingDirectory=/opt/patchbay
Restart=always
User=patchbay

[Install]
WantedBy=multi-user.target
```

The `patchbay` user needs:
- Membership in the `docker` group (for Docker socket access)
- Sudo or polkit permissions for `systemctl start/stop/restart` on managed units

### Docker socket security

Mounting the Docker socket grants full control over all containers. For hardened deployments, consider using [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy) to whitelist only the API endpoints Patchbay needs (container inspect, start, stop, restart).

## Development

```bash
pip install -e ".[dev]"

# Dev server with auto-reload
CONFIG_DIR=./config uvicorn patchbay.main:app --reload --port 4848

# Tests
pytest

# Lint and format
ruff check .
ruff format .
```
