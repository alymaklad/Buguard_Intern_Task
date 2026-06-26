"""
Assets router — import and list endpoints.

Endpoints:
  POST /import   — bulk ingest with dedup/merge
  GET  /assets   — paginated list with type/status/tag filters
  GET  /assets/{id} — single asset lookup
  GET  /assets/{id}/relationships — relationships for an asset
"""
import json
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models import Asset, AssetRelationship, AssetType, AssetStatus
from app.ingest import bulk_import
from app.schemas import AssetRead, AssetList, ImportResponse, RelationshipRead
from app.auth import get_current_tenant

router = APIRouter(tags=["Assets"])


@router.post("/import", response_model=ImportResponse)
def import_assets(
    records: List[Dict[str, Any]],
    tenant_id: str = Depends(get_current_tenant),
    session: Session = Depends(get_session),
):
    """
    Bulk import assets from a JSON array.

    - Upsert-based dedup on (type, value).
    - Idempotent: re-importing same records bumps last_seen only.
    - Per-record validation: one bad record never crashes the batch.
    - Returns count of imported, updated, and failed records.
    """
    result = bulk_import(records, tenant_id, session)
    return ImportResponse(**result)


@router.get("/assets", response_model=AssetList)
def list_assets(
    type: Optional[AssetType] = Query(None, description="Filter by asset type"),
    status: Optional[AssetStatus] = Query(None, description="Filter by status"),
    tag: Optional[str] = Query(None, description="Filter by tag label"),
    value_contains: Optional[str] = Query(None, description="Substring search in asset value"),
    limit: int = Query(20, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    tenant_id: str = Depends(get_current_tenant),
    session: Session = Depends(get_session),
):
    """
    List assets with optional filtering and pagination.
    """
    stmt = select(Asset).where(Asset.tenant_id == tenant_id)
    count_stmt = select(Asset).where(Asset.tenant_id == tenant_id)

    if type:
        stmt = stmt.where(Asset.type == type)
        count_stmt = count_stmt.where(Asset.type == type)
    if status:
        stmt = stmt.where(Asset.status == status)
        count_stmt = count_stmt.where(Asset.status == status)
    if value_contains:
        stmt = stmt.where(Asset.value.ilike(f"%{value_contains}%"))
        count_stmt = count_stmt.where(Asset.value.ilike(f"%{value_contains}%"))

    all_assets = session.exec(count_stmt).all()

    # Tag filtering in Python (JSON array membership)
    if tag:
        all_assets = [a for a in all_assets if tag in (a.tags or [])]

    total = len(all_assets)
    paged = all_assets[offset: offset + limit]

    items = [
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
        )
        for a in paged
    ]

    return AssetList(total=total, limit=limit, offset=offset, items=items)


@router.get("/assets/{asset_id}", response_model=AssetRead)
def get_asset(
    asset_id: str,
    tenant_id: str = Depends(get_current_tenant),
    session: Session = Depends(get_session)
):
    """Retrieve a single asset by its UUID."""
    asset = session.get(Asset, asset_id)
    if not asset or asset.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found.")
    return AssetRead(
        id=asset.id,
        type=asset.type,
        value=asset.value,
        status=asset.status,
        first_seen=asset.first_seen,
        last_seen=asset.last_seen,
        source=asset.source,
        tags=asset.tags or [],
        metadata=asset.metadata_ or {},
    )


@router.get("/assets/{asset_id}/relationships", response_model=List[RelationshipRead])
def get_asset_relationships(
    asset_id: str,
    tenant_id: str = Depends(get_current_tenant),
    session: Session = Depends(get_session)
):
    """Get all relationships involving this asset (as source or target)."""
    asset = session.get(Asset, asset_id)
    if not asset or asset.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found.")

    rels = session.exec(
        select(AssetRelationship).where(
            (AssetRelationship.from_asset_id == asset_id) |
            (AssetRelationship.to_asset_id == asset_id)
        )
    ).all()

    return [
        RelationshipRead(
            id=r.id,
            from_asset_id=r.from_asset_id,
            to_asset_id=r.to_asset_id,
            relationship_type=r.relationship_type,
        )
        for r in rels
    ]
