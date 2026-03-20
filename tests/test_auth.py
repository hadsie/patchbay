from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from patchbay.auth import AuthContext, can_control, can_view, check_permission, resolve_user
from patchbay.config import (
    AuthConfig,
    PermissionRule,
    PresetActionConfig,
    PresetConfig,
    ResourceAuth,
    RoleConfig,
    ServiceConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_auth_config(**overrides) -> AuthConfig:
    defaults = {
        "enabled": True,
        "user_header": "X-Forwarded-User",
        "groups_header": "X-Forwarded-Groups",
        "group_separator": "|",
        "roles": {
            "admin": RoleConfig(groups=["patchbay-admins"]),
            "viewer": RoleConfig(groups=["patchbay-users"]),
        },
        "view": PermissionRule(),
        "control": PermissionRule(allow=["admin"], deny=[]),
        "unauthenticated": "deny",
    }
    defaults.update(overrides)
    return AuthConfig(**defaults)


class _FakeRequest:
    """Minimal request stub for resolve_user tests."""

    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}


def _make_service(name: str = "svc", auth: ResourceAuth | None = None) -> ServiceConfig:
    return ServiceConfig(name=name, type="docker", target="c", auth=auth)


def _make_preset(name: str = "preset", auth: ResourceAuth | None = None) -> PresetConfig:
    return PresetConfig(
        name=name,
        actions=[PresetActionConfig(service="svc", action="start")],
        auth=auth,
    )


# ---------------------------------------------------------------------------
# Unit tests: resolve_user
# ---------------------------------------------------------------------------


class TestResolveUser:
    def test_auth_disabled_returns_wildcard(self):
        cfg = AuthConfig(enabled=False)
        ctx = resolve_user(_FakeRequest(), cfg)
        assert ctx.roles == {"*"}
        assert ctx.username is None
        assert ctx.authenticated is False

    def test_reads_headers_and_maps_groups(self):
        cfg = _make_auth_config()
        req = _FakeRequest(
            {
                "X-Forwarded-User": "alice",
                "X-Forwarded-Groups": "patchbay-admins",
            }
        )
        ctx = resolve_user(req, cfg)
        assert ctx.username == "alice"
        assert ctx.roles == {"admin"}
        assert ctx.authenticated is True

    def test_multiple_groups_map_to_multiple_roles(self):
        cfg = _make_auth_config()
        req = _FakeRequest(
            {
                "X-Forwarded-User": "bob",
                "X-Forwarded-Groups": "patchbay-admins|patchbay-users",
            }
        )
        ctx = resolve_user(req, cfg)
        assert ctx.roles == {"admin", "viewer"}

    def test_unrecognized_groups_yield_empty_roles(self):
        cfg = _make_auth_config()
        req = _FakeRequest(
            {
                "X-Forwarded-User": "charlie",
                "X-Forwarded-Groups": "some-other-group",
            }
        )
        ctx = resolve_user(req, cfg)
        assert ctx.roles == set()
        assert ctx.authenticated is True

    def test_raises_401_when_unauthenticated_deny(self):
        cfg = _make_auth_config(unauthenticated="deny")
        with pytest.raises(HTTPException) as exc_info:
            resolve_user(_FakeRequest(), cfg)
        assert exc_info.value.status_code == 401

    def test_returns_fallback_role_when_unauthenticated(self):
        cfg = _make_auth_config(unauthenticated="viewer")
        ctx = resolve_user(_FakeRequest(), cfg)
        assert ctx.roles == {"viewer"}
        assert ctx.username is None
        assert ctx.authenticated is False

    def test_custom_group_separator(self):
        cfg = _make_auth_config(group_separator=",")
        req = _FakeRequest(
            {
                "X-Forwarded-User": "dave",
                "X-Forwarded-Groups": "patchbay-admins,patchbay-users",
            }
        )
        ctx = resolve_user(req, cfg)
        assert ctx.roles == {"admin", "viewer"}

    def test_username_only_no_groups(self):
        cfg = _make_auth_config()
        req = _FakeRequest({"X-Forwarded-User": "eve"})
        ctx = resolve_user(req, cfg)
        assert ctx.username == "eve"
        assert ctx.roles == set()
        assert ctx.authenticated is True


# ---------------------------------------------------------------------------
# Unit tests: check_permission
# ---------------------------------------------------------------------------


