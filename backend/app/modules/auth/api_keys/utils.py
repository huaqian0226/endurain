"""User API key utility functions."""

import json
import secrets
from datetime import UTC, datetime

import modules.auth.token_hashing as token_hashing

MIN_TEMP_SCOPE_DURATION_MINUTES = 1
MAX_TEMP_SCOPE_DURATION_MINUTES = 10080

SUPPORTED_API_KEY_SCOPES = frozenset(
    {
        "activities:read",
        "activities:write",
        "activities:upload",
        "workbench:read",
        "gears:read",
        "gears:write",
        "health:read",
        "health:write",
        "followers:read",
        "followers:write",
        "notifications:read",
        "notifications:write",
        "users:read",
    }
)


def generate_api_key() -> str:
    """
    Generate a new raw API key.

    Keys have the format ``endurain_<token>`` where
    ``<token>`` is 32 cryptographically random bytes
    encoded as base64url (43 characters). Total entropy
    is 256 bits.

    Returns:
        A new raw API key string.
    """
    return f"endurain_{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key: str) -> str:
    """
    Compute the SHA-256 hex digest of a raw API key.

    High-entropy secrets do not require a slow KDF
    (Argon2/bcrypt). SHA-256 is the industry standard
    for hashing tokens of this entropy level.

    Args:
        raw_key: The plain-text API key to hash.

    Returns:
        Lowercase hex-encoded SHA-256 digest (64 chars).
    """
    return token_hashing.sha256_hex(raw_key)


def validate_api_key_scopes(
    requested_scopes: list[str],
    _user_access_type: str,
) -> None:
    """
    Validate requested scopes against supported API-key scopes.

    API keys support activity uploads and owner-scoped workbench projections. Keeping this
    allow-list separate from the full JWT scope set prevents API keys
    from silently gaining access when new unified-auth endpoints are
    added later.

    Args:
        requested_scopes: List of scopes the caller wants
            to assign to the new API key.
        _user_access_type: The owner's access type. Accepted for
            router compatibility but not used while API-key scopes are explicitly allow-listed.

    Raises:
        ValueError: If any requested scope is not supported.
    """
    unsupported = set(requested_scopes) - SUPPORTED_API_KEY_SCOPES
    if unsupported or not requested_scopes:
        raise ValueError(f"Unsupported API key scopes: {unsupported}. Valid scopes: {SUPPORTED_API_KEY_SCOPES}")


def scopes_to_json(scopes: list[str]) -> str:
    """
    Serialize a list of scope strings to a JSON string.

    Args:
        scopes: List of scope strings.

    Returns:
        JSON-encoded string representation.
    """
    return json.dumps(scopes)


def json_to_scopes(scopes_json: str) -> list[str]:
    """
    Deserialize a JSON string to a list of scope strings.

    Args:
        scopes_json: JSON-encoded scope list.

    Returns:
        List of scope strings.
    """
    return json.loads(scopes_json)


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp.

    Returns:
        Current UTC datetime.
    """
    return datetime.now(UTC)


def normalize_utc(value: datetime) -> datetime:
    """Ensure a datetime is timezone-aware in UTC.

    Naive datetimes (e.g. from SQLite test storage) are treated as UTC.

    Args:
        value: Datetime to normalize.

    Returns:
        Timezone-aware UTC datetime.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def is_api_key_expired(expires_at: datetime | None, now: datetime | None = None) -> bool:
    """Check whether an API key's own expiration timestamp has passed.

    Args:
        expires_at: Optional key expiration timestamp.
        now: Optional reference UTC datetime (defaults to :func:`utc_now`).

    Returns:
        True when ``expires_at`` is set and ``now > expires_at``, False otherwise.
    """
    if not isinstance(expires_at, datetime):
        return False
    current = normalize_utc(now) if now is not None else utc_now()
    return current > normalize_utc(expires_at)


def get_live_temp_scopes(
    db_key: object,
    now: datetime | None = None,
) -> tuple[list[str], datetime | None]:
    """Return currently active temporary scopes and their UTC expiry for a key.

    A temporary grant is live only when the key is active, not expired, has both
    ``temp_scopes`` and ``temp_scopes_expires_at`` set, and
    ``now(UTC) < temp_scopes_expires_at``.

    Args:
        db_key: API key ORM object (or compatible stub).
        now: Optional reference UTC datetime (defaults to :func:`utc_now`).

    Returns:
        Tuple of ``(live_temp_scopes, temp_scopes_expires_at)``. When inactive
        or expired, returns ``([], None)``.
    """
    if getattr(db_key, "is_active", True) is False:
        return [], None

    current = normalize_utc(now) if now is not None else utc_now()
    if is_api_key_expired(getattr(db_key, "expires_at", None), current):
        return [], None

    raw_temp_scopes = getattr(db_key, "temp_scopes", None)
    temp_expires_at = getattr(db_key, "temp_scopes_expires_at", None)
    if not isinstance(raw_temp_scopes, str) or not isinstance(temp_expires_at, datetime):
        return [], None

    expires_utc = normalize_utc(temp_expires_at)
    if current >= expires_utc:
        return [], None

    parsed = json_to_scopes(raw_temp_scopes)
    if not isinstance(parsed, list) or not parsed:
        return [], None

    return list(dict.fromkeys(parsed)), expires_utc


def get_effective_scopes(
    db_key: object,
    now: datetime | None = None,
) -> list[str]:
    """Compute effective scopes as base scopes union live temporary scopes.

    Args:
        db_key: API key ORM object (or compatible stub).
        now: Optional reference UTC datetime (defaults to :func:`utc_now`).

    Returns:
        Deduplicated list of effective scope strings preserving base-first order.
    """
    base_scopes = json_to_scopes(getattr(db_key, "scopes", "[]"))
    live_temp, _ = get_live_temp_scopes(db_key, now=now)
    return list(dict.fromkeys([*base_scopes, *live_temp]))
