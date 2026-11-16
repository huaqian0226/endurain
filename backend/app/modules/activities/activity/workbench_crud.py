"""Persistence for explicit workbench mappings and activity projections."""

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import core.exceptions as errors
import modules.activities.activity.models as models
import modules.activities.activity.workbench_schema as schema


def store_mapping(
    user_id: int, vehicle_uuid: str, body: schema.VehicleMappingEdit, db: Session
) -> schema.VehicleMappingRead:
    """Stage an explicit mapping, preserving the referenced gear."""
    existing = db.get(models.WorkbenchVehicle, vehicle_uuid)
    if existing is not None and existing.user_id != user_id:
        raise errors.NotFoundError("Vehicle mapping not found")
    occupied = db.scalar(
        select(models.WorkbenchVehicle).where(
            models.WorkbenchVehicle.user_id == user_id,
            models.WorkbenchVehicle.gear_id == body.gear_id,
            models.WorkbenchVehicle.vehicle_uuid != vehicle_uuid,
        )
    )
    if occupied is not None:
        raise errors.ConflictError("Gear already has a vehicle mapping")
    instances = db.scalars(
        select(models.WorkbenchVehicle.instance_id).where(
            models.WorkbenchVehicle.user_id == user_id,
        )
    ).all()
    if any(instance != body.instance_id for instance in instances):
        raise errors.ConflictError("The owner already has a different instance identity")
    if existing is None:
        if body.revision is not None:
            raise errors.ConflictError("Mapping no longer exists")
        existing = models.WorkbenchVehicle(
            vehicle_uuid=vehicle_uuid,
            user_id=user_id,
            gear_id=body.gear_id,
            instance_id=body.instance_id,
            excluded_activity_ids=body.excluded_activity_ids,
        )
        db.add(existing)
    else:
        if body.revision != existing.revision:
            raise errors.PreconditionFailedError("Re-read the vehicle mapping before updating")
        existing.gear_id = body.gear_id
        existing.excluded_activity_ids = sorted(set(existing.excluded_activity_ids) | set(body.excluded_activity_ids))
    db.flush()
    return schema.VehicleMappingRead.model_validate(existing)


def vehicle_activities(
    user_id: int, vehicle_uuid: str, db: Session, *, fixed_exclusions: list[int]
) -> tuple[schema.VehicleMappingRead, list[schema.WorkbenchActivity], schema.WorkbenchExcluded]:
    """Read a mapping and its entire activity set in one database statement."""
    mapping = models.WorkbenchVehicle
    activity = models.Activity
    rows = db.execute(
        select(mapping, activity)
        .outerjoin(activity, (activity.gear_id == mapping.gear_id) & (activity.user_id == mapping.user_id))
        .where(mapping.vehicle_uuid == vehicle_uuid, mapping.user_id == user_id)
        .order_by(activity.id)
    ).all()
    if not rows:
        raise errors.NotFoundError("Vehicle mapping not found")
    ref = rows[0][0]
    excluded_ids = _excluded_ids(user_id, db, fixed_exclusions=fixed_exclusions)
    items = []
    reasons = {"synthetic_id": 0, "synthetic_name": 0}
    for _, record in rows:
        if record is None:
            continue
        if record.id in excluded_ids:
            reasons["synthetic_id"] += 1
        elif "DEMO" in record.name.upper() or "SYNTHETIC" in record.name.upper():
            reasons["synthetic_name"] += 1
        else:
            items.append(_activity_projection(record, vehicle_uuid))
    return (
        schema.VehicleMappingRead.model_validate(ref),
        items,
        schema.WorkbenchExcluded(count=sum(reasons.values()), reasons=reasons),
    )


def _activity_projection(record: models.Activity, vehicle_uuid: str | None) -> schema.WorkbenchActivity:
    instant = record.start_time
    if isinstance(instant, datetime) and instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return schema.WorkbenchActivity(
        activity_id=record.id,
        revision=record.version,
        start_time=instant,
        timezone=record.timezone,
        gear_id=record.gear_id,
        vehicle_uuid=vehicle_uuid,
        distance_m=record.distance,
        timer_seconds=record.total_timer_time,
        elapsed_seconds=record.total_elapsed_time,
    )