class TestCheckPermission:
    def test_auth_disabled_bypass(self):
        ctx = AuthContext(username=None, roles={"*"}, authenticated=False)
        assert check_permission(ctx, PermissionRule(allow=["admin"], deny=[])) is True

    def test_role_in_allow(self):
        ctx = AuthContext(username="a", roles={"admin"}, authenticated=True)
        assert check_permission(ctx, PermissionRule(allow=["admin"], deny=[])) is True

    def test_role_in_deny(self):
        ctx = AuthContext(username="a", roles={"guest"}, authenticated=True)
        assert check_permission(ctx, PermissionRule(allow=["*"], deny=["guest"])) is False

    def test_deny_overrides_allow(self):
        ctx = AuthContext(username="a", roles={"admin"}, authenticated=True)
        assert check_permission(ctx, PermissionRule(allow=["admin"], deny=["admin"])) is False

    def test_wildcard_allow(self):
        ctx = AuthContext(username="a", roles={"viewer"}, authenticated=True)
        assert check_permission(ctx, PermissionRule(allow=["*"], deny=[])) is True

    def test_wildcard_denied_by_deny(self):
        ctx = AuthContext(username="a", roles={"guest"}, authenticated=True)
        assert check_permission(ctx, PermissionRule(allow=["*"], deny=["guest"])) is False

    def test_empty_roles_denied(self):
        ctx = AuthContext(username="a", roles=set(), authenticated=True)
        assert check_permission(ctx, PermissionRule(allow=["admin"], deny=[])) is False

    def test_empty_roles_allowed_by_wildcard(self):
        ctx = AuthContext(username="a", roles=set(), authenticated=True)
        assert check_permission(ctx, PermissionRule(allow=["*"], deny=[])) is True


# ---------------------------------------------------------------------------
# Unit tests: can_view / can_control
# ---------------------------------------------------------------------------


class TestCanView:
    def test_uses_resource_override(self):
        cfg = _make_auth_config()
        svc = _make_service(auth=ResourceAuth(view=PermissionRule(allow=["admin"])))
        ctx = AuthContext(username="a", roles={"viewer"}, authenticated=True)
        assert can_view(ctx, svc, cfg) is False

    def test_falls_back_to_default(self):
        cfg = _make_auth_config()
        svc = _make_service()
        ctx = AuthContext(username="a", roles={"viewer"}, authenticated=True)
        # Default view is allow: ["*"]
        assert can_view(ctx, svc, cfg) is True


class TestCanControl:
    def test_uses_resource_override(self):
        cfg = _make_auth_config()
        svc = _make_service(auth=ResourceAuth(control=PermissionRule(allow=["viewer"])))
        ctx = AuthContext(username="a", roles={"viewer"}, authenticated=True)
        assert can_control(ctx, svc, cfg) is True

    def test_falls_back_to_default(self):
        cfg = _make_auth_config()
        svc = _make_service()
        ctx = AuthContext(username="a", roles={"viewer"}, authenticated=True)
        # Default control is allow: ["admin"]
        assert can_control(ctx, svc, cfg) is False

    def test_partial_override_falls_back(self):
        """Resource overrides view but not control -- control uses default."""
        cfg = _make_auth_config()
        svc = _make_service(auth=ResourceAuth(view=PermissionRule(allow=["admin"])))
        ctx = AuthContext(username="a", roles={"viewer"}, authenticated=True)
        assert can_control(ctx, svc, cfg) is False

    def test_preset_can_view_and_control(self):
        cfg = _make_auth_config()
        preset = _make_preset(auth=ResourceAuth(control=PermissionRule(allow=["viewer"])))
        ctx = AuthContext(username="a", roles={"viewer"}, authenticated=True)
        assert can_view(ctx, preset, cfg) is True
        assert can_control(ctx, preset, cfg) is True


# ---------------------------------------------------------------------------
# Integration tests: auth disabled
# ---------------------------------------------------------------------------


class TestAuthDisabled:
    def test_services_returned_unchanged(self, test_client: TestClient):
        resp = test_client.get("/api/services")
        assert resp.status_code == 200
        names = {s["name"] for s in resp.json()}
        assert "test-svc" in names

    def test_auth_me_returns_unauthenticated(self, test_client: TestClient):
        resp = test_client.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] is None
        assert "*" in data["roles"]
        assert data["authenticated"] is False

    def test_can_control_defaults_true(self, test_client: TestClient):
        resp = test_client.get("/api/services")
        for svc in resp.json():
            assert svc["can_control"] is True

    def test_presets_can_control_defaults_true(self, test_client: TestClient):
        resp = test_client.get("/api/presets")
        for p in resp.json():
            assert p["can_control"] is True


# ---------------------------------------------------------------------------
# Integration tests: auth filtering
# ---------------------------------------------------------------------------


