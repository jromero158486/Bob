import pytest
from fastapi.testclient import TestClient

from backend.app.api.main import create_app
from backend.app.layer3_store.db import make_engine, migrate
from backend.app.layer3_store.repository import ClinicalStore


@pytest.fixture
def store(tmp_path):
    url = f"sqlite:///{tmp_path}/g.db"
    migrate(url)
    return ClinicalStore(make_engine(url))


def test_refuses_to_start_outside_demo_mode(store, monkeypatch):
    monkeypatch.setenv("CLINICAL_DEMO_ONLY", "0")
    with pytest.raises(RuntimeError, match="not implemented"):
        create_app(store, run_migrations=False)


def test_demo_header_and_optional_token(store, monkeypatch):
    monkeypatch.setenv("DEMO_API_TOKEN", "t0k")
    c = TestClient(create_app(store, run_migrations=False))
    h = c.get("/api/health")
    assert h.status_code == 200 and "synthetic-data-only" in h.headers["x-clinical-demo"]
    assert c.get("/api/patients").status_code == 401
    assert c.get("/api/patients", headers={"Authorization": "Bearer t0k"}).status_code == 200
