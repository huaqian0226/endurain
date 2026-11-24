"""Reusable route geometry and acknowledgements from TREK."""

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class SavedRoute(Base):
    """Owner's reusable geometry snapshot, independent of the original activity."""

    __tablename__ = "workbench_saved_routes"
    __table_args__ = (UniqueConstraint("user_id", "source_activity_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source_activity_id: Mapped[int | None] = mapped_column(ForeignKey("activities.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(160))
    activity_type: Mapped[int]
    point_count: Mapped[int]
    geometry: Mapped[list] = mapped_column(JSON, deferred=True)


class SavedRouteTrip(Base):
    """Receipt for a route sent to a specific TREK trip."""

    __tablename__ = "workbench_saved_route_trips"
    route_id: Mapped[int] = mapped_column(ForeignKey("workbench_saved_routes.id", ondelete="CASCADE"), primary_key=True)
    trip_id: Mapped[int] = mapped_column(primary_key=True)
    tour_id: Mapped[int | None]
    sent_points: Mapped[int]
