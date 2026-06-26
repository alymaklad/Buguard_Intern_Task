"""
Risk scoring & summarization capability.

Grounding pattern:
  1. Fetch REAL asset records from DB first.
  2. Pass that JSON as context to the LLM prompt.
  3. LLM returns structured RiskScore — not freeform prose.
  4. Risk factors evaluated: expired/expiring certs, sensitive services,
     EOL technology markers, stale assets, exposed admin ports.
"""
import json
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from langchain_core.prompts import ChatPromptTemplate
from sqlmodel import Session, select

from app.models import Asset
from app.schemas import RiskScore, AssetRead
from app.ai.llm import get_llm


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

RISK_SYSTEM = """You are a cybersecurity risk analyst for an Attack Surface Monitoring platform.
You will be given a JSON list of assets from a real database. Your job is to analyze ONLY
these assets and produce a structured risk assessment.

SCORING GUIDELINES:
- Expired certificates: +30 points
- Certificates expiring within 30 days: +20 points
- Sensitive exposed services (ssh, rdp, ftp, telnet, database ports 3306, 5432, 27017): +25 points
- End-of-life technology indicators (old versions, EOL tags): +20 points
- Stale assets that are still internet-facing: +15 points
- No tags or metadata (uncharted assets): +10 points

RULES:
- Only reference assets that appear in the provided JSON.
- Do not invent asset names, IDs, or values.
- Be specific: name exact asset values in your reasons.
- Provide actionable recommendations.
"""

RISK_HUMAN = """Analyze the following assets and provide a risk assessment:

Assets (JSON):
{assets_json}

Today's date: {today}
"""

risk_prompt = ChatPromptTemplate.from_messages([
    ("system", RISK_SYSTEM),
    ("human", RISK_HUMAN),
])

# Sensitive service ports/keywords
SENSITIVE_PORTS = {"22", "3389", "21", "23", "3306", "5432", "27017", "6379", "9200"}
SENSITIVE_KEYWORDS = {"ssh", "rdp", "ftp", "telnet", "mysql", "postgres", "mongodb", "redis", "elasticsearch"}


def _precompute_risk_hints(assets: List[Asset]) -> List[str]:
    """Pre-compute deterministic risk hints to guide the LLM."""
    hints = []
    today = datetime.now(timezone.utc)
    soon = today + timedelta(days=30)

    for asset in assets:
        meta = asset.metadata_ or {}

        # Certificate expiry checks
        if asset.type.value == "certificate":
            expires_str = meta.get("expires") or meta.get("expiry") or meta.get("not_after")
            if expires_str:
                try:
                    exp = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
                    if exp < today:
                        hints.append(f"EXPIRED CERT: {asset.value} expired on {expires_str}")
                    elif exp < soon:
                        hints.append(f"EXPIRING SOON: {asset.value} expires on {expires_str}")
                except ValueError:
                    pass

        # Sensitive service detection
        if asset.type.value == "service":
            port = str(meta.get("port", ""))
            banner = str(meta.get("banner", "")).lower()
            protocol = str(meta.get("protocol", "")).lower()
            if port in SENSITIVE_PORTS or any(kw in banner for kw in SENSITIVE_KEYWORDS):
                hints.append(f"SENSITIVE SERVICE: {asset.value} (port={port}, banner={banner[:50]})")

        # Stale assets
        if asset.status.value == "stale":
            hints.append(f"STALE ASSET: {asset.value} has not been seen recently")

    return hints


def score_risk(asset_ids: List[str], session: Session) -> Dict[str, Any]:
    """
    Fetch real assets from DB, then ask LLM to produce a structured RiskScore.

    Args:
        asset_ids: List of asset UUIDs to analyze (empty = all assets).
        session: DB session.

    Returns:
        Dict with risk assessment + the assets analyzed.
    """
    if asset_ids:
        stmt = select(Asset).where(Asset.id.in_(asset_ids))
    else:
        stmt = select(Asset).limit(50)  # safety cap for all-assets analysis

    assets = session.exec(stmt).all()

    if not assets:
        return {
            "error": "No assets found for the given IDs.",
            "asset_ids_requested": asset_ids,
        }

    # Serialize assets to JSON for the prompt
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

    hints = _precompute_risk_hints(assets)
    if hints:
        hint_text = "\n\nPre-computed risk hints (use these in your analysis):\n" + "\n".join(f"- {h}" for h in hints)
    else:
        hint_text = ""

    assets_json = json.dumps(assets_data, indent=2, default=str) + hint_text
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    llm = get_llm()
    structured_llm = llm.with_structured_output(RiskScore)
    chain = risk_prompt | structured_llm

    try:
        risk = chain.invoke({"assets_json": assets_json, "today": today_str})
    except Exception as e:
        raise RuntimeError(f"LLM risk scoring failed: {e}") from e

    return {
        "risk_assessment": risk.model_dump(),
        "assets_analyzed": len(assets),
        "asset_ids": [a.id for a in assets],
    }
