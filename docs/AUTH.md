# Authentication

## Overview

Patchbay doesn't do login or sessions. Your reverse proxy handles authentication and forwards identity headers; Patchbay reads those headers and enforces permissions locally.

When `auth.enabled` is `false` (the default), auth is skipped entirely and everything is unrestricted.

## Supported providers

Anything that sets user/group headers works. Some common ones:

| Provider | User header | Groups header |
|----------|------------|---------------|
| Authentik | `X-authentik-username` | `X-authentik-groups` |
| Authelia | `Remote-User` | `Remote-Groups` |
| OAuth2 Proxy | `X-Forwarded-User` | `X-Forwarded-Groups` |
| Keycloak (Gatekeeper) | `X-Forwarded-User` | `X-Forwarded-Groups` |
| Caddy Security | `X-Caddy-User` | `X-Caddy-Roles` |

Configure `user_header` and `groups_header` in `config.yml` to match your provider.

## Quick start

Minimal two-role setup (admin + viewer):

```yaml
# config.yml
auth:
  enabled: true
  user_header: "Remote-User"
  groups_header: "Remote-Groups"
  group_separator: ","
  roles:
    admin:
      groups: ["patchbay-admins"]
    viewer:
      groups: ["patchbay-users"]
  view:
    allow: ["*"]
  control:
    allow: ["admin"]
  unauthenticated: deny
```

Everyone can see services. Only admins can start/stop/restart. Unauthenticated requests get 401'd.

## Authentik setup guide

1. **Create groups** in Authentik: `patchbay-admins`, `patchbay-users`. Assign users to the appropriate groups.

2. **Create an application** in Authentik for Patchbay.

3. **Create a proxy provider** with forward auth (single application mode). Set the external host to your Patchbay URL.

4. **Define the Authentik middleware.** If you use Traefik dynamic config files, define it there. If you run Traefik via Docker Compose (more common), define it as labels on the Authentik outpost container:

   ```yaml
   # On the authentik-outpost service in your compose.yml
   labels:
     - traefik.enable=true
     - traefik.http.middlewares.authentik-auth.forwardAuth.address=http://authentik-outpost:9000/outpost.goauthentik.io/auth/traefik
     - traefik.http.middlewares.authentik-auth.forwardAuth.trustForwardHeader=true
     - traefik.http.middlewares.authentik-auth.forwardAuth.authResponseHeaders=X-authentik-username,X-authentik-groups
   ```

5. **Apply the middleware to Patchbay** via labels on the Patchbay service in your compose.yml:

   ```yaml
   # On the patchbay service
   labels:
     - traefik.enable=true
     - traefik.http.services.patchbay.loadbalancer.server.port=4848
     - traefik.http.routers.patchbay.rule=Host(`patchbay.example.com`)
     - traefik.http.routers.patchbay.entrypoints=websecure
     - traefik.http.routers.patchbay.tls=true
     - traefik.http.routers.patchbay.middlewares=authentik-auth
   ```

6. **Configure Patchbay**:

   ```yaml
   auth:
     enabled: true
     user_header: "X-authentik-username"
     groups_header: "X-authentik-groups"
     group_separator: "|"
     roles:
       admin:
         groups: ["patchbay-admins"]
       viewer:
         groups: ["patchbay-users"]
     view:
       allow: ["*"]
     control:
       allow: ["admin"]
     unauthenticated: deny
   ```

## Configuration reference

### `config.yml` auth section

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Master switch for auth |
| `user_header` | string | `X-Forwarded-User` | Header containing the username |
| `groups_header` | string | `X-Forwarded-Groups` | Header containing group memberships |
| `group_separator` | string | `\|` | Delimiter between group names |
| `roles` | dict | `{}` | Map of role name to `{groups: [...]}` |
| `view` | object | `{allow: ["*"], deny: []}` | Default view permissions |
| `control` | object | `{allow: ["admin"], deny: []}` | Default control permissions |
| `unauthenticated` | string | `deny` | `"deny"` for 401, or a role name |

### Per-service auth (`services.yml`)

```yaml
services:
  - name: traefik
    type: docker
    target: traefik
    auth:
      view:
        deny: ["guest"]
      control:
        allow: ["admin"]
```

Fields not specified fall back to the global defaults.

### Per-preset auth (`presets.yml`)

```yaml
presets:
  - name: Media Night
    auth:
      control:
        allow: ["admin", "media"]
    actions:
      - service: plex
        action: start
```

## Permission resolution

For each resource (service or preset) and permission type (view or control):

1. Use the resource's own `auth.<type>` if set, otherwise fall back to the global default.
2. User has any role in `deny`? Denied.
3. `allow` contains `"*"`? Allowed.
4. User has any role in `allow`? Allowed.
5. Otherwise: denied.

