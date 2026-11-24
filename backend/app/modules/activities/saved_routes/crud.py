"""Persistence primitives for saved routes; transactions belong to the service."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.activities.saved_routes.models import SavedRoute, SavedRouteTrip


def by_activity(owner: int, activity_id: int, db: Session) -> SavedRoute | None:
    """Find a snapshot by its owner and original activity."""
    return db.scalar(
        select(SavedRoute).where(SavedRoute.user_id == owner, SavedRoute.source_activity_id == activity_id)
    )


def add_snapshot(owner: int, source: int, name: str, sport: int, points: list, db: Session) -> SavedRoute:
    """Stage the snapshot including immutable geometry."""
    route = SavedRoute(
        user_id=owner,
        source_activity_id=source,
        name=name,
        activity_type=sport,
        geometry=points,
        point_count=len(points),
    )
    db.add(route)
    return route


def all_routes(owner: int, db: Session) -> list[SavedRoute]:
    """List owned metadata without fetching the geometry column."""
    return list(db.scalars(select(SavedRoute).where(SavedRoute.user_id == owner).order_by(SavedRoute.id.desc())))


def lock_route(owner: int, route_id: int, db: Session) -> SavedRoute | None:
    """Serialize sends of each owned snapshot."""
    return db.scalar(select(SavedRoute).where(SavedRoute.id == route_id, SavedRoute.user_id == owner).with_for_update())


def receipt_for(route: int, trip: int, db: Session) -> SavedRouteTrip | None:
    """Look up a previously acknowledged transfer."""
    return db.get(SavedRouteTrip, (route, trip))


def store_receipt(route: int, trip: int, tour: int | None, count: int, db: Session) -> None:
    """Stage a receipt in the transaction holding the route lock."""
    db.add(SavedRouteTrip(route_id=route, trip_id=trip, tour_id=tour, sent_points=count))
