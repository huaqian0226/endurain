"""Tests for M27 gear groups (schema, CRUD, batched distance, router, model/migration parity)."""

from datetime import UTC, datetime
from decimal import Decimal
from importlib import util as importlib_util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import String
from sqlalchemy.exc import SQLAlchemyError

import core.exceptions as core_exceptions
from tests._helpers.db import create_sqlite_session, setup_mock_execute


def _build_app(mock_db):
    import core.database as core_db
    import core.dependencies as core_deps
    import modules.auth.dependencies as auth_deps
    import modules.gears.gear.dependencies as gear_deps
    import modules.gears.gear.router as router

    app = FastAPI()
    app.include_router(router.router, prefix="/gears")

    def _mock():
        return None

    def _uid():
        return 1

    app.dependency_overrides[auth_deps.check_auth_scopes] = _mock
    app.dependency_overrides[auth_deps.get_user_id_from_auth] = _uid
    app.dependency_overrides[core_deps.validate_pagination_values_on_query] = _mock
    app.dependency_overrides[gear_deps.validate_gear_id] = _mock
    app.dependency_overrides[gear_deps.validate_gear_type] = _mock
    app.dependency_overrides[core_db.get_db] = lambda: mock_db
    return app


def _make_gear_row(**overrides) -> SimpleNamespace:
    """Build a Gear-like attribute object without triggering SQLAlchemy mapper init."""
    base = {
        "id": 1,
        "user_id": 1,
        "brand": None,
        "model": None,
        "nickname": "Road Bike",
        "group_name": None,
        "gear_type": 1,
        "created_at": None,
        "active": True,
        "initial_kms": 0.0,
        "purchase_value": None,
        "purchase_date": None,
        "retired_date": None,
        "frame_number": None,
        "size": None,
        "color": None,
        "model_year": None,
        "groupset": None,
        "specs": None,
        "purchase_source": None,
        "notes": None,
        "strava_gear_id": None,
        "garminconnect_gear_id": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestGearGroupSchema:
    """Validation and normalization for gear.group_name."""

    def test_create_accepts_and_trims_group_name(self):
        from modules.gears.gear.schema import GearCreate

        payload = GearCreate(nickname="Aero Road", gear_type=1, group_name="  公路车  ")
        assert payload.group_name == "公路车"

    @pytest.mark.parametrize("raw_value", ("", "   ", "\t\n  "))
    def test_whitespace_only_group_name_normalizes_to_none(self, raw_value):
        from modules.gears.gear.schema import GearCreate, GearUpdate

        created = GearCreate(nickname="Clean Bike", gear_type=1, group_name=raw_value)
        updated = GearUpdate(id=1, nickname="Clean Bike", gear_type=1, group_name=raw_value)
        assert created.group_name is None
        assert updated.group_name is None

    def test_length_cap_100_enforced(self):
        from modules.gears.gear.schema import GearCreate, GearUpdate

        exact = "a" * 100
        assert GearCreate(nickname="Exact", gear_type=1, group_name=f"  {exact}  ").group_name == exact
        assert GearUpdate(id=1, nickname="Exact", gear_type=1, group_name=exact).group_name == exact

        with pytest.raises(ValidationError):
            GearCreate(nickname="Too Long", gear_type=1, group_name="a" * 101)
        with pytest.raises(ValidationError):
            GearUpdate(id=1, nickname="Too Long", gear_type=1, group_name="a" * 101)

    def test_old_client_omitting_group_name_defaults_to_none(self):
        from modules.gears.gear.schema import GearCreate, GearDetailRead, GearRead, GearUpdate

        created = GearCreate(nickname="Legacy Bike", gear_type=1)
        updated = GearUpdate(id=1, nickname="Legacy Bike", gear_type=1)
        read = GearRead(id=1, user_id=1, nickname="Legacy Bike", gear_type=1)
        detail = GearDetailRead(id=1, user_id=1, nickname="Legacy Bike", gear_type=1)

        for obj in (created, updated, read, detail):
            assert obj.group_name is None
        assert read.total_distance is None
        assert detail.total_distance == 0


class TestGearGroupCrud:
    """Partial-update semantics and batched distance stats for gears."""

    def test_edit_omitting_group_name_preserves_existing_value(self, mock_db):
        import modules.gears.gear.crud as crud
        import modules.gears.gear.schema as s

        db_gear = _make_gear_row(nickname="Rental #1", group_name="迪乐租")
        setup_mock_execute(mock_db, return_one_or_none=db_gear)

        update = s.GearUpdate(id=1, nickname="Rental #1 Renamed", gear_type=1)
        result = crud.edit_gear(gear=update, user_id=1, db=mock_db)

        assert result.nickname == "Rental #1 Renamed"
        assert result.group_name == "迪乐租"
        assert db_gear.group_name == "迪乐租"

    def test_edit_explicit_none_clears_group_name(self, mock_db):
        import modules.gears.gear.crud as crud
        import modules.gears.gear.schema as s

        db_gear = _make_gear_row(nickname="Rental #1", group_name="迪乐租")
        setup_mock_execute(mock_db, return_one_or_none=db_gear)

        update = s.GearUpdate(id=1, nickname="Rental #1", gear_type=1, group_name=None)
        result = crud.edit_gear(gear=update, user_id=1, db=mock_db)

        assert result.group_name is None
        assert db_gear.group_name is None

    @pytest.mark.parametrize("blank", ("", "   "))
    def test_edit_empty_or_whitespace_clears_group_name(self, mock_db, blank):
        import modules.gears.gear.crud as crud
        import modules.gears.gear.schema as s

        db_gear = _make_gear_row(nickname="Road A", group_name="公路车")
        setup_mock_execute(mock_db, return_one_or_none=db_gear)

        update = s.GearUpdate(id=1, nickname="Road A", gear_type=1, group_name=blank)
        result = crud.edit_gear(gear=update, user_id=1, db=mock_db)

        assert result.group_name is None
        assert db_gear.group_name is None

    def test_edit_sets_and_trims_group_name(self, mock_db):
        import modules.gears.gear.crud as crud
        import modules.gears.gear.schema as s

        db_gear = _make_gear_row(nickname="Road A", group_name=None)
        setup_mock_execute(mock_db, return_one_or_none=db_gear)

        update = s.GearUpdate(id=1, nickname="Road A", gear_type=1, group_name="  公路车  ")
        result = crud.edit_gear(gear=update, user_id=1, db=mock_db)

        assert result.group_name == "公路车"
        assert db_gear.group_name == "公路车"

    def test_get_gears_activity_stats_empty_short_circuits(self, mock_db):
        import modules.gears.gear.crud as crud

        assert crud.get_gears_activity_stats([], user_id=1, db=mock_db) == {}
        mock_db.execute.assert_not_called()

    def test_get_gears_activity_stats_db_error(self, mock_db):
        import modules.gears.gear.crud as crud

        mock_db.execute.side_effect = SQLAlchemyError("err")
        with pytest.raises(core_exceptions.ProcessingError) as exc_info:
            crud.get_gears_activity_stats([1, 2], user_id=1, db=mock_db)
        assert exc_info.value.status_code == 500


class TestGearGroupSqlitePersistence:
    """Real SQLite round-trip for Gear.group_name and batched gear distance totals."""

    def test_create_update_and_batched_usage_totals(self):
        import modules.activities.activity.integration_service as activity_integration
        import modules.activities.activity.models as activity_models
        import modules.gears.gear.crud as gears_crud
        import modules.gears.gear.schema as gears_schema

        session = create_sqlite_session()
        try:
            g1 = gears_crud.create_gear(
                gears_schema.GearCreate(nickname="Synth A", gear_type=1, group_name="  公路车  ", initial_kms=10.0),
                user_id=1,
                db=session,
            )
            g2 = gears_crud.create_gear(
                gears_schema.GearCreate(nickname="Synth B", gear_type=1, group_name=None),
                user_id=1,
                db=session,
            )
            assert g1.group_name == "公路车"
            assert g2.group_name is None

            # Update omitting group_name preserves it; explicit empty string clears it.
            kept = gears_crud.edit_gear(
                gears_schema.GearUpdate(id=g1.id, nickname="Synth A", gear_type=1),
                user_id=1,
                db=session,
            )
            assert kept.group_name == "公路车"

            cleared = gears_crud.edit_gear(
                gears_schema.GearUpdate(id=g1.id, nickname="Synth A", gear_type=1, group_name=""),
                user_id=1,
                db=session,
            )
            assert cleared.group_name is None

            # Batched activity totals only include owner's activities.
            base_activity = {
                "activity_type": 1,
                "start_time": datetime(2025, 1, 1, tzinfo=UTC),
                "end_time": datetime(2025, 1, 1, 1, tzinfo=UTC),
                "created_at": datetime(2025, 1, 1, tzinfo=UTC),
                "total_elapsed_time": Decimal("3600"),
                "total_timer_time": Decimal("3600"),
                "visibility": 0,
                "is_hidden": False,
                "hide_start_time": False,
                "hide_location": False,
                "hide_map": False,
                "hide_hr": False,
                "hide_power": False,
                "hide_cadence": False,
                "hide_elevation": False,
                "hide_speed": False,
                "hide_pace": False,
                "hide_laps": False,
                "hide_workout_sets_steps": False,
                "hide_gear": False,
            }
            session.add_all(
                [
                    activity_models.Activity(user_id=1, gear_id=g1.id, distance=15000, **base_activity),
                    activity_models.Activity(user_id=1, gear_id=g1.id, distance=25000, **base_activity),
                    # Another user's activity referencing g1 must not be counted.
                    activity_models.Activity(user_id=2, gear_id=g1.id, distance=99999, **base_activity),
                ]
            )
            session.commit()

            totals = activity_integration.get_gears_usage_totals([g1.id, g2.id], user_id=1, db=session)
            assert totals[g1.id].distance == 40000.0
            assert totals[g1.id].time == 7200.0
            assert g2.id not in totals
            assert activity_integration.get_gears_usage_totals([], user_id=1, db=session) == {}
        finally:
            session.close()
            session.bind.dispose()


class TestGearGroupRouter:
    """HTTP contract for create, update, list, search, and detail with group_name."""

    @patch("modules.gears.gear.router.gears_crud.create_gear")
    def test_post_round_trips_trimmed_group_name(self, mock_create, mock_db):
        from modules.gears.gear.schema import GearRead

        client = TestClient(_build_app(mock_db))
        mock_create.return_value = GearRead(
            id=10,
            user_id=1,
            nickname="Roadie",
            gear_type=1,
            group_name="公路车",
        )

        response = client.post(
            "/gears",
            json={"nickname": "Roadie", "gear_type": 1, "group_name": "  公路车  "},
            headers={"Authorization": "Bearer x"},
        )
        assert response.status_code == 201
        assert response.json()["group_name"] == "公路车"
        passed_gear = mock_create.call_args.args[0]
        assert passed_gear.group_name == "公路车"

    def test_post_and_put_reject_overlength_group_name_with_422(self, mock_db):
        client = TestClient(_build_app(mock_db))
        too_long = "g" * 101

        post_resp = client.post(
            "/gears",
            json={"nickname": "Too Long", "gear_type": 1, "group_name": too_long},
            headers={"Authorization": "Bearer x"},
        )
        assert post_resp.status_code == 422

        put_resp = client.put(
            "/gears",
            json={"id": 1, "nickname": "Too Long", "gear_type": 1, "group_name": too_long},
            headers={"Authorization": "Bearer x"},
        )
        assert put_resp.status_code == 422

    @patch("modules.gears.gear.router.gears_crud.edit_gear")
    def test_put_forwards_explicit_clear_vs_omitted(self, mock_edit, mock_db):
        from modules.gears.gear.schema import GearRead

        client = TestClient(_build_app(mock_db))
        mock_edit.return_value = GearRead(id=1, user_id=1, nickname="Roadie", gear_type=1, group_name=None)

        resp_omitted = client.put(
            "/gears",
            json={"id": 1, "nickname": "Roadie", "gear_type": 1},
            headers={"Authorization": "Bearer x"},
        )
        assert resp_omitted.status_code == 200
        assert "group_name" not in mock_edit.call_args.args[0].model_fields_set

        resp_null = client.put(
            "/gears",
            json={"id": 1, "nickname": "Roadie", "gear_type": 1, "group_name": None},
            headers={"Authorization": "Bearer x"},
        )
        assert resp_null.status_code == 200
        assert "group_name" in mock_edit.call_args.args[0].model_fields_set
        assert mock_edit.call_args.args[0].group_name is None

        resp_empty = client.put(
            "/gears",
            json={"id": 1, "nickname": "Roadie", "gear_type": 1, "group_name": ""},
            headers={"Authorization": "Bearer x"},
        )
        assert resp_empty.status_code == 200
        assert "group_name" in mock_edit.call_args.args[0].model_fields_set
        assert mock_edit.call_args.args[0].group_name is None

    @patch("modules.gears.gear.router.gears_crud.get_gears_activity_stats")
    @patch("modules.gears.gear.router.gears_crud.get_gears_number")
    @patch("modules.gears.gear.router.gears_crud.get_gear_users_with_pagination")
    def test_list_attaches_group_name_and_batched_total_distance(
        self,
        mock_paginated,
        mock_number,
        mock_stats,
        mock_db,
    ):
        from modules.gears.gear.schema import GearRead

        client = TestClient(_build_app(mock_db))
        mock_paginated.return_value = [
            GearRead(id=1, user_id=1, nickname="Bike A", gear_type=1, group_name="迪乐租", initial_kms=10.0),
            GearRead(id=2, user_id=1, nickname="Bike B", gear_type=1, group_name=None, initial_kms=0.0),
        ]
        mock_number.return_value = 2
        mock_stats.return_value = {
            1: {"total_distance": 5000.0, "total_time": 900.0},
            2: {"total_distance": 12000.0, "total_time": 1800.0},
        }

        response = client.get("/gears", headers={"Authorization": "Bearer x"})
        assert response.status_code == 200
        records = response.json()["records"]
        assert records[0]["group_name"] == "迪乐租"
        assert records[0]["total_distance"] == 15000.0
        assert records[1]["group_name"] is None
        assert records[1]["total_distance"] == 12000.0
        mock_stats.assert_called_once_with([1, 2], 1, mock_db)

    @patch("modules.gears.gear.router.gears_crud.get_gears_activity_stats")
    @patch("modules.gears.gear.router.gears_crud.get_gear_user_contains_nickname")
    def test_search_attaches_group_name_and_batched_total_distance(self, mock_search, mock_stats, mock_db):
        from modules.gears.gear.schema import GearRead

        client = TestClient(_build_app(mock_db))
        mock_search.return_value = [
            GearRead(id=5, user_id=1, nickname="Road Pro", gear_type=1, group_name="公路车", initial_kms=5.0),
        ]
        mock_stats.return_value = {5: {"total_distance": 20000.0, "total_time": 3600.0}}

        response = client.get("/gears/nickname/contains/Road", headers={"Authorization": "Bearer x"})
        assert response.status_code == 200
        body = response.json()
        assert body[0]["group_name"] == "公路车"
        assert body[0]["total_distance"] == 25000.0

    @patch("modules.gears.gear.router.gears_crud.get_gear_components_total_cost")
    @patch("modules.gears.gear.router.gears_crud.get_gear_activity_stats")
    @patch("modules.gears.gear.router.gears_crud.get_gear_user_by_id")
    def test_detail_returns_group_name_and_total_distance(self, mock_get, mock_stats, mock_cost, mock_db):
        from modules.gears.gear.schema import GearRead

        client = TestClient(_build_app(mock_db))
        mock_get.return_value = GearRead(
            id=3,
            user_id=1,
            nickname="Road Pro",
            gear_type=1,
            group_name="公路车",
            initial_kms=2.0,
        )
        mock_stats.return_value = {"total_distance": 8000.0, "total_time": 1200.0}
        mock_cost.return_value = 0.0

        response = client.get("/gears/id/3", headers={"Authorization": "Bearer x"})
        assert response.status_code == 200
        body = response.json()
        assert body["group_name"] == "公路车"
        assert body["total_distance"] == 10000.0


class TestGearGroupModelAndMigration:
    """ORM column definition and Alembic migration revision metadata."""

    def test_model_column_is_nullable_string_100(self):
        from modules.gears.gear.models import Gear

        cols = Gear.__table__.columns
        assert "group_name" in cols
        col = cols["group_name"]
        assert col.nullable is True
        assert isinstance(col.type, String)
        assert col.type.length == 100
        assert col.comment

    def test_migration_revision_and_reversibility(self):
        migration_path = (
            Path(__file__).resolve().parents[3] / "app" / "alembic" / "versions" / "31_add_gear_group_name.py"
        )
        assert migration_path.is_file()
        spec = importlib_util.spec_from_file_location("wb_gear_group_01_migration", migration_path)
        assert spec is not None and spec.loader is not None
        module = importlib_util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert module.revision == "wb_gear_group_01"
        assert module.down_revision == "wb_api_key_temp_scopes_01"
        assert callable(module.upgrade)
        assert callable(module.downgrade)

        with (
            patch.object(module.op, "add_column") as mock_add,
            patch.object(module.op, "drop_column") as mock_drop,
        ):
            module.upgrade()
            module.downgrade()

        mock_add.assert_called_once()
        table_name, column = mock_add.call_args.args
        assert table_name == "gear"
        assert column.name == "group_name"
        assert column.nullable is True
        assert isinstance(column.type, String)
        assert column.type.length == 100

        mock_drop.assert_called_once_with("gear", "group_name")
