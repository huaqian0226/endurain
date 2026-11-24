import time
from datetime import UTC, datetime, timedelta
from typing import Any

import jasil.providers as platform_providers
import jasil.runtime as platform_runtime
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from stravalib.client import Client as StravaClient
from stravalib.exc import Fault as StravaFault

import core.cryptography as core_cryptography
import core.logger as core_logger
import modules.activities.activity.integration_service as activity_integration
import modules.activities.activity.schema as activity_schema
import modules.users.users_integrations.crud as user_integrations_crud
import modules.users.users_integrations.schema as user_integrations_schema
from core.database import SessionLocal

logger = core_logger.get_logger(__name__)


class StravaRateLimitTracker:
    """Tracks Strava API rate limit state in the platform's shared state.

    The limits are Strava's, per application, so every process and replica has to
    see the same answer: a process-local flag would let each worker keep
    hammering an API another one was already told to back off from. The flags are
    TTL keys in the platform ``StateProvider`` (in-process under the ``local``
    profile, Redis when distributed), so they expire on their own.
    """

    # Short-term limits reset every 15 minutes
    SHORT_TERM_COOLDOWN_SECONDS = 15 * 60

    _SHORT_TERM_KEY = "strava:rate_limited:short"
    _LONG_TERM_KEY = "strava:rate_limited:long"

    @staticmethod
    def _state() -> platform_providers.StateProvider:
        return platform_runtime.get_active_platform().state

    def mark_rate_limited(self, is_long_term: bool = False) -> None:
        """
        Record that a rate limit was hit.

        Args:
            is_long_term: True for the daily limit (resets at UTC midnight),
                False for the 15-minute limit.
        """
        now = datetime.now(UTC)
        if is_long_term:
            tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            key, ttl = self._LONG_TERM_KEY, max(1, int((tomorrow - now).total_seconds()))
            logger.warning(f"Strava daily rate limit hit. Skipping until {tomorrow}")
        else:
            key, ttl = self._SHORT_TERM_KEY, self.SHORT_TERM_COOLDOWN_SECONDS
            logger.warning(f"Strava 15-min rate limit hit. Skipping for {ttl} seconds")
        try:
            self._state().set(key, b"1", ttl_seconds=ttl)
        except platform_providers.StateBackendUnavailableError as err:
            logger.error("Could not record the Strava rate limit", exc_info=err)

    def is_rate_limited(self) -> bool:
        """
        Check if Strava API calls should be skipped.

        Fails open when the shared state is unreachable: a missed back-off costs
        one rejected call, which marks the limit again, whereas failing closed
        would stop every sync for as long as the state store is down.

        Returns:
            True if currently rate-limited.
        """
        try:
            state = self._state()
            return state.get(self._LONG_TERM_KEY) is not None or state.get(self._SHORT_TERM_KEY) is not None
        except platform_providers.StateBackendUnavailableError as err:
            logger.warning("Could not read the Strava rate limit state; assuming not limited", exc_info=err)
            return False


# Global rate limit tracker instance
rate_limit_tracker = StravaRateLimitTracker()


def is_strava_rate_limit_error(err: Exception) -> bool:
    """
    Check if an exception is a Strava rate limit error.

    Args:
        err: The exception to check.

    Returns:
        True if the error is a 429 rate limit response.
    """
    if isinstance(err, StravaFault):
        response = getattr(err, "response", None)
        if response is not None and getattr(response, "status_code", 0) == 429:
            return True
    err_str = str(err).lower()
    return "rate limit" in err_str or "429" in err_str


def is_strava_not_found_error(err: Exception) -> bool:
    """
    Check if an exception is a Strava 404 Not Found error.

    This occurs for activities that have no streams, such as
    those manually added via Apple Health and imported into Strava.

    Args:
        err: The exception to check.

    Returns:
        True if the error is a 404 not-found response.
    """
    if isinstance(err, StravaFault):
        response = getattr(err, "response", None)
        if response is not None and getattr(response, "status_code", 0) == 404:
            return True
    err_str = str(err).lower()
    return "not found" in err_str or "404" in err_str


def _noop_rate_limiter(response_headers: dict, method: str) -> None:
    """
    No-op rate limiter replacement for stravalib.

    Args:
        response_headers: HTTP response headers.
        method: HTTP method used.
    """
    pass