def equipment_for_activity(activity_id: int, db: Session) -> list[schema.EquipmentSelection]:
    """Read selected identities after the activity owner has been authorized."""
    rows = db.scalars(
        select(models.ActivityEquipment)
        .where(
            models.ActivityEquipment.activity_id == activity_id,
        )
        .order_by(models.ActivityEquipment.asset_id)
    ).all()
    return [schema.EquipmentSelection(asset_id=row.asset_id, use_mode=row.use_mode) for row in rows]


def replace_equipment(activity_id: int, selection: schema.EquipmentEdit, catalog_revision: str, db: Session) -> None:
    """Stage the exact confirmed set in the parent activity edit transaction."""
    db.execute(delete(models.ActivityEquipment).where(models.ActivityEquipment.activity_id == activity_id))
    for item in selection.items:
        db.add(
            models.ActivityEquipment(
                activity_id=activity_id,
                asset_id=str(item.asset_id),
                use_mode=item.use_mode,
                catalog_revision=catalog_revision,
                confirmed_at=datetime.now(UTC).isoformat(),
            )
        )
    db.flush()


def asset_activities(
    user_id: int, asset_id: str, db: Session, *, fixed_exclusions: list[int]
) -> tuple[str, list[schema.WorkbenchActivity], schema.WorkbenchExcluded]:
    """Read one owned asset's use, with each activity contributing once."""
    mapping = models.WorkbenchVehicle
    activity = models.Activity
    equipment = models.ActivityEquipment
    mappings = db.scalars(select(mapping).where(mapping.user_id == user_id)).all()
    if not mappings:
        raise errors.NotFoundError("No instance identity configured")
    excluded_ids = _excluded_ids(user_id, db, fixed_exclusions=fixed_exclusions)
    rows = db.execute(
        select(activity, equipment.use_mode, mapping.vehicle_uuid)
        .join(equipment, equipment.activity_id == activity.id)
        .outerjoin(mapping, (mapping.gear_id == activity.gear_id) & (mapping.user_id == activity.user_id))
        .where(activity.user_id == user_id, equipment.asset_id == asset_id, activity.equipment_confirmed.is_(True))
        .order_by(activity.id)
    ).all()
    items = []
    reasons = {"synthetic_id": 0, "synthetic_name": 0}
    for record, mode, vehicle_uuid in rows:
        if record.id in excluded_ids:
            reasons["synthetic_id"] += 1
        elif "DEMO" in record.name.upper() or "SYNTHETIC" in record.name.upper():
            reasons["synthetic_name"] += 1
        else:
            item = _activity_projection(record, vehicle_uuid)
            item.use_mode = mode
            items.append(item)
    return mappings[0].instance_id, items, schema.WorkbenchExcluded(count=sum(reasons.values()), reasons=reasons)


def _excluded_ids(user_id: int, db: Session, *, fixed_exclusions: list[int]) -> set[int]:
    """Apply instance exclusions across all vehicles, including renamed activities."""
    lists = db.scalars(
        select(models.WorkbenchVehicle.excluded_activity_ids).where(models.WorkbenchVehicle.user_id == user_id)
    ).all()
    return set(fixed_exclusions) | {item for ids in lists for item in ids}


def read_mapping(user_id: int, vehicle_uuid: str, db: Session) -> schema.VehicleMappingRead:
    """Read the owned mapping revision so a conflicted update can be retried."""
    mapping = db.scalar(
        select(models.WorkbenchVehicle).where(
            models.WorkbenchVehicle.vehicle_uuid == vehicle_uuid, models.WorkbenchVehicle.user_id == user_id
        )
    )
    if mapping is None:
        raise errors.NotFoundError("Vehicle mapping not found")
    return schema.VehicleMappingRead.model_validate(mapping)
