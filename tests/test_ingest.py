"""
Tests for bulk ingest, deduplication, and merge logic.

Uses an in-memory SQLite database for speed — no Docker/Postgres required for unit tests.
"""
import pytest
from sqlmodel import SQLModel, Session, create_engine

from app.models import Asset, AssetRelationship, AssetStatus, AssetType
from app.ingest import bulk_import, _merge_tags, _merge_metadata


# ---------------------------------------------------------------------------
# In-memory SQLite fixture (no Postgres needed for unit tests)
# ---------------------------------------------------------------------------

@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Tag & metadata merge unit tests
# ---------------------------------------------------------------------------

def test_merge_tags_union():
    result = _merge_tags(["prod", "api"], ["prod", "critical"])
    assert set(result) == {"prod", "api", "critical"}


def test_merge_tags_dedup():
    result = _merge_tags(["a", "b"], ["a", "b"])
    assert sorted(result) == ["a", "b"]


def test_merge_metadata_newer_wins():
    existing = {"version": "1.0", "issuer": "OldCA"}
    incoming = {"version": "2.0", "expires": "2027-01-01"}
    result = _merge_metadata(existing, incoming)
    assert result["version"] == "2.0"   # incoming overwrites
    assert result["issuer"] == "OldCA"  # existing preserved
    assert result["expires"] == "2027-01-01"


# ---------------------------------------------------------------------------
# Ingest: basic import
# ---------------------------------------------------------------------------

def test_basic_import(session):
    records = [
        {"id": "a1", "type": "domain", "value": "example.com", "source": "scan", "tags": ["root"], "metadata": {}},
        {"id": "a2", "type": "subdomain", "value": "api.example.com", "source": "scan", "tags": ["prod"], "metadata": {}},
    ]
    result = bulk_import(records, session)
    assert result["imported"] == 2
    assert result["updated"] == 0
    assert result["failed"] == []


# ---------------------------------------------------------------------------
# Ingest: idempotent (re-import same records → same row count)
# ---------------------------------------------------------------------------

def test_idempotent_import(session):
    records = [
        {"id": "a1", "type": "domain", "value": "example.com", "source": "scan", "tags": ["root"], "metadata": {}},
    ]
    r1 = bulk_import(records, session)
    r2 = bulk_import(records, session)

    assert r1["imported"] == 1
    assert r2["imported"] == 0
    assert r2["updated"] == 1

    # Verify only ONE row exists
    from sqlmodel import select
    assets = session.exec(select(Asset)).all()
    assert len(assets) == 1


# ---------------------------------------------------------------------------
# Ingest: dedup merges tags
# ---------------------------------------------------------------------------

def test_dedup_merges_tags(session):
    from sqlmodel import select
    records_v1 = [
        {"type": "domain", "value": "corp.io", "source": "scan", "tags": ["root"], "metadata": {}},
    ]
    records_v2 = [
        {"type": "domain", "value": "corp.io", "source": "scan", "tags": ["critical"], "metadata": {}},
    ]
    bulk_import(records_v1, session)
    bulk_import(records_v2, session)

    asset = session.exec(select(Asset).where(Asset.value == "corp.io")).first()
    assert "root" in asset.tags
    assert "critical" in asset.tags


# ---------------------------------------------------------------------------
# Ingest: re-appearing stale asset flips to active
# ---------------------------------------------------------------------------

def test_stale_asset_reactivated(session):
    from sqlmodel import select

    # Import as stale
    records_stale = [
        {"type": "domain", "value": "old.example.com", "status": "stale", "source": "scan", "tags": [], "metadata": {}},
    ]
    bulk_import(records_stale, session)

    asset = session.exec(select(Asset).where(Asset.value == "old.example.com")).first()
    assert asset.status == AssetStatus.stale

    # Re-import same asset (it reappears)
    records_active = [
        {"type": "domain", "value": "old.example.com", "status": "active", "source": "scan", "tags": [], "metadata": {}},
    ]
    bulk_import(records_active, session)

    session.refresh(asset)
    assert asset.status == AssetStatus.active


# ---------------------------------------------------------------------------
# Ingest: malformed record doesn't crash batch
# ---------------------------------------------------------------------------

def test_malformed_record_does_not_crash_batch(session):
    records = [
        {"id": "good1", "type": "domain", "value": "valid.com", "source": "scan", "tags": [], "metadata": {}},
        {"id": "bad1", "type": "invalid_type_xyz", "value": "bad.com", "source": "scan"},  # bad type
        {"id": "good2", "type": "ip_address", "value": "1.2.3.4", "source": "scan", "tags": [], "metadata": {}},
    ]
    result = bulk_import(records, session)

    assert result["imported"] == 2   # two good records
    assert len(result["failed"]) == 1  # one bad record logged
    assert result["failed"][0]["index"] == 1


# ---------------------------------------------------------------------------
# Ingest: metadata merge strategy
# ---------------------------------------------------------------------------

def test_metadata_newer_wins_on_reimport(session):
    from sqlmodel import select

    records_v1 = [
        {"type": "certificate", "value": "CN=test.com", "source": "scan", "tags": [],
         "metadata": {"issuer": "OldCA", "expires": "2024-01-01"}},
    ]
    records_v2 = [
        {"type": "certificate", "value": "CN=test.com", "source": "scan", "tags": [],
         "metadata": {"expires": "2027-01-01"}},  # updated expiry
    ]
    bulk_import(records_v1, session)
    bulk_import(records_v2, session)

    asset = session.exec(select(Asset).where(Asset.value == "CN=test.com")).first()
    assert asset.metadata_["expires"] == "2027-01-01"  # newer wins
    assert asset.metadata_["issuer"] == "OldCA"         # existing preserved
