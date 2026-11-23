"""Minimal, owner-scoped workbench projections."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VehicleMappingEdit(BaseModel):
    """Explicitly associate an existing vehicle without changing its gear."""

    model_config = ConfigDict(extra="forbid")
    instance_id: str = Field(min_length=1, max_length=100)
    gear_id: int = Field(gt=0)
    excluded_activity_ids: list[int] = Field(default_factory=list, max_length=1000)
    revision: int | None = Field(default=None, gt=0)


class VehicleMappingRead(BaseModel):
    """An owned stable vehicle mapping."""

    model_config = ConfigDict(from_attributes=True)
    vehicle_uuid: UUID
    instance_id: str
    gear_id: int
    revision: int


class WorkbenchActivity(BaseModel):
    """The measurements needed for maintenance, without location or health."""

    activity_id: int
    revision: int
    start_time: datetime | None
    timezone: str | None
    gear_id: int | None
    vehicle_uuid: UUID | None = None
    distance_m: float | None
    timer_seconds: float | None
    elapsed_seconds: float | None
    use_mode: Literal["carried", "used"] | None = None


class WorkbenchGear(BaseModel):
    """An original gear value, never an automatic price projection."""

    gear_id: int
    name: str
    purchase_value: float | None
    currency: str | None = None
    initial_kms: float | None = None


class WorkbenchExcluded(BaseModel):
    """Disjoint synthetic exclusions; stable IDs take priority over names."""

    count: int
    reasons: dict[str, int]


class WorkbenchCoverage(BaseModel):
    """Database completeness is separate from lifetime history completeness."""

    activity_count: int
    excluded_count: int
    first_activity_at: datetime | None
    last_activity_at: datetime | None
    history_complete: Literal[False] = False


class VehicleUsageRead(BaseModel):
    """A complete current vehicle projection from the activity owner."""

    schema_version: Literal[1] = 1
    instance_id: str
    vehicle_uuid: UUID
    revision: str
    observed_at: datetime
    complete: Literal[True] = True
    gear: WorkbenchGear
    activities: list[WorkbenchActivity]
    excluded: WorkbenchExcluded
    coverage: WorkbenchCoverage


class EquipmentSelection(BaseModel):
    """An explicit physical item carried or used during one activity."""

    model_config = ConfigDict(extra="forbid")
    asset_id: UUID
    use_mode: Literal["carried", "used"]


class EquipmentEdit(BaseModel):
    """A confirmed set, or an explicitly unknown equipment state."""

    model_config = ConfigDict(extra="forbid")
    confirmed: bool
    items: list[EquipmentSelection] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_set(self):
        """Reject ambiguous duplicates and unconfirmed actual-use claims."""
        ids = [item.asset_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("An asset may appear only once per activity")
        if not self.confirmed and self.items:
            raise ValueError("Unconfirmed equipment must have no selections")
        return self


class EquipmentCandidate(BaseModel):
    """An allowed physical identity from the household authority."""

    asset_id: UUID
    label: str
    status: Literal["active", "retired"]


class EquipmentCandidatesRead(BaseModel):
    """A bounded household response with source revision and observation time."""

    schema_version: Literal[1] = 1
    observed_at: datetime
    revision: str
    items: list[EquipmentCandidate]


class AssetUsageRead(BaseModel):
    """Complete current activity use of one physical item across vehicles."""

    schema_version: Literal[1] = 1
    instance_id: str
    asset_id: UUID
    revision: str
    observed_at: datetime
    complete: Literal[True] = True
    activities: list[WorkbenchActivity]
    excluded: WorkbenchExcluded
    coverage: WorkbenchCoverage


IntervalsSyncState = Literal["idle", "running", "unknown"]
IntervalsSyncResult = Literal["ok", "partial", "missing_key", "auth_rejected", "list_failed", "error"]
IntervalsSyncTrigger = Literal["manual", "scheduled"]
IntervalsSyncDeleteResult = Literal["ok", "not_found", "rejected", "failed", "pending"]


class IntervalsSyncDisabledRead(BaseModel):
    """Response when intervals.icu sync is disabled or not visible to the caller."""

    enabled: Literal[False] = False


class IntervalsSyncCountsRead(BaseModel):
    """Whitelisted integer activity counters from the latest intervals.icu sync run."""

    done: int
    failed: int
    gave_up: int
    skipped: int
    pending: int


class IntervalsSyncLastDeleteRead(BaseModel):
    """Whitelisted summary of the latest intervals.icu delete execution."""

    requested_at: datetime | None = None
    finished_at: datetime | None = None
    result: IntervalsSyncDeleteResult
    activity_id: int


class IntervalsSyncStatusRead(BaseModel):
    """Whitelisted status summary of the host intervals.icu sync bridge."""

    enabled: Literal[True] = True
    state: IntervalsSyncState
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_result: IntervalsSyncResult | None = None
    counts: IntervalsSyncCountsRead | None = None
    trigger: IntervalsSyncTrigger | None = None
    last_requested_at: datetime | None = None
    request_pending: bool = False
    last_delete: IntervalsSyncLastDeleteRead | None = None
    pending_deletes: int = 0


class IntervalsSyncRequestAcceptedRead(BaseModel):
    """Confirmation that a manual intervals.icu sync request was written to the bridge."""

    accepted: Literal[True] = True
    requested_at: datetime


class IntervalsSyncActivityRead(BaseModel):
    """Lookup result indicating whether an activity was imported from intervals.icu."""

    intervals_id: str | None = None


class IntervalsSyncDeleteRequestCreate(BaseModel):
    """Request payload to queue an intervals.icu deletion for an imported activity."""

    model_config = ConfigDict(extra="forbid")
    activity_id: int = Field(gt=0)


class IntervalsSyncDeleteRequestRead(BaseModel):
    """Confirmation for a queued or already pending intervals.icu delete request."""

    accepted: Literal[True] = True
    request_id: str
    intervals_id: str
