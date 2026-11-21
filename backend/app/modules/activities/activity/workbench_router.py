"""Authenticated workbench HTTP surface with route-specific scopes."""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Security
from sqlalchemy.orm import Session

import core.database as database
import core.dependencies as core_dependencies
import core.rate_limit as rate_limit
import modules.activities.activity.workbench_schema as schema
import modules.activities.activity.workbench_service as service
import modules.auth.dependencies as auth

router = APIRouter()


@router.get("/vehicles/{vehicle_uuid}", response_model=schema.VehicleUsageRead)
def read_vehicle(
    vehicle_uuid: UUID,
    _scope: Annotated[Callable, Security(auth.check_auth_scopes, scopes=["workbench:read"])],
    user_id: Annotated[int, Depends(auth.get_user_id_from_auth)],
    db: Annotated[Session, Depends(database.get_db)],
) -> schema.VehicleUsageRead:
    """Read a complete current vehicle projection for the credential owner."""
    return service.read_vehicle(user_id, str(vehicle_uuid), db)


@router.put("/vehicles/{vehicle_uuid}", response_model=schema.VehicleMappingRead)
@rate_limit.limiter.limit(rate_limit.WRITE)
def map_vehicle(
    request: Request,
    vehicle_uuid: UUID,
    body: schema.VehicleMappingEdit,
    _scope: Annotated[Callable, Security(auth.check_auth_scopes, scopes=["gears:write"])],
    user_id: Annotated[int, Depends(auth.get_user_id_from_auth)],
    db: Annotated[Session, Depends(database.get_db)],
) -> schema.VehicleMappingRead:
    """Explicitly map an existing owned gear without modifying its fields."""
    return service.map_vehicle(user_id, str(vehicle_uuid), body, db)


@router.get("/assets/{asset_id}/usage", response_model=schema.AssetUsageRead)
def read_asset(
    asset_id: UUID,
    _scope: Annotated[Callable, Security(auth.check_auth_scopes, scopes=["workbench:read"])],
    user_id: Annotated[int, Depends(auth.get_user_id_from_auth)],
    db: Annotated[Session, Depends(database.get_db)],
) -> schema.AssetUsageRead:
    """Read current use of one physical identity across the owner's activities."""
    return service.read_asset(user_id, str(asset_id), db)


@router.get("/equipment-candidates", response_model=schema.EquipmentCandidatesRead)
def equipment_candidates(
    _scope: Annotated[Callable, Security(auth.check_auth_scopes, scopes=["activities:read"])],
    user_id: Annotated[int, Depends(auth.get_user_id_from_auth)],
    catalogue: Annotated[Callable[[int], dict], Depends(core_dependencies.get_household_catalogue)],
) -> schema.EquipmentCandidatesRead:
    """Read the explicitly authorized household catalogue for the activity editor."""
    return service.list_equipment(user_id, catalogue)


@router.get("/vehicle-mappings/{vehicle_uuid}", response_model=schema.VehicleMappingRead)
def read_mapping(
    vehicle_uuid: UUID,
    _scope: Annotated[Callable, Security(auth.check_auth_scopes, scopes=["gears:read"])],
    user_id: Annotated[int, Depends(auth.get_user_id_from_auth)],
    db: Annotated[Session, Depends(database.get_db)],
) -> schema.VehicleMappingRead:
    """Read an editable mapping revision owned by the authenticated principal."""
    return service.read_mapping(user_id, str(vehicle_uuid), db)