def refresh_user_strava_token(user_id: int) -> None:
    """Refresh a user's Strava access token when it is about to expire.

    Called at the start of the user's own sync job, so tokens are kept current
    without a separate pass over every user. The integration is read in one short
    session, the Strava call runs with none open, and the new tokens are written in
    another. A failure is logged and left to the sync that follows, which will fail
    visibly if the token really is unusable.

    Args:
        user_id: The user whose token to refresh.
    """
    if rate_limit_tracker.is_rate_limited():
        logger.warning(f"User {user_id}: Strava rate limit active, skipping token refresh")
        return

    with SessionLocal() as db:
        user_integrations = user_integrations_crud.get_user_integrations_by_user_id(user_id, db)

    if user_integrations is None:
        logger.info(f"User {user_id}: User integrations not found. Will skip processing")
        return

    if not (
        user_integrations.strava_token is not None
        and user_integrations.strava_refresh_token is not None
        and user_integrations.strava_token_expires_at is not None
        and user_integrations.strava_client_id is not None
        and user_integrations.strava_client_secret is not None
    ):
        logger.info(f"User {user_id}: No Strava token found. Will skip processing")
        return

    refresh_time = user_integrations.strava_token_expires_at.replace(tzinfo=UTC) - timedelta(minutes=60)
    if datetime.now(UTC) <= refresh_time:
        return

    try:
        strava_client = create_strava_client(user_integrations)
        tokens = strava_client.refresh_access_token(
            client_id=core_cryptography.decrypt_token_fernet(user_integrations.strava_client_id),
            client_secret=core_cryptography.decrypt_token_fernet(user_integrations.strava_client_secret),
            refresh_token=core_cryptography.decrypt_token_fernet(user_integrations.strava_refresh_token),
        )
    except Exception as err:
        if is_strava_rate_limit_error(err):
            err_str = str(err).lower()
            is_long = "long" in err_str or "daily" in err_str
            rate_limit_tracker.mark_rate_limited(is_long_term=is_long)
            logger.warning(f"User {user_id}: Strava rate limit hit during token refresh")
            return
        logger.error(f"User {user_id}: Error refreshing the Strava token", exc_info=err)
        return

    with SessionLocal() as db:
        user_integrations_crud.link_strava_account(user_id, tokens, db)
    logger.info(f"User {user_id}: Strava tokens refreshed")


def fetch_and_validate_activity(activity_id: int, user_id: int, db: Session) -> activity_schema.ActivityRead | None:
    # Get the activity by Strava ID from the user
    activity_db = activity_integration.get_activity_by_strava_id(activity_id, user_id, db)

    # Check if activity is None
    if activity_db:
        # Log an informational event if the activity already exists
        logger.info(f"User {user_id}: Activity {activity_id} already exists. Will skip processing")

        # Return None
        return activity_db
    else:
        return None


def fetch_user_integrations_and_validate_token(
    user_id: int, db: Session
) -> user_integrations_schema.UsersIntegrationsRead | None:
    # Get the user integrations by user ID
    user_integrations = user_integrations_crud.get_user_integrations_by_user_id(user_id, db)

    # Check if user integrations is None
    if user_integrations is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User information not found",
        )

    # Check if user_integrations.strava_token_expires_at is None
    if user_integrations.strava_token_expires_at is None:
        return None

    # Return the user integrations
    return user_integrations


def create_strava_client(
    user_integrations: user_integrations_schema.UsersIntegrationsRead,
) -> StravaClient:
    # Convert to epoch timestamp
    epoch_time = (
        int(time.mktime(user_integrations.strava_token_expires_at.timetuple()))
        if user_integrations.strava_token_expires_at
        else None
    )

    # Create a Strava client with rate_limit_requests
    # disabled to prevent stravalib from blocking the
    # thread for minutes/hours when limits are hit.
    try:
        client = StravaClient(
            access_token=(
                core_cryptography.decrypt_token_fernet(user_integrations.strava_token)
                if user_integrations.strava_token
                else None
            ),
            refresh_token=(
                core_cryptography.decrypt_token_fernet(user_integrations.strava_refresh_token)
                if user_integrations.strava_refresh_token
                else None
            ),
            token_expires=epoch_time,
            rate_limit_requests=False,
        )
        # Replace the no-op limiter with our own no-op
        # to suppress stravalib rate limit warnings
        client.protocol.rate_limiter = _noop_rate_limiter
        return client
    except Exception as err:
        # Log the error and re-raise the exception
        logger.error(f"Error in create_strava_client: {err}", exc_info=err, extra=core_logger.context(console=True))
        raise err


