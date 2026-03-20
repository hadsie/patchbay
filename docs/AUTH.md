# Authentication

## Overview

Patchbay supports role-based access control (RBAC) via forward authentication headers set by an upstream reverse proxy. Patchbay does not handle login, sessions, or tokens -- your identity provider does that. Patchbay reads the identity headers your proxy forwards and makes authorization decisions locally.

When `auth.enabled` is `false` (the default), the entire auth system is skipped and Patchbay behaves as if no restrictions exist.

## Supported providers

Any reverse proxy that sets user/group headers works. Common providers:

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

Everyone sees all services. Only admins can start/stop/restart. Unauthenticated requests get a 401.

## Authentik setup guide

1. **Create groups** in Authentik: `patchbay-admins`, `patchbay-users`. Assign users to the appropriate groups.

2. **Create an application** in Authentik for Patchbay.

3. **Create a proxy provider** with forward auth (single application mode). Set the external host to your Patchbay URL.

4. **Configure Traefik middleware** (or your reverse proxy) to use Authentik's forward auth endpoint:

   ```yaml
   # Traefik dynamic config
   http:
     middlewares:
       authentik:
         forwardAuth:
           address: "http://authentik:9000/outpost.goauthentik.io/auth/traefik"
           trustForwardHeader: true
           authResponseHeaders:
             - X-authentik-username
             - X-authentik-groups
   ```

5. **Configure Patchbay**:

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

For each resource and permission type (view or control):

1. Use the resource's own `auth.<type>` if present, otherwise use the global default.
2. If the user has **any** role in `deny`: **denied**.
3. If `allow` contains `"*"`: **allowed**.
4. If the user has **any** role in `allow`: **allowed**.
5. Otherwise: **denied**.

Deny always wins. Roles are additive -- a user in multiple groups gets the union of all matching roles.

### Examples

- `allow: ["*"], deny: ["guest"]` -- everyone except guests
- `allow: ["admin"], deny: []` -- admins only
- `allow: ["admin", "media"], deny: []` -- admins and media role

## Preset delegation

When a user activates a preset, Patchbay only checks the **preset's** control permission. The user does **not** need control permission on each individual service in the preset.

This is intentional: an admin authors a preset and assigns it to a role, granting that role permission to execute the bundled operations without requiring broad service-level control. In the UI, a user may see a service they cannot toggle directly, but can still activate a preset that starts/stops it.

## Debugging

### `/api/auth/me` endpoint

Returns the current user's resolved identity:

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

If auth is not working as expected, check that identity headers are reaching Patchbay. Common issues:

- Proxy not forwarding headers (check `authResponseHeaders` in Traefik, or equivalent in your proxy)
- Header name mismatch between provider and `config.yml`
- Group separator mismatch (Authentik uses `|`, Authelia uses `,`)

## Limitations

- **Header trust:** Patchbay trusts identity headers unconditionally. This is only safe when the reverse proxy is the sole entry point. If Patchbay is exposed directly, anyone can forge headers. Keep `auth.enabled: false` when running without a proxy.
- **No per-action permissions:** You cannot allow "start" but deny "stop" for a given role. This could be added later if needed.
- **Page refresh after config reload:** If you change auth settings via `POST /api/config/reload`, the API immediately uses the new permissions. However, the dashboard HTML structure is fixed until the next page load. Users should refresh after auth config changes.
- **No audit logging:** Auth decisions are not logged. This is planned for a future release.
