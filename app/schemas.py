"""
Pydantic request/response schemas AND LangChain structured-output schemas.

Separating from models.py keeps the DB layer clean and lets us version
the API contract independently of the table structure.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict

from app.models import AssetType, AssetStatus, RelationshipType


# ---------------------------------------------------------------------------
# Import / ingest schemas
# ---------------------------------------------------------------------------

class AssetImportRecord(BaseModel):
    """Single record in a bulk import payload. All fields except type+value optional."""
    id: Optional[str] = None           # external ID hint (stored as-is if no conflict)
    type: AssetType
    value: str
    status: AssetStatus = AssetStatus.active
    source: str = "import"
    tags: List[str] = []
    metadata: Dict[str, Any] = {}
    # Convenience relationship hints (processed in ingest.py)
    parent: Optional[str] = None       # external ID of parent asset
    covers: Optional[str] = None       # certificate covers this asset id


class ImportResponse(BaseModel):
    imported: int
    updated: int
    failed: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Asset read schemas
# ---------------------------------------------------------------------------

class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: AssetType
    value: str
    status: AssetStatus
    first_seen: datetime
    last_seen: datetime
    source: str
    tags: List[str]
    metadata: Dict[str, Any]


class AssetList(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[AssetRead]


class RelationshipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    from_asset_id: str
    to_asset_id: str
    relationship_type: RelationshipType


# ---------------------------------------------------------------------------
# LangChain structured-output schemas (used by all four AI capabilities)
# ---------------------------------------------------------------------------

class QueryFilter(BaseModel):
    """
    Structured filter the LLM produces from a natural-language question.
    The LLM never produces asset IDs — only filter parameters that we
    validate and run as a real SQL query.
    """
    asset_type: Optional[AssetType] = Field(None, description="Filter by asset type")
    status: Optional[AssetStatus] = Field(None, description="Filter by lifecycle status")
    tag: Optional[str] = Field(None, description="Filter assets that have this tag")
    value_contains: Optional[str] = Field(None, description="Filter assets whose value contains this substring")
    metadata_key: Optional[str] = Field(None, description="Filter assets that have this metadata key set")
    metadata_value: Optional[str] = Field(None, description="Value that metadata_key should equal (optional)")
    out_of_scope: bool = Field(False, description="Set true if the question cannot be answered from asset data")
    out_of_scope_reason: Optional[str] = Field(None, description="Explanation when out_of_scope=true")


class RiskScore(BaseModel):
    """Structured risk assessment the LLM returns for an asset or group."""
    risk_score: int = Field(..., ge=0, le=100, description="Overall risk score 0-100")
    severity: Literal["low", "medium", "high", "critical"]
    reasons: List[str] = Field(..., description="Specific reasons driving the risk score")
    summary: str = Field(..., description="Concise human-readable risk summary")
    recommendations: List[str] = Field(default_factory=list, description="Actionable remediation steps")


class EnrichmentResult(BaseModel):
    """Structured enrichment/classification result the LLM returns for a raw asset."""
    environment: Literal["prod", "staging", "dev", "unknown"] = Field(
        ..., description="Inferred deployment environment"
    )
    category: str = Field(..., description="Functional category, e.g. 'web', 'api', 'database', 'cdn'")
    criticality: Literal["low", "medium", "high", "critical"] = Field(
        ..., description="Business criticality"
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Model confidence 0.0-1.0")
    reasoning: str = Field(..., description="Why this classification was chosen")


class ReportSection(BaseModel):
    title: str
    content: str
    referenced_asset_ids: List[str] = Field(
        default_factory=list,
        description="IDs of assets explicitly mentioned in this section"
    )


class ReportOutput(BaseModel):
    """Structured report the LLM generates over a filtered dataset."""
    title: str
    executive_summary: str
    sections: List[ReportSection]
    total_assets_analyzed: int
    key_findings: List[str]
    overall_risk_level: Literal["low", "medium", "high", "critical"]
