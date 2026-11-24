"""Gear schema definitions."""

from datetime import date as date_type
from datetime import datetime as datetime_type
from enum import IntEnum
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)


class GearType(IntEnum):
    """
    Supported gear type codes.

    Attributes:
        BIKE: Bicycle (1).
        SHOES: Running or walking shoes (2).
        WETSUIT: Wetsuit (3).
        RACQUET: Racquet (4).
        SKI: Skis (5).
        SNOWBOARD: Snowboard (6).
        WINDSURF: Windsurf board (7).
        WATER_SPORTS_BOARD: Water sports board (8).
    """

    BIKE = 1
    SHOES = 2
    WETSUIT = 3
    RACQUET = 4
    SKI = 5
    SNOWBOARD = 6
    WINDSURF = 7
    WATER_SPORTS_BOARD = 8


class GearBase(BaseModel):
    """
    Base model for gear data.

    Attributes:
        brand: Gear brand name.
        model: Gear model name.
        nickname: Gear display nickname.
        group_name: Optional user-defined gear group name.
        gear_type: Gear type identifier.
        created_at: Gear creation timestamp.
        active: Whether the gear is active.
        initial_kms: Initial kilometers.
        purchase_value: Purchase value.
        purchase_date: Purchase date (calendar date).
        retired_date: Retired date (calendar date).
        frame_number: Frame or serial number.
        size: Frame or gear size.
        color: Gear color.
        model_year: Retail model year (1900-2100).
        groupset: Groupset or drivetrain specification.
        specs: Additional gear specifications (multiline).
        purchase_source: Purchase or acquisition source.
        notes: Free-form notes and history (multiline).
        strava_gear_id: Strava gear ID.
        garminconnect_gear_id: Garmin gear ID.
    """

    brand: StrictStr | None = Field(
        default=None,
        max_length=250,
        description="Gear brand name",
    )
    model: StrictStr | None = Field(
        default=None,
        max_length=250,
        description="Gear model name",
    )
    nickname: StrictStr = Field(
        ...,
        max_length=250,
        description="Gear display nickname",
    )
    group_name: StrictStr | None = Field(
        default=None,
        max_length=100,
        description="Optional gear group name",
    )
    gear_type: GearType = Field(
        ...,
        description="Gear type identifier",
    )
    created_at: datetime_type | None = Field(
        default=None,
        description="Gear creation timestamp",
    )
    active: StrictBool | None = Field(
        default=None,
        description="Whether the gear is active",
    )
    initial_kms: StrictFloat | None = Field(
        default=None,
        ge=0,
        description="Initial kilometers",
    )
    purchase_value: StrictFloat | None = Field(
        default=None,
        ge=0,
        description="Purchase value",
    )
    purchase_date: date_type | None = Field(
        default=None,
        description="Gear purchase date",
    )
    retired_date: date_type | None = Field(
        default=None,
        description="Gear retired date",
    )
    frame_number: StrictStr | None = Field(
        default=None,
        max_length=100,
        description="Frame or serial number",
    )
    size: StrictStr | None = Field(
        default=None,
        max_length=50,
        description="Gear size",
    )
    color: StrictStr | None = Field(
        default=None,
        max_length=100,
        description="Gear color",
    )
    model_year: StrictInt | None = Field(
        default=None,
        ge=1900,
        le=2100,
        description="Retail model year",
    )
    groupset: StrictStr | None = Field(
        default=None,
        max_length=250,
        description="Groupset or drivetrain specification",
    )
    specs: StrictStr | None = Field(
        default=None,
        max_length=4000,
        description="Additional specifications (multiline)",
    )
    purchase_source: StrictStr | None = Field(
        default=None,
        max_length=250,
        description="Purchase or acquisition source",
    )
    notes: StrictStr | None = Field(
        default=None,
        max_length=8000,
        description="Notes and history (multiline)",
    )
    strava_gear_id: StrictStr | None = Field(
        default=None,
        max_length=45,
        description="Strava gear ID",
    )
    garminconnect_gear_id: StrictStr | None = Field(
        default=None,
        max_length=45,
        description="Garmin Connect gear ID",
    )

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        validate_assignment=True,
    )

    @field_validator(
        "group_name",
        "frame_number",
        "size",
        "color",
        "groupset",
        "specs",
        "purchase_source",
        "notes",
        mode="before",
    )
    @classmethod
    def _normalize_optional_profile_text(cls, value: object) -> object:
        """Trim surrounding whitespace and convert blank profile text to None."""
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @model_validator(mode="after")
    def _validate_retired_not_before_purchase(self) -> Self:
        """Ensure retired_date is on or after purchase_date when both are set."""
        if self.purchase_date is not None and self.retired_date is not None and self.retired_date < self.purchase_date:
            raise ValueError("retired_date must be on or after purchase_date")
        return self


class GearCreate(GearBase):
    """
    Schema for creating a gear record.

    Attributes:
        user_id: Foreign key to user.
    """

    user_id: StrictInt | None = Field(
        default=None,
        description="Foreign key to user",
    )


class _GearIdentity(GearBase):
    """
    Persisted gear fields shared by read and detail schemas.

    Attributes:
        id: Unique identifier.
        user_id: Foreign key to user.
    """

    id: StrictInt = Field(
        ...,
        description="Unique identifier",
    )
    user_id: StrictInt = Field(
        ...,
        description="Foreign key to user",
    )


class GearRead(_GearIdentity):
    """
    Schema for reading a gear record.

    Attributes:
        total_distance: Optional total distance in meters (activities plus initial distance).
    """

    total_distance: StrictFloat | None = Field(
        default=None,
        ge=0,
        description="Total activity distance in meters (including initial distance)",
    )


class GearDetailRead(_GearIdentity):
    """
    Extended gear with computed stats.

    Attributes:
        total_distance: Total distance (m).
        total_time: Total time (seconds).
        total_components_cost: Sum of parts.
    """

    total_distance: StrictFloat = Field(
        default=0,
        ge=0,
        description=("Total activity distance in meters"),
    )
    total_time: StrictFloat = Field(
        default=0,
        ge=0,
        description=("Total activity time in seconds"),
    )
    total_components_cost: StrictFloat = Field(
        default=0,
        ge=0,
        description=("Sum of component purchase values"),
    )


class GearUpdate(GearBase):
    """
    Schema for updating a gear record.

    Attributes:
        id: Unique identifier.
    """

    id: StrictInt = Field(
        ...,
        description="Unique identifier",
    )


class GearsListResponse(BaseModel):
    """
    Response model for paginated gear listing.

    Attributes:
        total: Total number of gear records.
        num_records: Number of records returned.
        page_number: Current page number.
        records: List of gear records.
    """

    total: StrictInt = Field(
        ...,
        ge=0,
        description="Total number of gear records",
    )
    num_records: StrictInt | None = Field(
        default=None,
        ge=0,
        description="Number of records returned",
    )
    page_number: StrictInt | None = Field(
        default=None,
        ge=1,
        description="Current page number",
    )
    records: list[GearRead] = Field(
        ...,
        description="List of gear records",
    )

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        validate_assignment=True,
    )
