"""
Natural-language report generation capability.

Grounding pattern (strictly enforced):
  1. Fetch REAL filtered dataset from DB.
  2. Pass ONLY that data to the LLM as context.
  3. LLM generates structured ReportOutput referencing assets by their real IDs.
  4. POST-GENERATION VALIDATION: every asset ID/value the LLM mentions is
     checked against the set we actually queried. Hallucinated references are
     detected, flagged, and stripped from the final response.

The LLM is instructed to reference assets only by the exact id/value strings
provided — never by memory or inference.
"""
import json
import re
from typing import List, Dict, Any, Optional

from langchain_core.prompts import ChatPromptTemplate
from sqlmodel import Session, select

from app.models import Asset
from app.schemas import ReportOutput, AssetRead, QueryFilter
from app.ai.query import run_asset_query
from app.ai.llm import get_llm
from app.ai.grounding import validate_report_ids, extract_mentioned_values


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

REPORT_SYSTEM = """You are a cybersecurity report writer for an Attack Surface Monitoring platform.
You will be given a JSON dataset of assets from a real database. Write a professional security report
based SOLELY on the data provided.

CRITICAL RULES:
- Reference assets ONLY by their exact 'id' and 'value' strings from the JSON provided.
- Do NOT invent, infer, or reference any asset not present in the provided JSON.
- Every specific claim must be traceable to an asset in the dataset.
- Be precise: use exact asset values (e.g., "api.example.com", "203.0.113.5") not generic descriptions.
- In each section's referenced_asset_ids, list the IDs of assets you actually mention.

REPORT STRUCTURE GUIDANCE:
- Title: concise, descriptive
- Executive summary: 2-3 sentence overview
- Sections: organize by theme (e.g., Certificate Health, Exposed Services, Technology Stack, Stale Assets)
- Key findings: 3-5 bullet points highlighting the most critical items
- Overall risk level: your assessment of the dataset as a whole
"""

REPORT_HUMAN = """Generate a security report for the following asset dataset:

Filter applied: {filter_description}
Total assets in dataset: {total_count}

Asset data (JSON):
{assets_json}

Today's date: {today}

Remember: Only reference assets present in the JSON above by their exact id and value.
"""

report_prompt = ChatPromptTemplate.from_messages([
    ("system", REPORT_SYSTEM),
    ("human", REPORT_HUMAN),
])


# Grounding helpers live in grounding.py (imported above)
# _validate_report_ids → validate_report_ids
# _extract_mentioned_values → extract_mentioned_values


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def generate_report(
    filter_params: Optional[QueryFilter],
    tenant_id: str,
    session: Session,
    limit: int = 100,
) -> Dict[str, Any]:
    """
    Generate a grounded natural-language security report.

    1. Fetch real filtered data.
    2. LLM generates structured report.
    3. Validate all mentioned IDs against the queried set.
    4. Return report + grounding validation result.
    """
    from datetime import datetime, timezone

    # Step 1: Fetch real data
    if filter_params:
        assets = run_asset_query(filter_params, tenant_id, session)
    else:
        assets = list(session.exec(select(Asset).where(Asset.tenant_id == tenant_id).limit(limit)).all())

    if not assets:
        return {
            "error": "No assets found matching the filter. Cannot generate a report.",
            "filter": filter_params.model_dump(exclude_none=True) if filter_params else {},
        }

    real_ids = {a.id for a in assets}
    real_values = {a.value for a in assets}

    # Serialize assets for the prompt
    assets_data = [
        {
            "id": a.id,
            "type": a.type.value,
            "value": a.value,
            "status": a.status.value,
            "tags": a.tags or [],
            "metadata": a.metadata_ or {},
        }
        for a in assets
    ]

    filter_description = (
        filter_params.model_dump(exclude_none=True) if filter_params else "No filter (full dataset)"
    )
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Step 2: Generate structured report
    llm = get_llm()
    structured_llm = llm.with_structured_output(ReportOutput)
    chain = report_prompt | structured_llm

    try:
        report = chain.invoke({
            "filter_description": json.dumps(filter_description),
            "total_count": len(assets),
            "assets_json": json.dumps(assets_data, indent=2, default=str),
            "today": today_str,
        })
    except Exception as e:
        raise RuntimeError(f"LLM report generation failed: {e}") from e

    # Step 3: Grounding validation
    grounding = validate_report_ids(report, real_ids)

    # Also check values mentioned in text for transparency
    mentioned_values = extract_mentioned_values(report, assets)

    return {
        "report": report.model_dump(),
        "grounding_validation": {
            **grounding,
            "total_assets_queried": len(assets),
            "asset_values_confirmed_in_text": mentioned_values,
        },
        "assets_queried_ids": list(real_ids),
    }
