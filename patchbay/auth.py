from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from patchbay.config import AuthConfig, PermissionRule, PresetConfig, ResourceAuth, ServiceConfig


@dataclass
class AuthContext:
    username: str | None
    roles: set[str]
    authenticated: bool


def resolve_user(request: Request, auth_config: AuthConfig) -> AuthContext:
    """Read identity headers and resolve the user's roles.

    When auth is disabled, returns a wildcard context that passes all checks.
    """
    if not auth_config.enabled:
        return AuthContext(username=None, roles={"*"}, authenticated=False)

    username = request.headers.get(auth_config.user_header)
    groups_raw = request.headers.get(auth_config.groups_header)

    if not username and not groups_raw:
        if auth_config.unauthenticated == "deny":
            raise HTTPException(status_code=401, detail="Authentication required")
        return AuthContext(
            username=None,
            roles={auth_config.unauthenticated},
            authenticated=False,
        )

    roles: set[str] = set()
    if groups_raw:
        groups = {g.strip() for g in groups_raw.split(auth_config.group_separator) if g.strip()}
        for role_name, role_cfg in auth_config.roles.items():
            if groups & set(role_cfg.groups):
                roles.add(role_name)

    return AuthContext(username=username, roles=roles, authenticated=True)


def check_permission(auth_ctx: AuthContext, rule: PermissionRule) -> bool:
    """Evaluate a permission rule against the user's roles.

    Resolution order: auth-disabled bypass, deny wins, wildcard allow,
    specific allow, default deny.
    """
    if "*" in auth_ctx.roles:
        return True
    if auth_ctx.roles & set(rule.deny):
        return False
    if "*" in rule.allow:
        return True
    if auth_ctx.roles & set(rule.allow):
        return True
    return False


def _effective_rule(
    resource_auth: ResourceAuth | None,
    default_rule: PermissionRule,
    permission_type: str,
) -> PermissionRule:
    if resource_auth:
        override = getattr(resource_auth, permission_type)
        if override is not None:
            return override
    return default_rule


def can_view(
    auth_ctx: AuthContext,
    resource: ServiceConfig | PresetConfig,
    auth_config: AuthConfig,
) -> bool:
    rule = _effective_rule(resource.auth, auth_config.view, "view")
    return check_permission(auth_ctx, rule)


def can_control(
    auth_ctx: AuthContext,
    resource: ServiceConfig | PresetConfig,
    auth_config: AuthConfig,
) -> bool:
    rule = _effective_rule(resource.auth, auth_config.control, "control")
    return check_permission(auth_ctx, rule)
