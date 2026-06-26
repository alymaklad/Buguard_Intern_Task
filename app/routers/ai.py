"""
AI analysis router — all four LangChain capabilities.

Endpoints:
  POST /ai/query    — Natural-language asset query
  POST /ai/risk     — Risk scoring & summarization
  POST /ai/enrich/{asset_id} — Automated enrichment & categorization
  POST /ai/report   — Natural-language report generation
"""
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

from app.auth import get_current_tenant
from app.limiter import limiter

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
@limiter.limit("10/minute")
def nl_query(
    request: Request,
    payload: NLQueryRequest,
    tenant_id: str = Depends(get_current_tenant),
    session: Session = Depends(get_session)
):
    """
    Natural-language asset query.

    The LLM translates your question into a structured filter, then we run
    a real SQL query. The model never invents asset data.

    Example: {"question": "Show me all expired certificates on production subdomains"}
    """
    try:
        return answer_nl_query(payload.question, tenant_id, session)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.post("/risk")
@limiter.limit("5/minute")
def risk_score(
    request: Request,
    payload: RiskRequest,
    tenant_id: str = Depends(get_current_tenant),
    session: Session = Depends(get_session)
):
    """
    Risk scoring & summarization.

    Fetches real assets from DB, evaluates expired certs, sensitive services,
    stale assets, and returns a structured risk assessment.

    Pass empty asset_ids to analyze all assets (up to 50).
    """
    try:
        return score_risk(payload.asset_ids, tenant_id, session)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.post("/enrich/{asset_id}")
@limiter.limit("10/minute")
def enrich(
    request: Request,
    asset_id: str,
    tenant_id: str = Depends(get_current_tenant),
    session: Session = Depends(get_session)
):
    """
    Automated enrichment & categorization.

    Classifies an asset's environment (prod/staging/dev), category, and criticality.
    Writes the enrichment result back to the asset's metadata and tags.
    """
    try:
        return enrich_asset(asset_id, tenant_id, session)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.post("/report")
@limiter.limit("3/minute")
def report(
    request: Request,
    payload: ReportRequest,
    tenant_id: str = Depends(get_current_tenant),
    session: Session = Depends(get_session)
):
    """
    Natural-language report generation with grounding validation.

    Generates a structured security report over the filtered (or full) dataset.
    Every asset ID the model mentions is validated against the queried set —
    hallucinated references are detected and stripped.
    """
    try:
        return generate_report(payload.filter, tenant_id, session)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
