# Spec: Role-Based Access Control via Forward Auth

**Status:** Draft
**Feature:** Authentication and authorization for services and presets
**Scope:** Config schema, middleware, API filtering, UI gating

---

## 1. Problem

Patchbay currently has no concept of user identity or permissions. Anyone who can reach the dashboard can control any service. For a public-facing or multi-user homelab, operators need to:

- Restrict who can start/stop certain services (e.g., only admins touch infrastructure).
- Restrict who can see certain services (e.g., hide business tools from guests).
- Restrict who can activate certain presets.
- Delegate preset activation without granting direct control over every service in the preset.

## 2. Approach

Patchbay does **not** implement authentication itself. Identity is established by an upstream reverse proxy that authenticates the user and forwards identity via HTTP headers. This is the standard pattern for homelab identity providers:

| Provider | User header | Groups header |
|----------|------------|---------------|
| Authentik | `X-authentik-username` | `X-authentik-groups` |
| Authelia | `Remote-User` | `Remote-Groups` |
| OAuth2 Proxy | `X-Forwarded-User` | `X-Forwarded-Groups` |
| Keycloak (Gatekeeper) | `X-Forwarded-User` | `X-Forwarded-Groups` |
| Caddy Security | `X-Caddy-User` | `X-Caddy-Roles` |
| Traefik Forward Auth | `X-Forwarded-User` | *(groups not standard)* |

Patchbay reads these headers, maps groups to roles, and makes authorization decisions locally. The header names are configurable so it works with any provider.

When `auth.enabled` is `false` (the default), the entire auth system is skipped and Patchbay behaves exactly as it does today.

## 3. Configuration

### 3.1 `config.yml` -- Auth section

```yaml
auth:
  enabled: true

  # Header names (configure to match your identity provider)
  user_header: "X-authentik-username"
  groups_header: "X-authentik-groups"
  group_separator: "|"    # character separating group names in the header value

  # Map identity provider groups to Patchbay roles.
  # A user gets all roles whose groups they belong to (additive).
  roles:
    admin:
      groups: ["patchbay-admins"]
    media:
      groups: ["patchbay-media", "media-team"]
    guest:
      groups: ["patchbay-guests"]

  # Default permissions for viewing service/preset status.
  # Applied to any service or preset that does not override with its own auth block.
  view:
    allow: ["*"]
    deny: []

  # Default permissions for controlling services (start/stop/restart)
  # and activating presets. Same override logic as view.
  control:
    allow: ["admin"]
    deny: []

  # What happens when no identity headers are present.
  # "deny" -- reject the request (401).
  # A role name -- treat the user as having that role.
  unauthenticated: deny
```

**Field reference:**

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `enabled` | no | `false` | Master switch. When false, all requests are allowed with no permission checks. |
| `user_header` | no | `X-Forwarded-User` | HTTP header containing the authenticated username. |
| `groups_header` | no | `X-Forwarded-Groups` | HTTP header containing the user's group memberships. |
| `group_separator` | no | `\|` | Delimiter between group names in the groups header value. |
| `roles` | yes (if enabled) | | Map of role names to group lists. |
| `roles.<name>.groups` | yes | | List of identity provider group names that grant this role. |
| `view` | no | `allow: ["*"], deny: []` | Default view permissions for services and presets. |
| `view.allow` | no | `["*"]` | Roles that can see services/presets. `"*"` means all roles. |
| `view.deny` | no | `[]` | Roles explicitly denied view access (overrides allow). |
| `control` | no | `allow: ["admin"], deny: []` | Default control permissions for services and presets. |
| `control.allow` | no | `["admin"]` | Roles that can start/stop/restart services or activate presets. |
| `control.deny` | no | `[]` | Roles explicitly denied control access. |
| `unauthenticated` | no | `deny` | Behavior when identity headers are missing. `"deny"` returns 401. A role name (e.g., `"guest"`) treats the user as having that single role. |

### 3.2 Per-service auth overrides (`services.yml`)

A service can override the defaults with its own `auth` block. Any field not specified falls back to the corresponding default from `config.yml`.

```yaml
services:
  - name: plex
    type: docker
    target: plex
    auth:
      view:
        allow: ["*"]
      control:
        allow: ["admin", "media"]

  - name: traefik
    type: docker
    target: traefik
    auth:
      view:
        deny: ["guest"]
      control:
        allow: ["admin"]
```

### 3.3 Per-preset auth overrides (`presets.yml`)

Presets follow the same pattern.

```yaml
presets:
  - name: Media Stack
    actions:
      - service: plex
        action: start
      - service: sonarr
        action: start
    auth:
      control:
        allow: ["admin", "media"]
```

### 3.4 Permission resolution

For a given request, the user's identity is resolved to a set of roles. Then for each resource (service or preset) and permission type (view or control):

