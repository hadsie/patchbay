from __future__ import annotations

from patchbay.backends.base import ServiceActionError


class TestListServices:
    def test_returns_all_services(self, test_client):
        resp = test_client.get("/api/services")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        names = {s["name"] for s in data}
        assert names == {"test-svc", "test-systemd", "test-compose"}

    def test_service_has_expected_fields(self, test_client):
        resp = test_client.get("/api/services")
        svc = resp.json()[0]
        for field in ("name", "type", "target", "state", "health"):
            assert field in svc


class TestGetService:
    def test_returns_single_service(self, test_client):
        resp = test_client.get("/api/services/test-svc")
        assert resp.status_code == 200
        assert resp.json()["name"] == "test-svc"

    def test_404_for_unknown(self, test_client):
        resp = test_client.get("/api/services/nonexistent")
        assert resp.status_code == 404
        assert resp.json()["code"] == "SERVICE_NOT_FOUND"


class TestServiceActions:
    def test_start_success(self, test_client, mock_docker_backend):
        resp = test_client.post("/api/services/test-svc/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"] == "success"
        assert data["action"] == "start"
        mock_docker_backend.start.assert_awaited_once_with("test-container")

    def test_stop_success(self, test_client, mock_docker_backend):
        resp = test_client.post("/api/services/test-svc/stop")
        assert resp.status_code == 200
        assert resp.json()["result"] == "success"
        mock_docker_backend.stop.assert_awaited_once_with("test-container")

    def test_restart_success(self, test_client, mock_docker_backend):
        resp = test_client.post("/api/services/test-svc/restart")
        assert resp.status_code == 200
        assert resp.json()["result"] == "success"

    def test_action_on_unknown_service_returns_404(self, test_client):
        resp = test_client.post("/api/services/ghost/start")
        assert resp.status_code == 404

    def test_backend_error_returns_error_result(self, test_client, mock_docker_backend):
        mock_docker_backend.start.side_effect = ServiceActionError("Container crashed")
        resp = test_client.post("/api/services/test-svc/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"] == "error"
        assert "Container crashed" in data["error"]

    def test_systemd_service_action(self, test_client, mock_systemd_backend):
        resp = test_client.post("/api/services/test-systemd/restart")
        assert resp.status_code == 200
        assert resp.json()["result"] == "success"
        mock_systemd_backend.restart.assert_awaited_once_with("test.service")
