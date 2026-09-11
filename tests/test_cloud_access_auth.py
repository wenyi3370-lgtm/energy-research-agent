from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from energy_research_agent.automation.api.app import create_app
from energy_research_agent.automation.executor import SyntheticKernelExecutor


def _client(tmp_path: Path) -> TestClient:
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'automation.db'}",
        executor=SyntheticKernelExecutor(),
        workdir=tmp_path / "work",
    )
    return TestClient(app)


def test_cloud_password_protects_portal_and_api(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ERA_ACCESS_USERNAME", "demo-user")
    monkeypatch.setenv("ERA_ACCESS_PASSWORD", "strong-test-password")

    with _client(tmp_path) as client:
        assert client.get("/health").status_code == 200

        unauthorized = client.get("/agent")
        assert unauthorized.status_code == 401
        assert unauthorized.headers["www-authenticate"].startswith("Basic")

        assert client.get("/agent", auth=("demo-user", "wrong")).status_code == 401
        assert client.get(
            "/agent", auth=("demo-user", "strong-test-password")
        ).status_code == 200
        assert client.get(
            "/api/v1/intelligence/status",
            auth=("demo-user", "strong-test-password"),
        ).status_code == 200


def test_local_mode_remains_open_without_password(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ERA_ACCESS_PASSWORD", raising=False)

    with _client(tmp_path) as client:
        assert client.get("/agent").status_code == 200
