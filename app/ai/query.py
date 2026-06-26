"""
Natural-language asset query capability.

Grounding pattern:
  1. LLM translates NL question → structured QueryFilter (no asset IDs produced).
  2. We validate filter fields against real enum values.
  3. We run a real SQL query against PostgreSQL.
  4. LLM never invents asset data — it only produces query parameters.

Handles:
  - Out-of-scope / ambiguous queries gracefully (out_of_scope=True in filter).
  - Provider errors with clean FastAPI error responses.
"""
import json
from typing import List, Dict, Any

from langchain_core.prompts import ChatPromptTemplate
from sqlmodel import Session, select

from app.models import Asset, AssetType, AssetStatus
from app.schemas import QueryFilter, AssetRead
from app.ai.llm import get_llm


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

NL_QUERY_SYSTEM = """You are an asset query translator for a cybersecurity Attack Surface Monitoring platform.
Your job is to translate a natural-language question into a structured query filter.

AVAILABLE ASSET TYPES: domain, subdomain, ip_address, service, certificate, technology
AVAILABLE STATUSES: active, stale, archived

RULES:
- Only produce filters that match the available types and statuses.
- If the question asks about something not related to asset data (e.g., weather, general knowledge),
  set out_of_scope=true and explain why.
- If a filter field is not relevant, leave it as null.
- Do NOT invent asset IDs or values — only produce filter parameters.
- value_contains should be a substring to search in the asset's value field.
- tag should be a single tag label to filter by (e.g., "prod", "expired").
"""

NL_QUERY_HUMAN = "Question: {question}"

nl_query_prompt = ChatPromptTemplate.from_messages([
    ("system", NL_QUERY_SYSTEM),
    ("human", NL_QUERY_HUMAN),
])


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def translate_nl_to_filter(question: str) -> QueryFilter:
    """
    Use LLM with structured output to translate NL question → QueryFilter.
    Raises RuntimeError on LLM/provider failure.
    """
    llm = get_llm()
    structured_llm = llm.with_structured_output(QueryFilter)
    chain = nl_query_prompt | structured_llm
    try:
        result = chain.invoke({"question": question})
        return result
    except Exception as e:
        raise RuntimeError(f"LLM query translation failed: {e}") from e


def run_asset_query(filter_obj: QueryFilter, session: Session) -> List[Asset]:
    """
    Execute a real SQL query based on the structured filter.
    The LLM never sees or produces asset data at this stage.
    """
    stmt = select(Asset)

    if filter_obj.asset_type:
        stmt = stmt.where(Asset.type == filter_obj.asset_type)
    if filter_obj.status:
        stmt = stmt.where(Asset.status == filter_obj.status)
    if filter_obj.value_contains:
        stmt = stmt.where(Asset.value.ilike(f"%{filter_obj.value_contains}%"))

    assets = session.exec(stmt).all()

    # Post-filter for tag (JSON array membership — simpler in Python than SQL)
    if filter_obj.tag:
        assets = [a for a in assets if filter_obj.tag in (a.tags or [])]

    # Post-filter for metadata key/value
    if filter_obj.metadata_key:
        if filter_obj.metadata_value:
            assets = [
                a for a in assets
                if str((a.metadata_ or {}).get(filter_obj.metadata_key, "")) == filter_obj.metadata_value
            ]
        else:
            assets = [a for a in assets if filter_obj.metadata_key in (a.metadata_ or {})]

    return list(assets)


def answer_nl_query(question: str, session: Session) -> Dict[str, Any]:
    """
    Full NL query pipeline:
      1. Translate question to filter.
      2. Run real DB query.
      3. Return results with the filter used (for transparency).

    Returns a dict safe to serialize as a JSON response.
    """
    filter_obj = translate_nl_to_filter(question)

    if filter_obj.out_of_scope:
        return {
            "out_of_scope": True,
            "message": filter_obj.out_of_scope_reason or "This question is outside the scope of asset data.",
            "filter_used": None,
            "results": [],
            "total": 0,
        }

    assets = run_asset_query(filter_obj, session)

    return {
        "out_of_scope": False,
        "filter_used": filter_obj.model_dump(exclude_none=True),
        "results": [
            AssetRead(
                id=a.id,
                type=a.type,
                value=a.value,
                status=a.status,
                first_seen=a.first_seen,
                last_seen=a.last_seen,
                source=a.source,
                tags=a.tags or [],
                metadata=a.metadata_ or {},
            ).model_dump()
            for a in assets
        ],
        "total": len(assets),
    }
