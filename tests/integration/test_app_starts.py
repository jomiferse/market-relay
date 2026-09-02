"""The service starts and responds with no external credentials (tasks.md 1.2)."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from market_relay.api.app import create_app


def test_health_check_without_external_credentials(monkeypatch) -> None:
    for key in list(os.environ):
        if "API_KEY" in key or "SECRET" in key or "TOKEN" in key:
            monkeypatch.delenv(key, raising=False)

    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "market-relay"
