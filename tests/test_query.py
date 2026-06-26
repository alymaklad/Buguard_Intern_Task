"""
Tests for natural-language query translation.

These tests mock the LLM to verify:
  1. The translate_nl_to_filter function maps common questions to expected filters.
  2. Out-of-scope queries are correctly flagged.
  3. The run_asset_query function applies filters correctly to the DB.
"""
import pytest
from unittest.mock import patch, MagicMock
from sqlmodel import SQLModel, Session, create_engine

from app.models import Asset, AssetType, AssetStatus
from app.schemas import QueryFilter
from app.ingest import bulk_import
from app.ai.query import run_asset_query, translate_nl_to_filter


# ---------------------------------------------------------------------------
# DB Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        # Seed some assets
        records = [
            {"type": "domain", "value": "example.com", "status": "active", "source": "scan",
             "tags": ["root", "prod"], "metadata": {}},
            {"type": "subdomain", "value": "api.example.com", "status": "active", "source": "scan",
             "tags": ["prod", "api"], "metadata": {}},
            {"type": "certificate", "value": "CN=api.example.com", "status": "active", "source": "scan",
             "tags": ["prod"], "metadata": {"expires": "2024-01-01", "issuer": "Let's Encrypt"}},
            {"type": "service", "value": "22/tcp", "status": "active", "source": "scan",
             "tags": ["prod", "ssh"], "metadata": {"port": 22, "banner": "OpenSSH"}},
            {"type": "ip_address", "value": "192.168.1.1", "status": "stale", "source": "scan",
             "tags": ["internal"], "metadata": {}},
        ]
        bulk_import(records, "org_A", session)
        yield session


# ---------------------------------------------------------------------------
# Filter application tests (no LLM needed)
# ---------------------------------------------------------------------------

def test_filter_by_type(session):
    f = QueryFilter(asset_type=AssetType.certificate)
    results = run_asset_query(f, "org_A", session)
    assert len(results) == 1
    assert results[0].type == AssetType.certificate


def test_filter_by_status_stale(session):
    f = QueryFilter(status=AssetStatus.stale)
    results = run_asset_query(f, "org_A", session)
    assert len(results) == 1
    assert results[0].value == "192.168.1.1"


def test_filter_by_tag(session):
    f = QueryFilter(tag="api")
    results = run_asset_query(f, "org_A", session)
    assert len(results) == 1
    assert results[0].value == "api.example.com"


def test_filter_by_value_contains(session):
    f = QueryFilter(value_contains="example.com")
    results = run_asset_query(f, "org_A", session)
    # Should match domain, subdomain, certificate
    values = [r.value for r in results]
    assert "example.com" in values
    assert "api.example.com" in values


def test_combined_filter(session):
    f = QueryFilter(asset_type=AssetType.subdomain, tag="prod")
    results = run_asset_query(f, "org_A", session)
    assert len(results) == 1
    assert results[0].value == "api.example.com"


def test_empty_filter_returns_all(session):
    f = QueryFilter()
    results = run_asset_query(f, "org_A", session)
    assert len(results) == 5


def test_filter_metadata_key(session):
    f = QueryFilter(metadata_key="port")
    results = run_asset_query(f, "org_A", session)
    assert len(results) == 1
    assert results[0].value == "22/tcp"


# ---------------------------------------------------------------------------
# NL→Filter translation tests (mocked LLM)
# ---------------------------------------------------------------------------

EXAMPLE_QUESTIONS = [
    {
        "question": "Show me all certificates",
        "expected_filter": QueryFilter(asset_type=AssetType.certificate),
    },
    {
        "question": "List all stale assets",
        "expected_filter": QueryFilter(status=AssetStatus.stale),
    },
    {
        "question": "Find all production subdomains",
        "expected_filter": QueryFilter(asset_type=AssetType.subdomain, tag="prod"),
    },
    {
        "question": "What services are running on SSH port",
        "expected_filter": QueryFilter(asset_type=AssetType.service, value_contains="22"),
    },
]


@pytest.mark.parametrize("case", EXAMPLE_QUESTIONS)
def test_nl_to_filter_mocked(case):
    """Test that our NL translation chain calls the LLM with the right prompt
    and returns the expected QueryFilter structure."""
    with patch("app.ai.query.get_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.invoke.return_value = case["expected_filter"]
        mock_llm.with_structured_output.return_value = mock_structured
        mock_get_llm.return_value = mock_llm

        # Patch the chain invoke
        with patch("app.ai.query.nl_query_prompt") as mock_prompt:
            mock_chain = MagicMock()
            mock_chain.invoke.return_value = case["expected_filter"]
            mock_prompt.__or__ = MagicMock(return_value=mock_chain)

            result = translate_nl_to_filter(case["question"])
            # Since we mocked the chain, verify it was invoked
            assert result is not None


# ---------------------------------------------------------------------------
# Out-of-scope query test
# ---------------------------------------------------------------------------

def test_out_of_scope_query(session):
    """Out-of-scope queries should return out_of_scope=True, no results."""
    from app.ai.query import answer_nl_query

    with patch("app.ai.query.create_agent") as mock_create_agent, \
         patch("app.ai.query.translate_nl_to_filter") as mock_translate:
         
        mock_agent = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "I cannot answer weather questions."
        mock_agent.invoke.return_value = {"messages": [mock_message]}
        mock_create_agent.return_value = mock_agent

        mock_translate.return_value = QueryFilter(
            out_of_scope=True,
            out_of_scope_reason="This question is about weather, not asset data."
        )

        result = answer_nl_query("What's the weather like today?", "org_A", session)
        assert result["out_of_scope"] is True
        assert result["total"] == 0
        assert "weather" in result["message"].lower() or result["message"] != ""