1. Determine the effective `allow` and `deny` lists: use the resource's own `auth.<type>` if present, otherwise use the defaults from `config.yml`.
2. If the user has **any** role that appears in `deny`: **denied**.
3. If `allow` contains `"*"`: **allowed**.
4. If the user has **any** role that appears in `allow`: **allowed**.
5. Otherwise: **denied**.

Deny always wins. A user is checked against all of their roles -- if any role grants access and no role is denied, access is allowed (additive).

### 3.5 Preset activation and service permissions

When a user activates a preset, Patchbay checks:

1. Does the user have `control` permission on the **preset**? If not, 403.
2. If yes, the preset executes. The user does **not** need direct `control` permission on each individual service in the preset.

This is an intentional delegation: an admin authors a preset and assigns it to a role, granting that role permission to execute the bundled operations even if those users cannot control those services individually. This avoids the need to grant broad service-level control just so users can run curated presets.

The UI should make this clear: if a user can see a service but not control it, the toggle and restart button are disabled. But if a preset that touches that service is available to them, the preset button is active.

## 4. Implementation

### 4.1 New file: `patchbay/auth.py`

Contains the authorization logic:

- `resolve_user(request) -> AuthContext`: Reads identity headers from the request. Returns an `AuthContext` containing the username, raw groups, and resolved set of roles. If no headers are present, applies the `unauthenticated` policy.
- `can_view(auth_context, resource) -> bool`: Checks view permission for a service or preset.
- `can_control(auth_context, resource) -> bool`: Checks control permission for a service or preset.

`AuthContext` is a lightweight dataclass:

```python
@dataclass
class AuthContext:
    username: str | None
    roles: set[str]
    authenticated: bool
```

### 4.2 Middleware

A FastAPI dependency (`get_auth_context`) that calls `resolve_user()` and attaches the result to the request. When auth is disabled, it returns a context with `roles={"*"}` so all permission checks pass without special-casing.

If `unauthenticated` is `"deny"` and no identity headers are present, the dependency raises `HTTPException(401)` before the route handler runs.

### 4.3 Config model changes

New Pydantic models in `config.py`:

```python
class PermissionRule(BaseModel):
    allow: list[str] = ["*"]
    deny: list[str] = []

class RoleConfig(BaseModel):
    groups: list[str]

class AuthConfig(BaseModel):
    enabled: bool = False
    user_header: str = "X-Forwarded-User"
    groups_header: str = "X-Forwarded-Groups"
    group_separator: str = "|"
    roles: dict[str, RoleConfig] = {}
    view: PermissionRule = PermissionRule()
    control: PermissionRule = PermissionRule(allow=["admin"], deny=[])
    unauthenticated: str = "deny"
```

`ServiceConfig` and `PresetConfig` gain an optional `auth` field:

```python
class ResourceAuth(BaseModel):
    view: PermissionRule | None = None
    control: PermissionRule | None = None
```

`GlobalConfig` gains an `auth` field:

```python
class GlobalConfig(BaseModel):
    # ... existing fields ...
    auth: AuthConfig = AuthConfig()
```

### 4.4 API changes

**Filtered responses:**

- `GET /api/services`: Only returns services the user can view.
- `GET /api/presets`: Only returns presets the user can view.
- `GET /api/services/{name}`: Returns 404 (not 403) if the user cannot view the service. This avoids leaking the existence of hidden services.

**Gated actions:**

- `POST /api/services/{name}/start|stop|restart`: Returns 403 if the user cannot control the service.
- `POST /api/presets/{name}/activate`: Returns 403 if the user cannot control the preset.

**New endpoint:**

- `GET /api/auth/me`: Returns the current user's identity and resolved roles. Useful for the UI and for debugging auth configuration.

```json
{
  "username": "alice",
  "roles": ["admin", "media"],
  "authenticated": true
}
```

When auth is disabled, returns:

```json
{
  "username": null,
  "roles": ["*"],
  "authenticated": false
}
```

**New error code:** `FORBIDDEN` (HTTP 403).

### 4.5 UI changes

The server-side Jinja2 render and the Alpine.js polling both use the same filtered API responses, so the UI automatically hides resources the user cannot view.

For services the user can view but not control:
- The toggle switch is rendered in a disabled state.
- The restart button is rendered in a disabled state.
- A visual indicator (e.g., lock icon or muted styling) communicates read-only status.

For presets the user can view but not control:
- The preset button is rendered in a disabled state.

The dashboard template should call `GET /api/auth/me` on init to know the user's identity. The username can be displayed in the header if available.

### 4.6 Validation

On config load/reload, validate:

- If `auth.enabled` is `true`, `roles` must define at least one role.
- Every role name referenced in `allow`/`deny` lists (in defaults, services, or presets) must be either `"*"` or a defined role name in `auth.roles`. Log a warning for undefined role references.
- `unauthenticated` must be either `"deny"` or a defined role name.
- `group_separator` must be a non-empty string.

### 4.7 Security considerations

