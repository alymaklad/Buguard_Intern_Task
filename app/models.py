"""
SQLModel table models for the Asset Management System.

Tables:
  - Asset: core asset record (domain, subdomain, ip_address, service, certificate, technology)
  - AssetRelationship: directed edge between two assets

Design decisions:
  - Unique constraint on (type, value) enables dedup/upsert without extra lookup.
  - tags and metadata stored as JSON (PostgreSQL JSONB-compatible via SQLModel).
  - UUID primary keys for global uniqueness and safe exposure in APIs.
  - No Alembic — create_all() on startup is fine for a 1-week project scope.
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any

from sqlmodel import SQLModel, Field, Column, JSON, UniqueConstraint


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AssetType(str, Enum):
    domain = "domain"
    subdomain = "subdomain"
    ip_address = "ip_address"
    service = "service"
    certificate = "certificate"
    technology = "technology"


class AssetStatus(str, Enum):
    active = "active"
    stale = "stale"
    archived = "archived"


class RelationshipType(str, Enum):
    subdomain_of = "subdomain_of"        # subdomain → domain
    resolves_to = "resolves_to"          # subdomain/domain → ip_address
    hosted_on = "hosted_on"              # service → ip_address
    secures = "secures"                  # certificate → domain/subdomain
    runs_on = "runs_on"                  # technology → subdomain/service
    related_to = "related_to"            # generic


# ---------------------------------------------------------------------------
# Asset table
# ---------------------------------------------------------------------------

class Asset(SQLModel, table=True):
    __tablename__ = "assets"
    __table_args__ = (
        UniqueConstraint("type", "value", name="uq_asset_type_value"),
    )

    id: Optional[str] = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
        index=True,
    )
    type: AssetType = Field(index=True)
    value: str = Field(index=True)
    status: AssetStatus = Field(default=AssetStatus.active, index=True)
    first_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = Field(default="import")
    tags: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    metadata_: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSON),
    )


# ---------------------------------------------------------------------------
# Relationship table
# ---------------------------------------------------------------------------

class AssetRelationship(SQLModel, table=True):
    __tablename__ = "relationships"

    id: Optional[str] = Field(
        default_factory=lambda: str(uuid.uuid4()),
        primary_key=True,
    )
    from_asset_id: str = Field(index=True, foreign_key="assets.id")
    to_asset_id: str = Field(index=True, foreign_key="assets.id")
    relationship_type: RelationshipType = Field(default=RelationshipType.related_to)
