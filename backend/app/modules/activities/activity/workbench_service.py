"""Owner-scoped workbench projections and mapping transactions."""

import contextlib
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

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


_INTERVALS_BRIDGE_MAX_BYTES = 65_536
_INTERVALS_IMPORTED_MAX_BYTES = 1_048_576
_INTERVALS_RUNNING_STALE_WINDOW = timedelta(minutes=30)
_INTERVALS_RECENT_REQUEST_WINDOW = timedelta(seconds=60)
_INTERVALS_ALLOWED_STATES = frozenset({"idle", "running"})
_INTERVALS_ALLOWED_TRIGGERS = frozenset({"manual", "scheduled"})
_INTERVALS_ALLOWED_RESULTS = frozenset({"ok", "partial", "missing_key", "auth_rejected", "list_failed", "error"})
_INTERVALS_ALLOWED_DELETE_RESULTS = frozenset({"ok", "not_found", "rejected", "failed", "pending"})
_INTERVALS_COUNT_KEYS = ("done", "failed", "gave_up", "skipped", "pending")
_INTERVALS_ID_RE = re.compile(r"i?[0-9]{1,20}")


@dataclass(frozen=True)
class _ParsedSyncStatus:
    """Validated fields extracted from the host bridge status file."""

    state: schema.IntervalsSyncState
    trigger: schema.IntervalsSyncTrigger | None
    started_at: datetime | None
    finished_at: datetime | None
    result: schema.IntervalsSyncResult | None
    counts: schema.IntervalsSyncCountsRead | None
    handled_request_id: str | None
    last_delete: schema.IntervalsSyncLastDeleteRead | None
    handled_delete_request_ids: frozenset[str]


@dataclass(frozen=True)
class _ParsedDeleteRequest:
    """Validated fields extracted from a bridge delete-request file."""

    request_id: str
    activity_id: int
    intervals_id: str
    requested_at: datetime


def _intervals_sync_root(user_id: int) -> Path | None:
    """Return the bridge root directory when the feature is configured for this owner."""
    sync_dir = config.settings.WORKBENCH_INTERVALS_SYNC_DIR
    owner_id = config.settings.WORKBENCH_INTERVALS_SYNC_USER_ID
    if owner_id is None:
        owner_id = config.settings.WORKBENCH_JIADANG_USER_ID
    if not sync_dir or not sync_dir.strip() or owner_id is None or user_id != owner_id:
        return None
    return Path(sync_dir)


def _read_bridge_json(path: Path, max_bytes: int = _INTERVALS_BRIDGE_MAX_BYTES) -> dict | None:
    """Read a bounded JSON object from the bridge directory, returning None on any error."""
    try:
        with path.open("rb") as fh:
            raw = fh.read(max_bytes + 1)
        if len(raw) > max_bytes:
            return None
        parsed = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _validate_intervals_id(value: object) -> str | None:
    """Return the validated intervals.icu activity id, or None if invalid."""
    if not isinstance(value, str) or not _INTERVALS_ID_RE.fullmatch(value):
        return None
    return value


def _parse_iso_utc(value: object) -> datetime | None:
    """Parse an ISO-8601 datetime string into a UTC-aware datetime, or None if invalid."""
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _parse_optional_iso_utc(value: object) -> tuple[bool, datetime | None]:
    """Parse an optional ISO-8601 datetime field, returning (is_valid, datetime_or_none)."""
    if value is None:
        return True, None
    parsed = _parse_iso_utc(value)
    return (parsed is not None), parsed


def _parse_sync_counts(raw_counts: object) -> tuple[bool, schema.IntervalsSyncCountsRead | None]:
    """Validate whitelisted non-negative integer counts, rejecting booleans and strings."""
    if raw_counts is None:
        return True, None
    if not isinstance(raw_counts, dict):
        return False, None
    values: dict[str, int] = {}
    for key in _INTERVALS_COUNT_KEYS:
        val = raw_counts.get(key)
        if type(val) is not int or val < 0:
            return False, None
        values[key] = val
    return True, schema.IntervalsSyncCountsRead(**values)


def _parse_last_delete(raw: object) -> schema.IntervalsSyncLastDeleteRead | None:
    """Validate whitelisted last_delete fields from status.json, returning None if invalid."""
    if not isinstance(raw, dict):
        return None
    result = raw.get("result")
    if not isinstance(result, str) or result not in _INTERVALS_ALLOWED_DELETE_RESULTS:
        return None
    activity_id = raw.get("activity_id")
    if type(activity_id) is not int or activity_id <= 0:
        return None
    requested_ok, requested_at = _parse_optional_iso_utc(raw.get("requested_at"))
    finished_ok, finished_at = _parse_optional_iso_utc(raw.get("finished_at"))
    if not (requested_ok and finished_ok):
        return None
    return schema.IntervalsSyncLastDeleteRead(
        requested_at=requested_at,
        finished_at=finished_at,
        result=cast(schema.IntervalsSyncDeleteResult, result),
        activity_id=activity_id,
    )