- **Header trust:** Patchbay trusts identity headers unconditionally. This is safe only when the reverse proxy is the sole entry point. If Patchbay is exposed directly (no proxy), anyone can forge headers. The docs should warn about this clearly. When running without a proxy (local dev), `auth.enabled` should be `false`.
- **Hidden services return 404, not 403:** A 403 on `GET /api/services/{name}` reveals that the service exists. Return 404 instead.
- **No header logging:** Do not log the raw header values, as they contain identity information.

## 5. Config examples

### 5.1 Simple two-role setup (admin + viewer)

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

No per-service overrides needed. Everyone sees everything, only admins can control.

### 5.2 Role-per-category with overrides

```yaml
# config.yml
auth:
  enabled: true
  user_header: "X-authentik-username"
  groups_header: "X-authentik-groups"
  group_separator: "|"
  roles:
    admin:
      groups: ["patchbay-admins"]
    media:
      groups: ["patchbay-media"]
    dev:
      groups: ["patchbay-dev"]
    guest:
      groups: ["patchbay-guests"]
  view:
    allow: ["*"]
    deny: []
  control:
    allow: ["admin"]
    deny: []
  unauthenticated: guest
```

```yaml
# services.yml (with per-service overrides)
services:
  - name: plex
    type: docker
    target: plex
    category: Media
    auth:
      control:
        allow: ["admin", "media"]

  - name: sonarr
    type: docker
    target: sonarr
    category: Media
    auth:
      control:
        allow: ["admin", "media"]

  - name: n8n
    type: docker
    target: n8n
    category: Development
    auth:
      view:
        deny: ["guest"]
      control:
        allow: ["admin", "dev"]

  - name: traefik
    type: docker
    target: traefik
    category: Infrastructure
    auth:
      view:
        deny: ["guest"]
```

```yaml
# presets.yml
presets:
  - name: Media Night
    auth:
      control:
        allow: ["admin", "media"]
    actions:
      - service: plex
        action: start
      - service: sonarr
        action: start
```

### 5.3 Auth disabled (default, backwards compatible)

```yaml
# config.yml
auth:
  enabled: false
```

Or simply omit the `auth` section entirely. Patchbay behaves exactly as it does today.

## 6. Edge cases

| Scenario | Behavior |
|----------|----------|
| Auth enabled, no identity headers, `unauthenticated: deny` | 401 on all API requests. Dashboard renders a "not authenticated" message. |
| Auth enabled, no identity headers, `unauthenticated: guest` | User is treated as having the `guest` role. |
| User belongs to groups that map to multiple roles | Roles are additive. User gets the union of all matched roles. |
| User belongs to no recognized groups | User has an empty role set. Only resources with `allow: ["*"]` are accessible. |
| Service has `auth.view` but not `auth.control` | View uses the service override, control falls back to `config.yml` defaults. |
| Preset references services the user cannot view | The preset button is still shown (if the user can view the preset). The user does not see those services in the service list, but can still activate the preset. |
| `allow: ["*"]` and `deny: ["guest"]` | Everyone except guest. Deny takes precedence over the wildcard. |
| Config reload changes auth settings | New permissions take effect immediately on next request. No active sessions to invalidate since there are no sessions. |
| Role referenced in allow/deny but not defined in `auth.roles` | Warning logged on config load. The role is effectively unreachable (no user will ever have it). |

## 7. Acceptance criteria

1. When `auth.enabled` is `false` (or omitted), all behavior is identical to current Patchbay -- no permission checks, no header reading.
2. When `auth.enabled` is `true`, user identity is read from the configured headers.
3. Groups are mapped to roles additively (union of all matching roles).
4. `GET /api/services` and `GET /api/presets` return only resources the user can view.
5. `POST /api/services/{name}/start|stop|restart` returns 403 if the user lacks control permission.
6. `POST /api/presets/{name}/activate` returns 403 if the user lacks control permission on the preset.
7. Preset activation does not require control permission on individual services within the preset.
8. Attempting to view a service/preset the user cannot see returns 404 (not 403).
9. `GET /api/auth/me` returns the current user's username and resolved roles.
10. Per-service and per-preset `auth` blocks override the defaults from `config.yml`.
11. Deny always takes precedence over allow.
12. The `"*"` wildcard in `allow` matches all roles.
13. `unauthenticated: deny` returns 401 when identity headers are missing.
14. `unauthenticated: <role>` assigns that role to unauthenticated users.
15. The UI disables toggle/restart controls for services the user can view but not control.
16. The UI disables preset buttons for presets the user can view but not control.
17. Config validation catches undefined role references and logs warnings.
18. Header names, group separator, and role-to-group mappings are all configurable.

## 8. Out of scope

- Authentication (login pages, sessions, tokens) -- handled by the upstream proxy.
- API key authentication -- separate feature, already specced in SPEC.md Section 10.2.
- Per-action permissions (e.g., allow start but not stop) -- adds complexity for little benefit. If needed, can be added later by extending `PermissionRule`.
- Audit logging -- a future feature that would pair well with auth.