class TestAuthFiltering:
    def test_admin_sees_all_services(self, auth_test_client: TestClient):
        resp = auth_test_client.get(
            "/api/services",
            headers={"X-Forwarded-User": "alice", "X-Forwarded-Groups": "patchbay-admins"},
        )
        assert resp.status_code == 200
        names = {s["name"] for s in resp.json()}
        assert names == {"public-svc", "admin-only-svc", "viewer-control-svc"}

    def test_viewer_sees_only_visible_services(self, auth_test_client: TestClient):
        resp = auth_test_client.get(
            "/api/services",
            headers={"X-Forwarded-User": "bob", "X-Forwarded-Groups": "patchbay-users"},
        )
        names = {s["name"] for s in resp.json()}
        assert "admin-only-svc" not in names
        assert "public-svc" in names

    def test_viewer_can_control_set_correctly(self, auth_test_client: TestClient):
        resp = auth_test_client.get(
            "/api/services",
            headers={"X-Forwarded-User": "bob", "X-Forwarded-Groups": "patchbay-users"},
        )
        by_name = {s["name"]: s for s in resp.json()}
        assert by_name["public-svc"]["can_control"] is False
        assert by_name["viewer-control-svc"]["can_control"] is True

    def test_hidden_service_returns_404(self, auth_test_client: TestClient):
        resp = auth_test_client.get(
            "/api/services/admin-only-svc",
            headers={"X-Forwarded-User": "bob", "X-Forwarded-Groups": "patchbay-users"},
        )
        assert resp.status_code == 404

    def test_admin_sees_all_presets(self, auth_test_client: TestClient):
        resp = auth_test_client.get(
            "/api/presets",
            headers={"X-Forwarded-User": "alice", "X-Forwarded-Groups": "patchbay-admins"},
        )
        names = {p["name"] for p in resp.json()}
        assert names == {"Public Preset", "Admin Preset"}

    def test_viewer_presets_filtered(self, auth_test_client: TestClient):
        resp = auth_test_client.get(
            "/api/presets",
            headers={"X-Forwarded-User": "bob", "X-Forwarded-Groups": "patchbay-users"},
        )
        names = {p["name"] for p in resp.json()}
        assert "Admin Preset" not in names
        assert "Public Preset" in names

    def test_hidden_preset_returns_404(self, auth_test_client: TestClient):
        resp = auth_test_client.get(
            "/api/presets/Admin Preset",
            headers={"X-Forwarded-User": "bob", "X-Forwarded-Groups": "patchbay-users"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Integration tests: auth gating
# ---------------------------------------------------------------------------


class TestAuthGating:
    def test_viewer_cannot_start_service(self, auth_test_client: TestClient):
        resp = auth_test_client.post(
            "/api/services/public-svc/start",
            headers={"X-Forwarded-User": "bob", "X-Forwarded-Groups": "patchbay-users"},
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == "FORBIDDEN"

    def test_viewer_cannot_stop_service(self, auth_test_client: TestClient):
        resp = auth_test_client.post(
            "/api/services/public-svc/stop",
            headers={"X-Forwarded-User": "bob", "X-Forwarded-Groups": "patchbay-users"},
        )
        assert resp.status_code == 403

    def test_viewer_cannot_restart_service(self, auth_test_client: TestClient):
        resp = auth_test_client.post(
            "/api/services/public-svc/restart",
            headers={"X-Forwarded-User": "bob", "X-Forwarded-Groups": "patchbay-users"},
        )
        assert resp.status_code == 403

    def test_admin_can_control_service(self, auth_test_client: TestClient):
        resp = auth_test_client.post(
            "/api/services/public-svc/restart",
            headers={"X-Forwarded-User": "alice", "X-Forwarded-Groups": "patchbay-admins"},
        )
        assert resp.status_code == 200

    def test_hidden_service_action_returns_404(self, auth_test_client: TestClient):
        resp = auth_test_client.post(
            "/api/services/admin-only-svc/start",
            headers={"X-Forwarded-User": "bob", "X-Forwarded-Groups": "patchbay-users"},
        )
        assert resp.status_code == 404

    def test_viewer_can_control_overridden_service(self, auth_test_client: TestClient):
        resp = auth_test_client.post(
            "/api/services/viewer-control-svc/restart",
            headers={"X-Forwarded-User": "bob", "X-Forwarded-Groups": "patchbay-users"},
        )
        assert resp.status_code == 200

    def test_viewer_cannot_activate_preset(self, auth_test_client: TestClient):
        resp = auth_test_client.post(
            "/api/presets/Public Preset/activate",
            headers={"X-Forwarded-User": "bob", "X-Forwarded-Groups": "patchbay-users"},
        )
        assert resp.status_code == 403

    def test_admin_can_activate_preset(self, auth_test_client: TestClient):
        resp = auth_test_client.post(
            "/api/presets/Public Preset/activate",
            headers={"X-Forwarded-User": "alice", "X-Forwarded-Groups": "patchbay-admins"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Integration tests: /api/auth/me
# ---------------------------------------------------------------------------


class TestAuthMe:
    def test_returns_identity_and_roles(self, auth_test_client: TestClient):
        resp = auth_test_client.get(
            "/api/auth/me",
            headers={"X-Forwarded-User": "alice", "X-Forwarded-Groups": "patchbay-admins"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "alice"
        assert "admin" in data["roles"]
        assert data["authenticated"] is True

    def test_returns_multiple_roles(self, auth_test_client: TestClient):
        resp = auth_test_client.get(
            "/api/auth/me",
            headers={
                "X-Forwarded-User": "bob",
                "X-Forwarded-Groups": "patchbay-admins|patchbay-users",
            },
        )
        data = resp.json()
        assert set(data["roles"]) == {"admin", "viewer"}


# ---------------------------------------------------------------------------
# Integration tests: unauthenticated
# ---------------------------------------------------------------------------


class TestAuthUnauthenticated:
    def test_returns_401_when_deny(self, auth_test_client: TestClient):
        resp = auth_test_client.get("/api/services")
        assert resp.status_code == 401

    def test_dashboard_returns_401_html(self, auth_test_client: TestClient):
        resp = auth_test_client.get("/")
        assert resp.status_code == 401
        assert "log in" in resp.text.lower()