def _parse_handled_delete_ids(raw: object) -> frozenset[str]:
    """Extract validated handled delete request ids from status.json, defaulting to empty."""
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(item for item in raw if isinstance(item, str) and item.strip())


def _parse_status_file(path: Path) -> _ParsedSyncStatus | None:
    """Validate and extract whitelisted fields from status.json, or return None if corrupt."""
    data = _read_bridge_json(path)
    if data is None:
        return None

    schema_version = data.get("schema")
    if type(schema_version) is not int or schema_version != 1:
        return None

    state = data.get("state")
    if not isinstance(state, str) or state not in _INTERVALS_ALLOWED_STATES:
        return None

    trigger = data.get("trigger")
    if trigger is not None and (not isinstance(trigger, str) or trigger not in _INTERVALS_ALLOWED_TRIGGERS):
        return None

    result = data.get("result")
    if result is not None and (not isinstance(result, str) or result not in _INTERVALS_ALLOWED_RESULTS):
        return None

    started_ok, started_at = _parse_optional_iso_utc(data.get("started_at"))
    finished_ok, finished_at = _parse_optional_iso_utc(data.get("finished_at"))
    counts_ok, counts = _parse_sync_counts(data.get("counts"))
    if not (started_ok and finished_ok and counts_ok):
        return None

    handled_request_id = data.get("handled_request_id")
    if handled_request_id is not None and not isinstance(handled_request_id, str):
        return None

    return _ParsedSyncStatus(
        state=cast(schema.IntervalsSyncState, state),
        trigger=cast(schema.IntervalsSyncTrigger | None, trigger),
        started_at=started_at,
        finished_at=finished_at,
        result=cast(schema.IntervalsSyncResult | None, result),
        counts=counts,
        handled_request_id=handled_request_id,
        last_delete=_parse_last_delete(data.get("last_delete")),
        handled_delete_request_ids=_parse_handled_delete_ids(data.get("handled_delete_request_ids")),
    )


def _parse_request_file(path: Path) -> tuple[str, datetime] | None:
    """Read and validate request_id and requested_at from trigger/request.json."""
    data = _read_bridge_json(path)
    if data is None:
        return None
    request_id = data.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        return None
    requested_at = _parse_iso_utc(data.get("requested_at"))
    if requested_at is None:
        return None
    return request_id, requested_at


def _read_imported_intervals_id(root: Path, activity_id: int) -> str | None:
    """Look up a validated intervals.icu activity id in status/imported.json."""
    data = _read_bridge_json(root / "status" / "imported.json", max_bytes=_INTERVALS_IMPORTED_MAX_BYTES)
    if data is None:
        return None
    schema_version = data.get("schema")
    if type(schema_version) is not int or schema_version != 1:
        return None
    activities = data.get("activities")
    if not isinstance(activities, dict):
        return None
    return _validate_intervals_id(activities.get(str(activity_id)))


def _parse_delete_request_file(path: Path) -> _ParsedDeleteRequest | None:
    """Validate and extract a delete request file, returning None if corrupt."""
    data = _read_bridge_json(path)
    if data is None:
        return None
    schema_version = data.get("schema")
    if type(schema_version) is not int or schema_version != 1:
        return None
    request_id = data.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        return None
    activity_id = data.get("activity_id")
    if type(activity_id) is not int or activity_id <= 0:
        return None
    intervals_id = _validate_intervals_id(data.get("intervals_id"))
    if intervals_id is None:
        return None
    requested_at = _parse_iso_utc(data.get("requested_at"))
    if requested_at is None:
        return None
    return _ParsedDeleteRequest(
        request_id=request_id,
        activity_id=activity_id,
        intervals_id=intervals_id,
        requested_at=requested_at,
    )


def _list_unhandled_delete_requests(root: Path, handled_ids: frozenset[str]) -> list[_ParsedDeleteRequest]:
    """Return valid unhandled delete requests in deterministic order, ignoring corrupt files."""
    delete_dir = root / "delete-requests"
    try:
        entries = list(delete_dir.iterdir())
    except OSError:
        return []
    requests: list[_ParsedDeleteRequest] = []
    for entry in entries:
        if entry.name.startswith(".") or entry.suffix != ".json" or not entry.is_file():
            continue
        parsed = _parse_delete_request_file(entry)
        if parsed is not None and parsed.request_id not in handled_ids:
            requests.append(parsed)
    requests.sort(key=lambda item: (item.requested_at, item.request_id))
    return requests


