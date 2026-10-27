from pathlib import Path
from uuid import uuid7

from fastapi.testclient import TestClient

from moretztrichter.main import create_app
from moretztrichter.settings import Settings


class FakeDatabase:
    def __init__(self, ping_fails: bool = False) -> None:
        self.received = []
        self.ping_fails = ping_fails

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def ensure_schema_ready(self) -> None:
        pass

    async def ping(self) -> None:
        if self.ping_fails:
            raise RuntimeError("database unavailable")

    async def ingest(self, batch: object) -> tuple[bool, int, int]:
        self.received.append(batch)
        return False, 1, 0


def request_body() -> dict[str, object]:
    return {
        "batch_id": str(uuid7()),
        "device": {"identifier": "device-1"},
        "channels": [{"name": "temperature", "samples": [["2026-01-01T00:00:00Z", 20.0]]}],
    }


def test_ingest_requires_token_and_ping_checks_database(tmp_path: Path) -> None:
    database = FakeDatabase()
    settings = Settings("postgresql://unused", "test-token", tmp_path / "token", 1_000_000)
    with TestClient(create_app(settings, database)) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200
        assert client.post("/api/v1/ingest", json=request_body()).status_code == 401
        assert (
            client.get("/api/v1/ping", headers={"Authorization": "Bearer test-token"}).status_code
            == 200
        )
        response = client.post(
            "/api/v1/ingest", json=request_body(), headers={"Authorization": "Bearer test-token"}
        )
    assert response.status_code == 201
    assert len(response.headers["X-Request-ID"]) == 32
    assert response.json()["inserted"] == 1
    assert len(database.received) == 1


def test_readyz_reports_database_failure(tmp_path: Path) -> None:
    settings = Settings("postgresql://unused", "test-token", tmp_path / "token", 1_000_000)
    with TestClient(create_app(settings, FakeDatabase(ping_fails=True))) as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    assert len(response.headers["X-Request-ID"]) == 32


def test_ingest_requires_json_content_type(tmp_path: Path) -> None:
    settings = Settings("postgresql://unused", "test-token", tmp_path / "token", 1_000_000)
    with TestClient(create_app(settings, FakeDatabase())) as client:
        response = client.post(
            "/api/v1/ingest",
            content="not json",
            headers={"Authorization": "Bearer test-token", "Content-Type": "text/plain"},
        )
    assert response.status_code == 415
    assert len(response.headers["X-Request-ID"]) == 32