Deny always wins. A user in multiple groups gets the union of all matching roles.

### Examples

- `allow: ["*"], deny: ["guest"]` -- everyone except guests
- `allow: ["admin"], deny: []` -- admins only
- `allow: ["admin", "media"], deny: []` -- admins and media role

## Preset delegation

Activating a preset only checks the **preset's** control permission, not each individual service in it.

This is by design: an admin creates a preset and assigns it to a role. Users with that role can run the preset even if they can't toggle those services individually.

## Debugging

### `/api/auth/me` endpoint

Shows who Patchbay thinks you are:

```bash
curl -H "X-Forwarded-User: alice" -H "X-Forwarded-Groups: patchbay-admins" \
  http://localhost:4848/api/auth/me
```

```json
{"username": "alice", "roles": ["admin"], "authenticated": true}
```

When auth is disabled:

```json
{"username": null, "roles": ["*"], "authenticated": false}
```

### Verifying headers

If auth isn't working, check that headers are actually reaching Patchbay. Common issues:

- Proxy not forwarding headers (check `authResponseHeaders` in Traefik, or equivalent in your proxy)
- Header name mismatch between provider and `config.yml`
- Group separator mismatch (Authentik uses `|`, Authelia uses `,`)

## API key authentication

For programmatic access (CLI, scripts, AI agents) where forward-auth headers are not available, Patchbay supports `Authorization: Bearer <key>` authentication. API keys are static, stored as bcrypt hashes in config, and each key binds to specific roles.

### Generating a key

```bash
patchbay-keygen --label my-key --roles admin
```

Save the plaintext key somewhere safe -- it cannot be recovered from the hash.

### Configuration

API keys live in a separate file, `api_keys.yml`, in the same config directory as `config.yml`. This keeps secrets out of the main config and lets you set stricter file permissions.

```yaml
# api_keys.yml
api_keys:
  - label: "claude-agent"
    key_hash: "$2b$12$..."
    roles: ["admin"]
  - label: "monitoring"
    key_hash: "$2b$12$..."
    roles: ["viewer"]
```

Each key gets a `label` (used as the username in `/api/auth/me`, prefixed with `api:`), a `key_hash` (bcrypt), and a list of `roles` that must be defined in `auth.roles` in `config.yml`.

When `api_keys.yml` is missing or empty, Bearer token checking is disabled entirely (backward compatible).

### Usage

```bash
curl -H "Authorization: Bearer pb_abc123..." http://localhost:4848/api/services
```

### Priority

When a request includes a `Bearer` token and API keys are configured:

1. The token is checked against all configured keys.
2. If it matches, the key's roles are used (identity headers are ignored).
3. If the token is present but invalid, Patchbay returns 401 -- it never falls through to header-based auth with a bad key.
4. If no `Authorization` header is present, normal header-based auth applies.

### Security notes

- Treat API keys like passwords. Do not commit plaintext keys to git.
- Use environment variable injection or secrets management in production.
- API keys bypass forward-auth entirely -- Patchbay validates them at the application layer.

### Traefik dual-router pattern

When using forward-auth (Authentik, Authelia, etc.) with Traefik, API clients sending Bearer tokens will be redirected to the login page by the forward-auth middleware. To avoid this, configure two Traefik routers:

```yaml
# Router 1: Browser traffic with forward-auth
- traefik.http.routers.patchbay-web.rule=Host(`patchbay.example.com`) && !HeaderRegexp(`Authorization`, `^Bearer .+`)
- traefik.http.routers.patchbay-web.middlewares=authentik-auth
- traefik.http.routers.patchbay-web.entrypoints=websecure
- traefik.http.routers.patchbay-web.tls=true

# Router 2: API traffic with Bearer token -- no forward-auth
- traefik.http.routers.patchbay-api.rule=Host(`patchbay.example.com`) && HeaderRegexp(`Authorization`, `^Bearer .+`)
- traefik.http.routers.patchbay-api.entrypoints=websecure
- traefik.http.routers.patchbay-api.tls=true
```

This is optional. If forward-auth is not in the path (e.g., direct access on a LAN), a single router works fine.

## Limitations

- **Header trust:** Patchbay trusts identity headers blindly. This is only safe behind a reverse proxy. If Patchbay is exposed directly, anyone can forge headers.
- **No per-action permissions:** You can't allow "start" but deny "stop" for a role. Could be added later.
- **Page refresh after config reload:** After `POST /api/config/reload`, the API uses new permissions immediately but the dashboard HTML is stale until you refresh the page.
- **No audit logging:** Auth decisions aren't logged yet.