def _write_atomic_json(target_dir: Path, filename: str, tmp_prefix: str, payload: dict) -> None:
    """Atomically write a JSON object into target_dir/filename via tempfile + fsync + replace."""
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_dir,
            prefix=tmp_prefix,
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            json.dump(payload, tmp_file)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        with contextlib.suppress(OSError):
            os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, target_dir / filename)
        tmp_path = None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def read_intervals_sync(user_id: int) -> schema.IntervalsSyncDisabledRead | schema.IntervalsSyncStatusRead:
    """Read whitelisted intervals.icu sync status for the configured owner.

    Args:
        user_id: Authenticated caller's user id.

    Returns:
        Disabled marker when the feature is off or caller is not the owner, otherwise
        the validated status summary.
    """
    root = _intervals_sync_root(user_id)
    if root is None:
        return schema.IntervalsSyncDisabledRead()

    parsed_status = _parse_status_file(root / "status" / "status.json")
    parsed_request = _parse_request_file(root / "trigger" / "request.json")
    last_requested_at = parsed_request[1] if parsed_request is not None else None
    handled_id = parsed_status.handled_request_id if parsed_status is not None else None
    request_pending = bool(parsed_request is not None and parsed_request[0] != handled_id)
    handled_delete_ids = parsed_status.handled_delete_request_ids if parsed_status is not None else frozenset()
    pending_deletes = len(_list_unhandled_delete_requests(root, handled_delete_ids))

    if parsed_status is None:
        return schema.IntervalsSyncStatusRead(
            state="unknown",
            last_requested_at=last_requested_at,
            request_pending=request_pending,
            last_delete=None,
            pending_deletes=pending_deletes,
        )

    return schema.IntervalsSyncStatusRead(
        state=parsed_status.state,
        last_started_at=parsed_status.started_at,
        last_finished_at=parsed_status.finished_at,
        last_result=parsed_status.result,
        counts=parsed_status.counts,
        trigger=parsed_status.trigger,
        last_requested_at=last_requested_at,
        request_pending=request_pending,
        last_delete=parsed_status.last_delete,
        pending_deletes=pending_deletes,
    )


def request_intervals_sync(user_id: int) -> schema.IntervalsSyncRequestAcceptedRead:
    """Write an atomic manual sync request to the host bridge for the configured owner.

    Args:
        user_id: Authenticated caller's user id.

    Returns:
        Accepted confirmation containing the UTC request timestamp.

    Raises:
        NotFoundError: Feature is disabled or caller is not the configured owner.
        ConflictError: A sync is currently running (<30 min) or an unhandled request is recent (<60 s).
        ServiceUnavailableError: The bridge trigger directory is missing or unwritable.
    """
    root = _intervals_sync_root(user_id)
    if root is None:
        raise errors.NotFoundError("Not found")

    now = datetime.now(UTC)
    parsed_status = _parse_status_file(root / "status" / "status.json")
    if (
        parsed_status is not None
        and parsed_status.state == "running"
        and parsed_status.started_at is not None
        and (now - parsed_status.started_at) < _INTERVALS_RUNNING_STALE_WINDOW
    ):
        raise errors.ConflictError("running")

    parsed_request = _parse_request_file(root / "trigger" / "request.json")
    handled_id = parsed_status.handled_request_id if parsed_status is not None else None
    if (
        parsed_request is not None
        and parsed_request[0] != handled_id
        and (now - parsed_request[1]) < _INTERVALS_RECENT_REQUEST_WINDOW
    ):
        raise errors.ConflictError("recent")

    trigger_dir = root / "trigger"
    if not trigger_dir.is_dir():
        raise errors.ServiceUnavailableError("Sync trigger directory is unavailable")

    requested_at = now.replace(microsecond=0)
    payload = {
        "request_id": uuid4().hex,
        "requested_at": requested_at.isoformat().replace("+00:00", "Z"),
    }

    try:
        _write_atomic_json(trigger_dir, "request.json", ".request.", payload)
    except OSError as exc:
        logger.error(
            "Failed to write intervals.icu sync request", exc_info=exc, extra=core_logger.context(user_id=user_id)
        )
        raise errors.ServiceUnavailableError("Unable to write sync request") from exc

    logger.info("Accepted intervals.icu sync request", extra=core_logger.context(user_id=user_id))
    return schema.IntervalsSyncRequestAcceptedRead(accepted=True, requested_at=requested_at)


