import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.mark.asyncio
async def test_health() -> None:
    app = create_app()
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

