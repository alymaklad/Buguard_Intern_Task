"""
Tests for hallucination grounding validation.

Proves that the grounding check in report.py correctly:
  1. Accepts reports that only reference real asset IDs.
  2. Detects and flags hallucinated IDs not in the queried set.
  3. Strips hallucinated IDs from section.referenced_asset_ids.
"""
import pytest
from app.schemas import ReportOutput, ReportSection
from app.ai.grounding import validate_report_ids as _validate_report_ids, extract_mentioned_values as _extract_mentioned_values
from app.models import Asset, AssetType, AssetStatus
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helper: build a mock asset
# ---------------------------------------------------------------------------

def make_asset(id: str, value: str, asset_type=AssetType.domain) -> Asset:
    return Asset(tenant_id="org_A", 
        id=id,
        type=asset_type,
        value=value,
        status=AssetStatus.active,
        first_seen=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
        source="test",
        tags=[],
        metadata_={},
    )


# ---------------------------------------------------------------------------
# Test: all referenced IDs are real → grounded=True
# ---------------------------------------------------------------------------

def test_grounding_valid_ids():
    real_ids = {"asset-001", "asset-002", "asset-003"}

    report = ReportOutput(
        title="Test Report",
        executive_summary="Overview of assets.",
        sections=[
            ReportSection(
                title="Section 1",
                content="Asset asset-001 is active.",
                referenced_asset_ids=["asset-001", "asset-002"],
            )
        ],
        total_assets_analyzed=3,
        key_findings=["All good"],
        overall_risk_level="low",
    )

    result = _validate_report_ids(report, real_ids)
    assert result["grounded"] is True
    assert result["hallucinated_ids"] == []
    assert result["flagged_sections"] == []


# ---------------------------------------------------------------------------
# Test: hallucinated ID is detected and stripped
# ---------------------------------------------------------------------------

def test_grounding_detects_hallucinated_id():
    real_ids = {"asset-001", "asset-002"}

    report = ReportOutput(
        title="Hallucination Test Report",
        executive_summary="Risk analysis.",
        sections=[
            ReportSection(
                title="Critical Finding",
                content="Asset hallucinated-999 has an expired certificate.",
                referenced_asset_ids=["asset-001", "hallucinated-999"],  # bad ID injected
            )
        ],
        total_assets_analyzed=2,
        key_findings=["Issue found"],
        overall_risk_level="high",
    )

    result = _validate_report_ids(report, real_ids)
    assert result["grounded"] is False
    assert "hallucinated-999" in result["hallucinated_ids"]
    assert len(result["flagged_sections"]) == 1
    assert result["flagged_sections"][0]["section"] == "Critical Finding"

    # Verify the hallucinated ID was stripped from the section
    assert "hallucinated-999" not in report.sections[0].referenced_asset_ids
    assert "asset-001" in report.sections[0].referenced_asset_ids  # real ID preserved


# ---------------------------------------------------------------------------
# Test: multiple hallucinated IDs across sections
# ---------------------------------------------------------------------------

def test_grounding_multiple_hallucinations():
    real_ids = {"real-a", "real-b"}

    report = ReportOutput(
        title="Multi-hallucination Report",
        executive_summary="Analysis.",
        sections=[
            ReportSection(
                title="Section A",
                content="fake-1 is exposed.",
                referenced_asset_ids=["real-a", "fake-1"],
            ),
            ReportSection(
                title="Section B",
                content="fake-2 is stale.",
                referenced_asset_ids=["real-b", "fake-2", "fake-3"],
            ),
        ],
        total_assets_analyzed=2,
        key_findings=["Multiple issues"],
        overall_risk_level="critical",
    )

    result = _validate_report_ids(report, real_ids)
    assert result["grounded"] is False
    assert set(result["hallucinated_ids"]) == {"fake-1", "fake-2", "fake-3"}
    assert len(result["flagged_sections"]) == 2

    # Real IDs still present in sections
    assert "real-a" in report.sections[0].referenced_asset_ids
    assert "real-b" in report.sections[1].referenced_asset_ids


# ---------------------------------------------------------------------------
# Test: value extraction from report text
# ---------------------------------------------------------------------------

def test_extract_mentioned_values():
    assets = [
        make_asset("id-1", "api.example.com", AssetType.subdomain),
        make_asset("id-2", "203.0.113.10", AssetType.ip_address),
        make_asset("id-3", "ghost.example.com", AssetType.subdomain),
    ]

    report = ReportOutput(
        title="Value Extraction Test",
        executive_summary="The subdomain api.example.com is at risk. IP 203.0.113.10 is exposed.",
        sections=[],
        total_assets_analyzed=2,
        key_findings=["api.example.com has issues"],
        overall_risk_level="medium",
    )

    mentioned = _extract_mentioned_values(report, assets)
    assert "api.example.com" in mentioned
    assert "203.0.113.10" in mentioned
    assert "ghost.example.com" not in mentioned  # not in text, not hallucinated, just not mentioned


# ---------------------------------------------------------------------------
# Test: empty referenced_asset_ids → always grounded
# ---------------------------------------------------------------------------

def test_grounding_no_ids_referenced():
    real_ids = {"asset-001"}

    report = ReportOutput(
        title="Safe Report",
        executive_summary="Nothing specific mentioned.",
        sections=[
            ReportSection(
                title="Overview",
                content="General overview with no specific asset references.",
                referenced_asset_ids=[],
            )
        ],
        total_assets_analyzed=1,
        key_findings=["All good"],
        overall_risk_level="low",
    )

    result = _validate_report_ids(report, real_ids)
    assert result["grounded"] is True