def read_intervals_activity(user_id: int, activity_id: int) -> schema.IntervalsSyncActivityRead:
    """Look up whether an activity was imported from intervals.icu for the configured owner.

    Args:
        user_id: Authenticated caller's user id.
        activity_id: Endurain activity identifier to check.

    Returns:
        Validated intervals.icu activity id, or None when disabled, non-owner, or not imported.
    """
    root = _intervals_sync_root(user_id)
    if root is None:
        return schema.IntervalsSyncActivityRead(intervals_id=None)
    return schema.IntervalsSyncActivityRead(intervals_id=_read_imported_intervals_id(root, activity_id))


def request_intervals_delete(user_id: int, activity_id: int) -> tuple[schema.IntervalsSyncDeleteRequestRead, bool]:
    """Queue an intervals.icu delete request on the host bridge for an imported activity.

    Args:
        user_id: Authenticated caller's user id.
        activity_id: Endurain activity identifier that was imported from intervals.icu.

    Returns:
        Tuple of (response payload, created). ``created`` is False when an unhandled
        request for the same activity already exists (idempotent 200).

    Raises:
        NotFoundError: Feature is disabled or caller is not the configured owner.
        ConflictError: Activity is not mapped in ``status/imported.json`` (``not_imported``).
        ServiceUnavailableError: Bridge delete-requests or trigger directory is missing/unwritable.
    """
    root = _intervals_sync_root(user_id)
    if root is None:
        raise errors.NotFoundError("Not found")

    intervals_id = _read_imported_intervals_id(root, activity_id)
    if intervals_id is None:
        raise errors.ConflictError("not_imported")

    delete_dir = root / "delete-requests"
    if not delete_dir.is_dir():
        raise errors.ServiceUnavailableError("Delete requests directory is unavailable")

    parsed_status = _parse_status_file(root / "status" / "status.json")
    handled_delete_ids = parsed_status.handled_delete_request_ids if parsed_status is not None else frozenset()
    for existing in _list_unhandled_delete_requests(root, handled_delete_ids):
        if existing.activity_id == activity_id:
            return (
                schema.IntervalsSyncDeleteRequestRead(
                    accepted=True,
                    request_id=existing.request_id,
                    intervals_id=existing.intervals_id,
                ),
                False,
            )

    handled_trigger_id = parsed_status.handled_request_id if parsed_status is not None else None
    parsed_trigger = _parse_request_file(root / "trigger" / "request.json")
    has_unhandled_trigger = parsed_trigger is not None and parsed_trigger[0] != handled_trigger_id
    trigger_dir = root / "trigger"
    if not has_unhandled_trigger and not trigger_dir.is_dir():
        raise errors.ServiceUnavailableError("Sync trigger directory is unavailable")

    requested_at = datetime.now(UTC).replace(microsecond=0)
    requested_at_iso = requested_at.isoformat().replace("+00:00", "Z")
    request_id = uuid4().hex
    delete_payload = {
        "schema": 1,
        "request_id": request_id,
        "activity_id": activity_id,
        "intervals_id": intervals_id,
        "requested_at": requested_at_iso,
    }
    try:
        _write_atomic_json(delete_dir, f"{request_id}.json", ".delete.", delete_payload)
    except OSError as exc:
        logger.error(
            "Failed to write intervals.icu delete request",
            exc_info=exc,
            extra=core_logger.context(user_id=user_id, activity_id=activity_id),
        )
        raise errors.ServiceUnavailableError("Unable to write delete request") from exc

    if not has_unhandled_trigger:
        trigger_payload = {
            "request_id": uuid4().hex,
            "requested_at": requested_at_iso,
        }
        try:
            _write_atomic_json(trigger_dir, "request.json", ".request.", trigger_payload)
        except OSError as exc:
            logger.error(
                "Failed to write intervals.icu sync trigger for delete request",
                exc_info=exc,
                extra=core_logger.context(user_id=user_id, activity_id=activity_id),
            )
            raise errors.ServiceUnavailableError("Unable to write sync trigger") from exc

    logger.info(
        "Accepted intervals.icu delete request",
        extra=core_logger.context(user_id=user_id, activity_id=activity_id),
    )
    return (
        schema.IntervalsSyncDeleteRequestRead(
            accepted=True,
            request_id=request_id,
            intervals_id=intervals_id,
        ),
        True,
    )
