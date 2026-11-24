"""PostgreSQL migration safety test for revision wb_api_key_temp_scopes_01 (M26).

Skipped unless ``M26_MIGRATION_TEST_DB_URL`` is set to a throwaway PostgreSQL
database URL (never a production or shared instance).
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command

_DB_URL = os.environ.get("M26_MIGRATION_TEST_DB_URL")
_APP_DIR = Path(__file__).resolve().parents[2] / "app"

_PREV_REVISION = "wb_gear_profile_01"
_HEAD_REVISION = "wb_api_key_temp_scopes_01"
_NEW_COLUMNS = (
    "temp_scopes",
    "temp_scopes_expires_at",
)


def _alembic_config() -> Config:
    config = Config(str(_APP_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_APP_DIR / "alembic"))
    config.attributes["configure_logger"] = False
    return config


@pytest.mark.skipif(not _DB_URL, reason="Set M26_MIGRATION_TEST_DB_URL to run throwaway Postgres migration test")
def test_api_key_temp_scopes_migration_upgrade_and_downgrade(monkeypatch):
    """Upgrade preserves existing API key rows with NULL new columns; downgrade restores prior schema."""
    assert _DB_URL is not None
    engine = create_engine(_DB_URL)

    import core.database as core_database

    monkeypatch.setattr(core_database, "engine", engine)

    cfg = _alembic_config()

    # 1. Bring throwaway DB up to the previous revision (wb_gear_profile_01).
    command.upgrade(cfg, _PREV_REVISION)

    created_at = datetime(2025, 3, 15, 12, 0, 0, tzinfo=UTC)
    key_id = str(uuid4())
    key_hash = "a" * 64

    with engine.begin() as conn:
        user_id = conn.execute(
            text(
                "INSERT INTO users (name, username, email, preferred_language, gender, units, "
                "access_type, active, first_day_of_week, currency, timezone, email_verified, "
                "pending_admin_approval) "
                "VALUES ('Synth Key Owner', 'synth_m26', 'synth_m26@example.test', 'en', 'unspecified', "
                "'metric', 'regular', true, 'monday', 'euro', 'UTC', true, false) RETURNING id"
            )
        ).scalar_one()

        conn.execute(
            text(
                "INSERT INTO users_api_keys (id, user_id, name, key_prefix, key_hash, scopes, "
                "expires_at, last_used_at, created_at, is_active) "
                "VALUES (:id, :user_id, 'Legacy Key', 'abcdefgh', :key_hash, '[\"activities:read\"]', "
                "NULL, NULL, :created_at, true)"
            ),
            {"id": key_id, "user_id": user_id, "key_hash": key_hash, "created_at": created_at},
        )

    # 2. Upgrade to head (wb_api_key_temp_scopes_01).
    command.upgrade(cfg, _HEAD_REVISION)

    from modules.auth.api_keys.models import UsersApiKeys

    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT id, user_id, name, key_prefix, key_hash, scopes, expires_at, "
                    "last_used_at, created_at, is_active, temp_scopes, temp_scopes_expires_at "
                    "FROM users_api_keys WHERE id = :id"
                ),
                {"id": key_id},
            )
            .mappings()
            .one()
        )

        # Old fields identical
        assert row["user_id"] == user_id
        assert row["name"] == "Legacy Key"
        assert row["key_prefix"] == "abcdefgh"
        assert row["key_hash"] == key_hash
        assert row["scopes"] == '["activities:read"]'
        assert row["expires_at"] is None
        assert row["last_used_at"] is None
        assert row["created_at"] == created_at
        assert row["is_active"] is True

        # New fields NULL
        for col in _NEW_COLUMNS:
            assert row[col] is None, f"Expected users_api_keys.{col} to be NULL after upgrade"

        # Verify PostgreSQL column comments match ORM model comments exactly.
        pg_comments = dict(
            conn.execute(
                text(
                    "SELECT a.attname, col_description(c.oid, a.attnum) "
                    "FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid "
                    "WHERE c.relname = 'users_api_keys' AND a.attnum > 0 AND NOT a.attisdropped"
                )
            ).all()
        )
        for col in _NEW_COLUMNS:
            assert pg_comments[col] == UsersApiKeys.__table__.columns[col].comment

    # 3. Downgrade one step back to wb_gear_profile_01 and assert old data still intact.
    command.downgrade(cfg, "-1")

    with engine.connect() as conn:
        cols_after_downgrade = {
            r[0]
            for r in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'users_api_keys'")
            ).all()
        }
        for col in _NEW_COLUMNS:
            assert col not in cols_after_downgrade

        row_after = (
            conn.execute(
                text(
                    "SELECT id, user_id, name, key_prefix, key_hash, scopes, is_active "
                    "FROM users_api_keys WHERE id = :id"
                ),
                {"id": key_id},
            )
            .mappings()
            .one()
        )
        assert row_after["name"] == "Legacy Key"
        assert row_after["scopes"] == '["activities:read"]'
        assert row_after["is_active"] is True

    engine.dispose()
