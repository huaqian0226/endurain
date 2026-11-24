"""Gear database models."""

from datetime import date as date_type
from datetime import datetime as datetime_type
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from core.database import Base

if TYPE_CHECKING:
    from modules.gears.gear_components.models import GearComponents
    from modules.users.users.models import Users
    from modules.users.users_default_gear.models import UsersDefaultGear


class Gear(Base):
    """
    Gear data model.

    Attributes:
        id: Primary key.
        brand: Gear brand name.
        model: Gear model name.
        nickname: Gear nickname.
        group_name: Optional user-defined gear group name.
        gear_type: Gear type identifier.
        user_id: Foreign key to users table.
        created_at: Gear creation timestamp.
        active: Whether the gear is active.
        initial_kms: Initial kilometers.
        purchase_value: Gear purchase value.
        purchase_date: Gear purchase date (calendar date).
        retired_date: Gear retired date (calendar date).
        frame_number: Frame or serial number.
        size: Frame or gear size.
        color: Gear color.
        model_year: Retail model year (distinct from manufacture date).
        groupset: Groupset or drivetrain specification.
        specs: Additional gear specifications (multiline).
        purchase_source: Where the gear was purchased or acquired.
        notes: Free-form notes and history (multiline).
        strava_gear_id: Strava gear ID.
        garminconnect_gear_id: Garmin gear ID.
        users: Relationship to Users model.
        gear_components: Components relationship.
        users_default_run_gear: Default run gear.
        users_default_trail_run_gear: Trail run.
        users_default_virtual_run_gear: Virtual run.
        users_default_ride_gear: Default ride.
        users_default_gravel_ride_gear: Gravel ride.
        users_default_mtb_ride_gear: MTB ride.
        users_default_virtual_ride_gear: Virtual ride.
        users_default_ows_gear: Open water swim.
        users_default_walk_gear: Default walk gear.
        users_default_hike_gear: Default hike gear.
        users_default_tennis_gear: Tennis gear.
        users_default_alpine_ski_gear: Alpine ski.
        users_default_nordic_ski_gear: Nordic ski.
        users_default_snowboard_gear: Snowboard.
        users_default_windsurf_gear: Windsurf.
    """

    __tablename__ = "gear"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        autoincrement=True,
    )
    brand: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
        comment="Gear brand (May include spaces)",
    )
    model: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
        comment="Gear model (May include spaces)",
    )
    nickname: Mapped[str] = mapped_column(
        String(250),
        index=True,
        nullable=False,
        comment=("Gear nickname (May include spaces)"),
    )
    group_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Optional user-defined gear group name",
    )
    gear_type: Mapped[int] = mapped_column(
        nullable=False,
        comment=(
            "Gear type (1 - bike, 2 - shoes,"
            " 3 - wetsuit, 4 - racquet,"
            " 5 - skis, 6 - snowboard,"
            " 7 - windsurf,"
            " 8 - water sports board)"
        ),
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment=("User ID that the gear belongs to"),
    )
    created_at: Mapped[datetime_type] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        comment="Gear creation date (DateTime)",
    )
    active: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        comment=("Whether the gear is active (true - yes, false - no)"),
    )
    initial_kms: Mapped[Decimal] = mapped_column(
        Numeric(precision=11, scale=2),
        nullable=False,
        default=0,
        comment=("Initial kilometers of the gear"),
    )
    purchase_value: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=11, scale=2),
        nullable=True,
        comment="Gear purchase value",
    )
    purchase_date: Mapped[date_type | None] = mapped_column(
        Date(),
        nullable=True,
        comment="Gear purchase date (Date)",
    )
    retired_date: Mapped[date_type | None] = mapped_column(
        Date(),
        nullable=True,
        comment="Gear retired date (Date)",
    )
    frame_number: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Gear frame or serial number",
    )
    size: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Gear size",
    )
    color: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Gear color",
    )
    model_year: Mapped[int | None] = mapped_column(
        SmallInteger(),
        nullable=True,
        comment="Gear retail model year",
    )
    groupset: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
        comment="Gear groupset or drivetrain",
    )
    specs: Mapped[str | None] = mapped_column(
        Text(),
        nullable=True,
        comment="Additional gear specifications (multiline)",
    )
    purchase_source: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
        comment="Gear purchase or acquisition source",
    )
    notes: Mapped[str | None] = mapped_column(
        Text(),
        nullable=True,
        comment="Gear notes and history (multiline)",
    )
    strava_gear_id: Mapped[str | None] = mapped_column(
        String(45),
        unique=True,
        nullable=True,
        comment="Strava gear ID",
    )
    garminconnect_gear_id: Mapped[str | None] = mapped_column(
        String(45),
        unique=True,
        nullable=True,
        comment="Garmin Connect gear ID",
    )

    # Define a relationship to the Users model
    users: Mapped["Users"] = relationship(back_populates="gear")
    # Establish a one-to-many relationship with 'gear_components'
    gear_components: Mapped[list["GearComponents"]] = relationship(
        back_populates="gear",
        cascade="all, delete-orphan",
        foreign_keys="[GearComponents.gear_id]",
    )
    # Establish a one-to-many relationship with 'users_default_gear'
    users_default_run_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="run_gear",
        foreign_keys="[UsersDefaultGear.run_gear_id]",
    )
    users_default_trail_run_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="trail_run_gear",
        foreign_keys="[UsersDefaultGear.trail_run_gear_id]",
    )
    users_default_virtual_run_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="virtual_run_gear",
        foreign_keys="[UsersDefaultGear.virtual_run_gear_id]",
    )
    users_default_ride_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="ride_gear",
        foreign_keys="[UsersDefaultGear.ride_gear_id]",
    )
    users_default_gravel_ride_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="gravel_ride_gear",
        foreign_keys="[UsersDefaultGear.gravel_ride_gear_id]",
    )
    users_default_mtb_ride_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="mtb_ride_gear",
        foreign_keys="[UsersDefaultGear.mtb_ride_gear_id]",
    )
    users_default_virtual_ride_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="virtual_ride_gear",
        foreign_keys="[UsersDefaultGear.virtual_ride_gear_id]",
    )
    users_default_ows_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="ows_gear",
        foreign_keys="[UsersDefaultGear.ows_gear_id]",
    )
    users_default_walk_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="walk_gear",
        foreign_keys="[UsersDefaultGear.walk_gear_id]",
    )
    users_default_hike_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="hike_gear",
        foreign_keys="[UsersDefaultGear.hike_gear_id]",
    )
    users_default_tennis_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="tennis_gear",
        foreign_keys="[UsersDefaultGear.tennis_gear_id]",
    )
    users_default_alpine_ski_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="alpine_ski_gear",
        foreign_keys="[UsersDefaultGear.alpine_ski_gear_id]",
    )
    users_default_nordic_ski_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="nordic_ski_gear",
        foreign_keys="[UsersDefaultGear.nordic_ski_gear_id]",
    )
    users_default_snowboard_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="snowboard_gear",
        foreign_keys="[UsersDefaultGear.snowboard_gear_id]",
    )
    users_default_windsurf_gear: Mapped[list["UsersDefaultGear"]] = relationship(
        back_populates="windsurf_gear",
        foreign_keys="[UsersDefaultGear.windsurf_gear_id]",
    )