#: Localized Strava export CSV headers mapped to the canonical English names
#: expected by Endurain's bikes, shoes, and activities parsers.
STRAVA_CSV_HEADER_ALIASES: dict[str, str] = {
    # bikes.csv
    "自行车名": "Bike Name",
    "自行车品牌": "Bike Brand",
    "自行车型号": "Bike Model",
    "自行车默认的运动类型": "Bike Default Sport Types",
    # shoes.csv
    "鞋名": "Shoe Name",
    "鞋品牌": "Shoe Brand",
    "鞋型号": "Shoe Model",
    "鞋子默认的运动类型": "Shoe Default Sport Types",
    # activities.csv
    "活动 ID": "Activity ID",
    "活动日期": "Activity Date",
    "活动名称": "Activity Name",
    "活动类型": "Activity Type",
    "活动描述": "Activity Description",
    "活动装备": "Activity Gear",
    "文件名": "Filename",
    "媒体": "Media",
    "海拔爬升": "Elevation Gain",
    "海拔下降": "Elevation Loss",
    "降低海拔": "Elevation Loss",
}

#: Reverse lookup from canonical English header to its Simplified Chinese alias
#: for diagnostic log messages.
STRAVA_CSV_CHINESE_HEADER_BY_CANONICAL: dict[str, str] = {
    canonical: localized for localized, canonical in STRAVA_CSV_HEADER_ALIASES.items()
}

#: Strava Simplified Chinese ``Activity Type`` values mapped to canonical
#: English labels recognized by ``activity_constants.define_activity_type``.
STRAVA_ACTIVITY_TYPE_ALIASES: dict[str, str] = {
    "骑行": "Ride",
    "跑步": "Run",
    "越野跑": "Trail Run",
    "虚拟跑步": "Virtual Run",
    "砾石路骑行": "Gravel Ride",
    "砾石骑行": "Gravel Ride",
    "山地自行车骑行": "MountainBikeRide",
    "山地骑行": "MountainBikeRide",
    "虚拟骑行": "Virtual Ride",
    "游泳": "Swim",
    "锻炼": "Workout",
    "训练": "Workout",
    "步行": "Walk",
    "健走": "Walk",
    "徒步": "Hike",
    "远足": "Hike",
    "划船": "Rowing",
    "瑜伽": "Yoga",
    "高山滑雪": "Alpine Ski",
    "越野滑雪": "Nordic Ski",
    "单板滑雪": "Snowboard",
    "力量训练": "WeightTraining",
    "举重训练": "WeightTraining",
    "混合健身": "Crossfit",
    "网球": "Tennis",
    "乒乓球": "TableTennis",
    "羽毛球": "Badminton",
    "壁球": "Squash",
    "墙球": "Racquetball",
    "匹克球": "Pickleball",
    "通勤骑行": "Commuting ride",
    "室内骑行": "Indoor ride",
    "风帆冲浪": "Windsurf",
    "帆板冲浪": "Windsurf",
    "立式桨板": "Stand Up Paddling",
    "桨板冲浪": "Stand Up Paddling",
    "冲浪": "Surfing",
    "田径跑": "Track Run",
    "跑道跑": "Track Run",
    "电动自行车骑行": "E-Bike Ride",
    "电动山地自行车骑行": "E-Mountain Bike Ride",
    "滑冰": "Ice Skate",
    "足球": "Soccer",
    "板式网球": "Padel",
    "跑步机": "Treadmill",
    "皮划艇": "Kayaking",
    "帆船": "Sail",
    "雪鞋健行": "Snowshoe",
    "轮滑": "InlineSkate",
    "高强度间歇训练": "HIIT",
    "跳绳": "Jump Rope",
}


def normalize_strava_csv_row(row: dict[Any, Any]) -> dict[Any, Any]:
    """Normalize localized Strava CSV row headers to canonical English names.

    English rows pass through unchanged. When both a canonical English header
    and a localized alias appear in the same row, the canonical English value
    takes precedence.

    Args:
        row: A single CSV row dictionary produced by ``csv.DictReader``.

    Returns:
        A row dictionary with known localized header keys mapped to their
        canonical English names.
    """
    if not any(key in STRAVA_CSV_HEADER_ALIASES for key in row):
        return row
    normalized: dict[Any, Any] = {}
    for key, value in row.items():
        canonical = STRAVA_CSV_HEADER_ALIASES.get(key, key)
        if canonical == key:
            normalized[canonical] = value
        else:
            normalized.setdefault(canonical, value)
    return normalized


def normalize_strava_activity_type(activity_type: Any) -> Any:
    """Map a localized Strava activity type label to its canonical English name.

    English labels, unknown values, and non-string values pass through
    unchanged.

    Args:
        activity_type: Raw ``Activity Type`` value from a Strava CSV row.

    Returns:
        Canonical English activity type label if known, otherwise the original
        value.
    """
    if not isinstance(activity_type, str):
        return activity_type
    return STRAVA_ACTIVITY_TYPE_ALIASES.get(activity_type.strip(), activity_type)
