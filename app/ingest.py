"""
Bulk import and deduplication logic.

Dedup strategy (documented in README):
  - Match on (type, value) unique constraint.
  - On conflict (re-import): update last_seen, union tags, newer-source-wins per metadata key.
  - Re-appearing stale/archived assets are flipped back to active.
  - Per-record Pydantic validation: failures are collected and returned, never crash the batch.
  - Returns {imported, updated, failed: [{index, value, error}]}.
"""
from datetime import datetime, timezone
from typing import List, Dict, Any

from sqlmodel import Session, select

from app.models import Asset, AssetRelationship, AssetStatus, RelationshipType
from app.schemas import AssetImportRecord


def _merge_tags(existing: List[str], incoming: List[str]) -> List[str]:
    """Union merge — preserves all unique tags from both sources."""
    return list(set(existing) | set(incoming))


def _merge_metadata(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Newer source wins per key — incoming values overwrite existing ones."""
    merged = dict(existing)
    merged.update(incoming)
    return merged


def bulk_import(
    raw_records: List[Dict[str, Any]],
    tenant_id: str,
    session: Session,
) -> Dict[str, Any]:
    """
    Import a list of raw dicts as assets.

    Returns:
        {"imported": int, "updated": int, "failed": [{index, value, error}]}
    """
    imported = 0
    updated = 0
    failed = []

    # Build an external-id → internal-id map so relationship hints work
    ext_id_map: Dict[str, str] = {}

    for idx, raw in enumerate(raw_records):
        try:
            record = AssetImportRecord.model_validate(raw)
        except Exception as e:
            failed.append({"index": idx, "value": raw.get("value", "?"), "error": str(e)})
            continue

        now = datetime.now(timezone.utc)

        try:
            # Check for existing asset by (tenant_id, type, value)
            stmt = select(Asset).where(
                Asset.tenant_id == tenant_id,
                Asset.type == record.type,
                Asset.value == record.value,
            )
            existing = session.exec(stmt).first()

            if existing:
                # --- UPDATE path ---
                existing.last_seen = now
                existing.tags = _merge_tags(existing.tags or [], record.tags)
                existing.metadata_ = _merge_metadata(existing.metadata_ or {}, record.metadata)
                # Re-activate stale/archived assets that show up again
                if existing.status in (AssetStatus.stale, AssetStatus.archived):
                    existing.status = AssetStatus.active
                session.add(existing)
                session.commit()
                session.refresh(existing)
                ext_id_map[record.id or record.value] = existing.id
                updated += 1
            else:
                # --- INSERT path ---
                asset = Asset(
                    tenant_id=tenant_id,
                    type=record.type,
                    value=record.value,
                    status=record.status,
                    source=record.source,
                    tags=record.tags,
                    metadata_=record.metadata,
                    first_seen=now,
                    last_seen=now,
                )
                session.add(asset)
                session.commit()
                session.refresh(asset)
                ext_id_map[record.id or record.value] = asset.id
                imported += 1

        except Exception as e:
            session.rollback()
            failed.append({"index": idx, "value": record.value, "error": str(e)})
            continue

    # --- Process relationship hints (parent, covers) ---
    for idx, raw in enumerate(raw_records):
        try:
            record = AssetImportRecord.model_validate(raw)
        except Exception:
            continue

        asset_internal_id = ext_id_map.get(record.id or record.value)
        if not asset_internal_id:
            continue

        hints = []
        if record.parent:
            parent_internal_id = ext_id_map.get(record.parent)
            if parent_internal_id:
                hints.append((asset_internal_id, parent_internal_id, RelationshipType.subdomain_of))
        if record.covers:
            covers_internal_id = ext_id_map.get(record.covers)
            if covers_internal_id:
                hints.append((asset_internal_id, covers_internal_id, RelationshipType.secures))

        for from_id, to_id, rel_type in hints:
            try:
                # Avoid duplicate relationships
                existing_rel = session.exec(
                    select(AssetRelationship).where(
                        AssetRelationship.tenant_id == tenant_id,
                        AssetRelationship.from_asset_id == from_id,
                        AssetRelationship.to_asset_id == to_id,
                        AssetRelationship.relationship_type == rel_type,
                    )
                ).first()
                if not existing_rel:
                    rel = AssetRelationship(
                        tenant_id=tenant_id,
                        from_asset_id=from_id,
                        to_asset_id=to_id,
                        relationship_type=rel_type,
                    )
                    session.add(rel)
                    session.commit()
            except Exception:
                session.rollback()

    return {"imported": imported, "updated": updated, "failed": failed}
