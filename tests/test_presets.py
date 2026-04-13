from __future__ import annotations

from patchbay.backends.base import ServiceActionError


class TestListPresets:
    def test_returns_all_presets(self, test_client):
        resp = test_client.get("/api/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test Preset"

    def test_preset_has_actions(self, test_client):
        resp = test_client.get("/api/presets")
        preset = resp.json()[0]
        assert len(preset["actions"]) == 1
        assert preset["actions"][0]["service"] == "test-svc"
        assert preset["actions"][0]["action"] == "restart"


class TestGetPreset:
    def test_returns_single_preset(self, test_client):
        resp = test_client.get("/api/presets/Test Preset")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Preset"

    def test_slug_lookup_converts_spaces_to_hyphens(self, test_client):
        resp = test_client.get("/api/presets/test-preset")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Preset"

    def test_404_for_unknown(self, test_client):
        resp = test_client.get("/api/presets/Nonexistent")
        assert resp.status_code == 404
        assert resp.json()["code"] == "PRESET_NOT_FOUND"


class TestActivatePreset:
    def test_activation_succeeds(self, test_client, mock_docker_backend):
        resp = test_client.post("/api/presets/Test Preset/activate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["preset"] == "Test Preset"
        assert len(data["actions"]) == 1
        assert data["actions"][0]["result"] == "success"

    def test_activation_records_failure(self, test_client, mock_docker_backend):
        mock_docker_backend.restart.side_effect = ServiceActionError("Exploded")
        resp = test_client.post("/api/presets/Test Preset/activate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["failed_at"] == 0
        assert data["actions"][0]["result"] == "error"
        assert "Exploded" in data["actions"][0]["error"]

    def test_activate_by_slug(self, test_client, mock_docker_backend):
        resp = test_client.post("/api/presets/test-preset/activate")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_activate_unknown_preset_returns_404(self, test_client):
        resp = test_client.post("/api/presets/Ghost/activate")
        assert resp.status_code == 404
