"""Owner-scoped routes for saved activity geometry and TREK Tours."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Security
from sqlalchemy.orm import Session

import core.database as database
import core.dependencies as dependencies
import core.rate_limit as rate_limit
import modules.activities.saved_routes.schema as schema
import modules.activities.saved_routes.service as saved
import modules.auth.dependencies as auth

router = APIRouter()


@router.put("/activities/{activity_id}/saved-route", response_model=schema.RouteRead)
@rate_limit.limiter.limit(rate_limit.WRITE)
def save_activity_route(
    request: Request,
    activity_id: dependencies.PositiveId,
    body: schema.RouteName,
    _scope: Annotated[Callable, Security(auth.check_auth_scopes, scopes=["activities:write"])],
    user_id: Annotated[int, Depends(auth.get_user_id_from_auth)],
    db: Annotated[Session, Depends(database.get_db)],
):
    """Save an owned activity as a reusable route."""
    return saved.save_route(user_id, activity_id, body.name, db)


@router.get("/saved-routes", response_model=list[schema.RouteRead])
def list_saved_routes(
    _scope: Annotated[Callable, Security(auth.check_auth_scopes, scopes=["activities:read"])],
    user_id: Annotated[int, Depends(auth.get_user_id_from_auth)],
    db: Annotated[Session, Depends(database.get_db)],
):
    """List the owner's saved routes."""
    return saved.routes_for(user_id, db)


@router.get("/route-trips", response_model=list[schema.TripChoice])
def list_route_trips(
    _scope: Annotated[Callable, Security(auth.check_auth_scopes, scopes=["activities:read"])],
    user_id: Annotated[int, Depends(auth.get_user_id_from_auth)],
    trek: Annotated[Callable, Depends(dependencies.get_trek_route_tool)],
):
    """List destinations for the connected TREK owner."""
    return saved.trip_choices(user_id, trek)


@router.post("/saved-routes/{route_id}/trips/{trip_id}", response_model=schema.SendResult)
@rate_limit.limiter.limit(rate_limit.WRITE)
def send_saved_route(
    request: Request,
    route_id: dependencies.PositiveId,
    trip_id: dependencies.PositiveId,
    _scope: Annotated[Callable, Security(auth.check_auth_scopes, scopes=["activities:write"])],
    user_id: Annotated[int, Depends(auth.get_user_id_from_auth)],
    db: Annotated[Session, Depends(database.get_db)],
    trek: Annotated[Callable, Depends(dependencies.get_trek_route_tool)],
):
    """Send a saved route into one selected trip's Tours."""
    return saved.send_route(user_id, route_id, trip_id, db, trek)
