"""
Integration test for the full API layer using TestClient with SQLite.
Tests the complete request-response cycle for all endpoints.
"""
import json
import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from unittest.mock import patch

from app.main import app
from app.db import get_session


# ---------------------------------------------------------------------------
# Override DB to use in-memory SQLite for tests
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite:///./test_integration.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})


def override_get_session():
    SQLModel.metadata.create_all(test_engine)
    with Session(test_engine) as session:
        yield session


app.dependency_overrides[get_session] = override_get_session


@pytest.fixture(autouse=True)
def setup_and_teardown():
    """Create tables before each test, drop after."""
    SQLModel.metadata.create_all(test_engine)
    yield
    SQLModel.metadata.drop_all(test_engine)


client = TestClient(app)
client.headers.update({"X-API-Key": "buguard_org_a_123"})

SAMPLE_RECORDS = [
    {"id": "t1", "type": "domain", "value": "test.com", "status": "active",
     "source": "scan", "tags": ["prod"], "metadata": {}},
    {"id": "t2", "type": "subdomain", "value": "api.test.com", "status": "active",
     "source": "scan", "tags": ["prod", "api"], "metadata": {}, "parent": "t1"},
    {"id": "t3", "type": "certificate", "value": "CN=test.com", "status": "active",
     "source": "scan", "tags": [],
     "metadata": {"expires": "2024-01-01", "issuer": "Let's Encrypt"}, "covers": "t1"},
    {"id": "bad", "type": "INVALID_TYPE", "value": "broken", "source": "scan"},
]


# ---------------------------------------------------------------------------
# Import endpoint tests
# ---------------------------------------------------------------------------

def test_import_endpoint_returns_correct_counts():
    response = client.post("/import", json=SAMPLE_RECORDS)
    assert response.status_code == 200
    data = response.json()
    assert data["imported"] == 3
    assert data["updated"] == 0
    assert len(data["failed"]) == 1


def test_import_is_idempotent():
    client.post("/import", json=SAMPLE_RECORDS[:3])
    response = client.post("/import", json=SAMPLE_RECORDS[:3])
    assert response.status_code == 200
    data = response.json()
    assert data["imported"] == 0
    assert data["updated"] == 3


def test_import_malformed_does_not_crash():
    response = client.post("/import", json=[{"type": "INVALID", "value": "x"}])
    assert response.status_code == 200
    data = response.json()
    assert data["imported"] == 0
    assert len(data["failed"]) == 1


# ---------------------------------------------------------------------------
# Assets list endpoint tests
# ---------------------------------------------------------------------------

def test_list_assets_pagination():
    client.post("/import", json=SAMPLE_RECORDS[:3])
    response = client.get("/assets?limit=2&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert data["limit"] == 2
    assert data["offset"] == 0


def test_list_assets_filter_by_type():
    client.post("/import", json=SAMPLE_RECORDS[:3])
    response = client.get("/assets?type=certificate")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["value"] == "CN=test.com"


def test_list_assets_filter_by_tag():
    client.post("/import", json=SAMPLE_RECORDS[:3])
    response = client.get("/assets?tag=api")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["value"] == "api.test.com"


def test_get_asset_not_found():
    response = client.get("/assets/nonexistent-id")
    assert response.status_code == 404


def test_get_asset_by_id():
    client.post("/import", json=SAMPLE_RECORDS[:1])
    list_response = client.get("/assets?type=domain")
    asset_id = list_response.json()["items"][0]["id"]
    response = client.get(f"/assets/{asset_id}")
    assert response.status_code == 200
    assert response.json()["value"] == "test.com"


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
