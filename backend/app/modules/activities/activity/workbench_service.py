"""Owner-scoped workbench projections and mapping transactions."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

import core.config as config
import core.exceptions as errors
import core.logger as core_logger
import modules.activities.activity.workbench_crud as crud
import modules.activities.activity.workbench_schema as schema
import modules.gears.gear.integration_service as gears

logger = core_logger.get_logger(__name__)


def map_vehicle(
    user_id: int, vehicle_uuid: str, body: schema.VehicleMappingEdit, db: Session
) -> schema.VehicleMappingRead:
    """Associate an owned existing gear and commit the reference only."""
    if gears.read_owned_gear(user_id, body.gear_id, db) is None:
        raise errors.NotFoundError("Gear not found")
    result = crud.store_mapping(user_id, vehicle_uuid, body, db)
    db.commit()
    logger.info("Stored vehicle mapping", extra=core_logger.context(user_id=user_id, vehicle_uuid=vehicle_uuid))
    return result


def read_vehicle(user_id: int, vehicle_uuid: str, db: Session) -> schema.VehicleUsageRead:
    """Return the current complete activity projection and original gear values."""
    ref, activities, excluded = crud.vehicle_activities(
        user_id, vehicle_uuid, db, fixed_exclusions=config.settings.WORKBENCH_EXCLUDED_ACTIVITY_IDS
    )
    gear = gears.read_owned_gear(user_id, ref.gear_id, db)
    if gear is None:
        raise errors.NotFoundError("Gear not found")
    times = [a.start_time for a in activities if a.start_time is not None]
    body = schema.VehicleUsageRead(
        instance_id=ref.instance_id,
        vehicle_uuid=ref.vehicle_uuid,
        revision="pending",
        observed_at=datetime.now(UTC),
        gear=schema.WorkbenchGear(gear_id=gear.id, name=gear.nickname, purchase_value=gear.purchase_value),
        activities=activities,
        excluded=excluded,
        coverage=schema.WorkbenchCoverage(
            activity_count=len(activities),
            excluded_count=excluded.count,
            first_activity_at=min(times) if times else None,
            last_activity_at=max(times) if times else None,
        ),
    )
    digest = body.model_dump(mode="json", exclude={"observed_at", "revision"})
    body.revision = hashlib.sha256(json.dumps(digest, sort_keys=True).encode()).hexdigest()
    return body


def list_equipment(user_id: int, catalogue: Callable[[int], dict] | None) -> schema.EquipmentCandidatesRead:
    """Expose only allowed physical identities, retaining authority metadata."""
    if catalogue is None:
        raise errors.CatalogueUnavailableError()
    envelope = catalogue(user_id)
    try:
        items = [
            schema.EquipmentCandidate.model_validate(
                {key: row["asset"][key] for key in ("asset_id", "label", "status")}
            )
            for row in envelope["items"]
            if isinstance(row, dict) and row.get("result") == "ok"
        ]
        if len({item.asset_id for item in items}) != len(items):
            raise ValueError("Duplicate authority identities")
        return schema.EquipmentCandidatesRead(
            observed_at=envelope["observed_at"], revision=str(envelope["revision"]), items=items
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise errors.CatalogueUnavailableError() from exc


def validate_equipment(user_id: int, selection: schema.EquipmentEdit, catalogue: Callable[[int], dict] | None) -> str:
    """Validate selected physical identities against the live allowed catalogue."""
    if not selection.items:
        return "explicit-empty"
    candidates = list_equipment(user_id, catalogue)
    allowed = {item.asset_id for item in candidates.items}
    if any(item.asset_id not in allowed for item in selection.items):
        raise errors.InvalidInputError("An equipment identity is unavailable or not allowed")
    return candidates.revision


def read_asset(user_id: int, asset_id: str, db: Session) -> schema.AssetUsageRead:
    """Return complete current owner use of a shared physical item."""
    instance_id, activities, excluded = crud.asset_activities(
        user_id, asset_id, db, fixed_exclusions=config.settings.WORKBENCH_EXCLUDED_ACTIVITY_IDS
    )
    times = [a.start_time for a in activities if a.start_time is not None]
    body = schema.AssetUsageRead(
        instance_id=instance_id,
        asset_id=asset_id,
        revision="pending",
        observed_at=datetime.now(UTC),
        activities=activities,
        excluded=excluded,
        coverage=schema.WorkbenchCoverage(
            activity_count=len(activities),
            excluded_count=excluded.count,
            first_activity_at=min(times) if times else None,
            last_activity_at=max(times) if times else None,
        ),
    )
    body.revision = hashlib.sha256(
        json.dumps(body.model_dump(mode="json", exclude={"observed_at", "revision"}), sort_keys=True).encode()
    ).hexdigest()
    return body


def read_mapping(user_id: int, vehicle_uuid: str, db: Session) -> schema.VehicleMappingRead:
    """Expose the owned mapping's edit revision separately from usage hashes."""
    return crud.read_mapping(user_id, vehicle_uuid, db)
