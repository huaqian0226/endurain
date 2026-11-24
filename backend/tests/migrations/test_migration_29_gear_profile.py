"""PostgreSQL migration safety test for revision wb_gear_profile_01 (M25).

Skipped unless ``M25_MIGRATION_TEST_DB_URL`` is set to a throwaway PostgreSQL
database URL (never a production or shared instance).
"""

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command

_DB_URL = os.environ.get("M25_MIGRATION_TEST_DB_URL")
_APP_DIR = Path(__file__).resolve().parents[2] / "app"

_PREV_REVISION = "wb_equipment_01"
_HEAD_REVISION = "wb_gear_profile_01"
_NEW_COLUMNS = (
    "purchase_date",
    "retired_date",
    "frame_number",
    "size",
    "color",
    "model_year",
    "groupset",
    "specs",
    "purchase_source",
    "notes",
)


def _alembic_config() -> Config:
    config = Config(str(_APP_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(_APP_DIR / "alembic"))
    config.attributes["configure_logger"] = False
    return config


@pytest.mark.skipif(not _DB_URL, reason="Set M25_MIGRATION_TEST_DB_URL to run throwaway Postgres migration test")
def test_gear_profile_migration_upgrade_and_downgrade(monkeypatch):
    """Upgrade preserves existing gear, component, and activity rows; downgrade restores prior schema."""
    assert _DB_URL is not None
    engine = create_engine(_DB_URL)

    # Point Alembic's env.py engine at our throwaway PostgreSQL instance.
    import core.database as core_database

    monkeypatch.setattr(core_database, "engine", engine)

    cfg = _alembic_config()

    # 1. Bring throwaway DB up to the previous revision (wb_equipment_01).
    command.upgrade(cfg, _PREV_REVISION)

    created_at = datetime(2024, 3, 15, 12, 0, 0, tzinfo=UTC)
    with engine.begin() as conn:
        user_id = conn.execute(
            text(
                "INSERT INTO users (name, username, email, preferred_language, gender, units, "
                "access_type, active, first_day_of_week, currency, timezone, email_verified, "
                "pending_admin_approval) "
                "VALUES ('Synth Rider', 'synth_m25', 'synth_m25@example.test', 'en', 'unspecified', "
                "'metric', 'regular', true, 'monday', 'euro', 'UTC', true, false) RETURNING id"
            )
        ).scalar_one()

        gear_id = conn.execute(
            text(
                "INSERT INTO gear (brand, model, nickname, gear_type, user_id, created_at, active, "
                "initial_kms, purchase_value, strava_gear_id, garminconnect_gear_id) "
                "VALUES ('SynthBrand', 'Aero Expert', 'Synth Aero 56', 1, :user_id, :created_at, true, "
                "1234.50, 2899.99, 'b_synth_01', 'g_synth_01') RETURNING id"
            ),
            {"user_id": user_id, "created_at": created_at},
        ).scalar_one()

        comp_id = conn.execute(
            text(
                "INSERT INTO gear_components (user_id, gear_id, type, brand, model, purchase_date, "
                "retired_date, active, expected_kms, purchase_value) "
                "VALUES (:user_id, :gear_id, 'chain', 'SynthChain', 'X10', :purchase_date, NULL, true, "
                "3000000, 35.00) RETURNING id"
            ),
            {"user_id": user_id, "gear_id": gear_id, "purchase_date": date(2025, 1, 1)},
        ).scalar_one()

        activity_id = conn.execute(
            text(
                "INSERT INTO activities (user_id, name, distance, activity_type, start_time, end_time, "
                "timezone, total_elapsed_time, total_timer_time, created_at, visibility, gear_id, "
                "is_hidden, hide_start_time, hide_location, hide_map, hide_hr, hide_power, "
                "hide_cadence, hide_elevation, hide_speed, hide_pace, hide_laps, "
                "hide_workout_sets_steps, hide_gear, version, equipment_confirmed) "
                "VALUES (:user_id, 'Synth Ride', 42000, 1, :start_time, :end_time, 'UTC', 5400, 5200, "
                ":created_at, 0, :gear_id, false, false, false, false, false, false, false, false, "
                "false, false, false, false, false, 1, false) RETURNING id"
            ),
            {
                "user_id": user_id,
                "start_time": datetime(2025, 4, 1, 8, 0, 0, tzinfo=UTC),
                "end_time": datetime(2025, 4, 1, 9, 30, 0, tzinfo=UTC),
                "created_at": datetime(2025, 4, 1, 9, 31, 0, tzinfo=UTC),
                "gear_id": gear_id,
            },
        ).scalar_one()

    # 2. Upgrade to head (wb_gear_profile_01).
    command.upgrade(cfg, "head")

    from modules.gears.gear.models import Gear

    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT brand, model, nickname, gear_type, user_id, created_at, active, "
                    "initial_kms, purchase_value, strava_gear_id, garminconnect_gear_id, "
                    "purchase_date, retired_date, frame_number, size, color, model_year, "
                    "groupset, specs, purchase_source, notes "
                    "FROM gear WHERE id = :gear_id"
                ),
                {"gear_id": gear_id},
            )
            .mappings()
            .one()
        )

        # Old fields identical
        assert row["brand"] == "SynthBrand"
        assert row["model"] == "Aero Expert"
        assert row["nickname"] == "Synth Aero 56"
        assert row["gear_type"] == 1
        assert row["user_id"] == user_id
        assert row["created_at"] == created_at
        assert row["active"] is True
        assert row["initial_kms"] == Decimal("1234.50")
        assert row["purchase_value"] == Decimal("2899.99")
        assert row["strava_gear_id"] == "b_synth_01"
        assert row["garminconnect_gear_id"] == "g_synth_01"

        # New fields all NULL
        for col in _NEW_COLUMNS:
            assert row[col] is None, f"Expected gear.{col} to be NULL after upgrade"

        # Related component and activity intact
        comp = (
            conn.execute(
                text("SELECT id, gear_id, type, brand, model FROM gear_components WHERE id = :id"),
                {"id": comp_id},
            )
            .mappings()
            .one()
        )
        assert comp["gear_id"] == gear_id
        assert comp["type"] == "chain"

        act = (
            conn.execute(
                text("SELECT id, gear_id, name, distance FROM activities WHERE id = :id"),
                {"id": activity_id},
            )
            .mappings()
            .one()
        )
        assert act["gear_id"] == gear_id
        assert act["name"] == "Synth Ride"

        # Verify PostgreSQL column comments match ORM model comments exactly.
        pg_comments = dict(
            conn.execute(
                text(
                    "SELECT a.attname, col_description(c.oid, a.attnum) "
                    "FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid "
                    "WHERE c.relname = 'gear' AND a.attnum > 0 AND NOT a.attisdropped"
                )
            ).all()
        )
        for col in _NEW_COLUMNS:
            assert pg_comments[col] == Gear.__table__.columns[col].comment

    # 3. Downgrade one step back to wb_equipment_01 and assert old data still intact.
    command.downgrade(cfg, "-1")

    with engine.connect() as conn:
        cols_after_downgrade = {
            r[0]
            for r in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'gear'")
            ).all()
        }
        for col in _NEW_COLUMNS:
            assert col not in cols_after_downgrade

        row_after = (
            conn.execute(
                text(
                    "SELECT brand, model, nickname, gear_type, user_id, active, "
                    "initial_kms, purchase_value, strava_gear_id, garminconnect_gear_id "
                    "FROM gear WHERE id = :gear_id"
                ),
                {"gear_id": gear_id},
            )
            .mappings()
            .one()
        )
        assert row_after["brand"] == "SynthBrand"
        assert row_after["model"] == "Aero Expert"
        assert row_after["nickname"] == "Synth Aero 56"
        assert row_after["initial_kms"] == Decimal("1234.50")
        assert row_after["purchase_value"] == Decimal("2899.99")

        assert (
            conn.execute(text("SELECT gear_id FROM gear_components WHERE id = :id"), {"id": comp_id}).scalar_one()
            == gear_id
        )
        assert (
            conn.execute(text("SELECT gear_id FROM activities WHERE id = :id"), {"id": activity_id}).scalar_one()
            == gear_id
        )

    engine.dispose()
