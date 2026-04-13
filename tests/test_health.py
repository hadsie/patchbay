from __future__ import annotations

from patchbay.config import HealthCheckConfig, ServiceConfig
from patchbay.health import HealthResult, resolve_health


def _make_service(
    name: str = "svc",
    stype: str = "docker",
    target: str = "container",
    health_check: HealthCheckConfig | None = None,
) -> ServiceConfig:
    return ServiceConfig(name=name, type=stype, target=target, health_check=health_check)


class TestResolveHealth:
    def test_stopped_returns_na(self):
        svc = _make_service()
        assert resolve_health(svc, "stopped", None, None) == "n/a"

    def test_error_returns_na(self):
        svc = _make_service()
        assert resolve_health(svc, "error", None, None) == "n/a"

    def test_http_check_result_takes_priority(self):
        hc = HealthCheckConfig(endpoint="http://localhost/health")
        svc = _make_service(health_check=hc)
        result = HealthResult(status="unhealthy", error="500")
        assert resolve_health(svc, "running", result, "healthy") == "unhealthy"

    def test_http_check_healthy(self):
        hc = HealthCheckConfig(endpoint="http://localhost/health")
        svc = _make_service(health_check=hc)
        result = HealthResult(status="healthy")
        assert resolve_health(svc, "running", result, None) == "healthy"

    def test_http_check_pending(self):
        hc = HealthCheckConfig(endpoint="http://localhost/health")
        svc = _make_service(health_check=hc)
        result = HealthResult(status="pending")
        assert resolve_health(svc, "running", result, None) == "pending"

    def test_docker_healthcheck_used_when_no_http_check(self):
        svc = _make_service()
        assert resolve_health(svc, "running", None, "unhealthy") == "unhealthy"

    def test_docker_healthcheck_healthy(self):
        svc = _make_service()
        assert resolve_health(svc, "running", None, "healthy") == "healthy"

    def test_docker_healthcheck_starting(self):
        svc = _make_service()
        assert resolve_health(svc, "running", None, "starting") == "pending"

    def test_running_no_check_assumes_healthy(self):
        svc = _make_service()
        assert resolve_health(svc, "running", None, None) == "healthy"

    def test_systemd_running_no_check_assumes_healthy(self):
        svc = _make_service(stype="systemd", target="test.service")
        assert resolve_health(svc, "running", None, None) == "healthy"

    def test_partial_with_no_check_returns_unhealthy(self):
        svc = _make_service(stype="compose", target="/opt/app")
        assert resolve_health(svc, "partial", None, None) == "unhealthy"

    def test_partial_with_http_check_uses_check_result(self):
        hc = HealthCheckConfig(endpoint="http://localhost/health")
        svc = _make_service(stype="compose", target="/opt/app", health_check=hc)
        result = HealthResult(status="healthy")
        assert resolve_health(svc, "partial", result, None) == "healthy"
