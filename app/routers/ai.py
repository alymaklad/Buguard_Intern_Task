"""
AI analysis router — all four LangChain capabilities.

Endpoints:
  POST /ai/query    — Natural-language asset query
  POST /ai/risk     — Risk scoring & summarization
  POST /ai/enrich/{asset_id} — Automated enrichment & categorization
  POST /ai/report   — Natural-language report generation
"""
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_session
from app.schemas import QueryFilter
from app.ai.query import answer_nl_query
from app.ai.risk import score_risk
from app.ai.enrich import enrich_asset
from app.ai.report import generate_report

router = APIRouter(prefix="/ai", tags=["AI Analysis"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class NLQueryRequest(BaseModel):
    question: str


class RiskRequest(BaseModel):
    asset_ids: List[str] = []  # empty = analyze all assets (capped at 50)


class ReportRequest(BaseModel):
    filter: Optional[QueryFilter] = None  # None = full dataset


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/query")
def nl_query(request: NLQueryRequest, session: Session = Depends(get_session)):
    """
    Natural-language asset query.

    The LLM translates your question into a structured filter, then we run
    a real SQL query. The model never invents asset data.

    Example: {"question": "Show me all expired certificates on production subdomains"}
    """
    try:
        return answer_nl_query(request.question, session)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.post("/risk")
def risk_score(request: RiskRequest, session: Session = Depends(get_session)):
    """
    Risk scoring & summarization.

    Fetches real assets from DB, evaluates expired certs, sensitive services,
    stale assets, and returns a structured risk assessment.

    Pass empty asset_ids to analyze all assets (up to 50).
    """
    try:
        return score_risk(request.asset_ids, session)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.post("/enrich/{asset_id}")
def enrich(asset_id: str, session: Session = Depends(get_session)):
    """
    Automated enrichment & categorization.

    Classifies an asset's environment (prod/staging/dev), category, and criticality.
    Writes the enrichment result back to the asset's metadata and tags.
    """
    try:
        return enrich_asset(asset_id, session)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.post("/report")
def report(request: ReportRequest, session: Session = Depends(get_session)):
    """
    Natural-language report generation with grounding validation.

    Generates a structured security report over the filtered (or full) dataset.
    Every asset ID the model mentions is validated against the queried set —
    hallucinated references are detected and stripped.
    """
    try:
        return generate_report(request.filter, session)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
