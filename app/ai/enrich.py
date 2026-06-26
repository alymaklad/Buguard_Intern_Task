"""
Automated enrichment & categorization capability.

Grounding pattern:
  1. Fetch the REAL asset from DB.
  2. Pass its value + existing metadata to the LLM.
  3. LLM returns structured EnrichmentResult.
  4. We write the enrichment BACK to the asset's metadata column.

The LLM never invents new assets — it only classifies the one we give it.
"""
import json
from typing import Dict, Any

from langchain_core.prompts import ChatPromptTemplate
from sqlmodel import Session

from app.models import Asset
from app.schemas import EnrichmentResult
from app.ai.llm import get_llm


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

ENRICH_SYSTEM = """You are a cybersecurity asset classifier for an Attack Surface Monitoring platform.
You will be given a single asset's value and metadata. Your job is to classify it.

CLASSIFICATION RULES:
- environment: infer from subdomain labels (prod/staging/stage/dev/test/uat), IP ranges, or service banners.
  Default to 'prod' if the asset looks live and internet-facing with no environment indicators.
- category: functional role — e.g., 'web', 'api', 'database', 'cache', 'cdn', 'mail', 'vpn', 'admin', 'monitoring'
- criticality:
  * critical: production assets, payment/auth/database endpoints, admin interfaces
  * high: APIs, core infrastructure
  * medium: staging/test with real data, non-critical services
  * low: dev/sandbox environments, non-internet-facing assets
- confidence: how certain you are (0.0-1.0) based on available evidence
- reasoning: brief explanation referencing specific evidence from the asset data

IMPORTANT: Only analyze the asset you are given. Do not reference or invent other assets.
"""

ENRICH_HUMAN = """Classify this asset:

Type: {asset_type}
Value: {asset_value}
Current tags: {asset_tags}
Current metadata: {asset_metadata}
"""

enrich_prompt = ChatPromptTemplate.from_messages([
    ("system", ENRICH_SYSTEM),
    ("human", ENRICH_HUMAN),
])


def enrich_asset(asset_id: str, session: Session) -> Dict[str, Any]:
    """
    Classify and enrich a single asset.

    1. Fetch the real asset from DB.
    2. LLM produces EnrichmentResult.
    3. Write enrichment back to asset.metadata_.
    4. Return enrichment result + updated asset snapshot.
    """
    asset = session.get(Asset, asset_id)
    if not asset:
        raise ValueError(f"Asset with id '{asset_id}' not found.")

    llm = get_llm()
    structured_llm = llm.with_structured_output(EnrichmentResult)
    chain = enrich_prompt | structured_llm

    try:
        enrichment = chain.invoke({
            "asset_type": asset.type.value,
            "asset_value": asset.value,
            "asset_tags": json.dumps(asset.tags or []),
            "asset_metadata": json.dumps(asset.metadata_ or {}, indent=2, default=str),
        })
    except Exception as e:
        raise RuntimeError(f"LLM enrichment failed: {e}") from e

    # Write enrichment back to metadata
    updated_metadata = dict(asset.metadata_ or {})
    updated_metadata["ai_enrichment"] = {
        "environment": enrichment.environment,
        "category": enrichment.category,
        "criticality": enrichment.criticality,
        "confidence": enrichment.confidence,
        "reasoning": enrichment.reasoning,
    }

    # Also add environment and criticality as top-level tags for easy filtering
    updated_tags = list(set(asset.tags or []) | {enrichment.environment, enrichment.criticality})

    asset.metadata_ = updated_metadata
    asset.tags = updated_tags
    session.add(asset)
    session.commit()
    session.refresh(asset)

    return {
        "asset_id": asset.id,
        "asset_value": asset.value,
        "enrichment": enrichment.model_dump(),
        "tags_after": asset.tags,
        "metadata_after": asset.metadata_,
    }
