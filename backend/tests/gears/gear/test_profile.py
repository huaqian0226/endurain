"""Tests for M25 rich gear profile fields (schema, CRUD, router, model/migration parity)."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Date, SmallInteger, String, Text

NEW_PROFILE_FIELDS = (
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


class TestGearProfileSchema:
    """Validation and normalization for the 10 new gear profile fields."""

    def test_create_accepts_all_profile_fields(self):
        from modules.gears.gear.schema import GearCreate

        payload = GearCreate(
            nickname="Aero Road",
            gear_type=1,
            brand="BrandA",
            model="Aero Pro",
            purchase_date=date(2024, 3, 15),
            retired_date=date(2026, 5, 10),
            frame_number="SYN-FRAME-001",
            size="56",
            color="Matte Black / Red",
            model_year=2013,
            groupset="Electronic 10-speed",
            specs="Front wheel: 82mm carbon\nRear wheel: 101mm carbon\nTyres: 22mm tubular",
            purchase_source="Local bike shop",
            notes="Line 1\n<script>alert('xss')</script>\nLine 3",
        )
        assert payload.purchase_date == date(2024, 3, 15)
        assert payload.retired_date == date(2026, 5, 10)
        assert payload.frame_number == "SYN-FRAME-001"
        assert payload.size == "56"
        assert payload.color == "Matte Black / Red"
        assert payload.model_year == 2013
        assert payload.groupset == "Electronic 10-speed"
        assert "Front wheel: 82mm carbon\nRear wheel: 101mm carbon" in payload.specs
        assert payload.purchase_source == "Local bike shop"
        assert payload.notes == "Line 1\n<script>alert('xss')</script>\nLine 3"

    def test_old_client_omitting_profile_fields_defaults_to_none(self):
        from modules.gears.gear.schema import GearCreate, GearDetailRead, GearRead, GearUpdate

        created = GearCreate(nickname="Minimal Bike", gear_type=1)
        updated = GearUpdate(id=1, nickname="Minimal Bike", gear_type=1)
        read = GearRead(id=1, user_id=1, nickname="Minimal Bike", gear_type=1)
        detail = GearDetailRead(id=1, user_id=1, nickname="Minimal Bike", gear_type=1)

        for obj in (created, updated, read, detail):
            for field in NEW_PROFILE_FIELDS:
                assert getattr(obj, field) is None

    def test_retired_date_same_as_purchase_date_is_allowed(self):
        from modules.gears.gear.schema import GearCreate

        gear = GearCreate(
            nickname="Same Day",
            gear_type=1,
            purchase_date=date(2025, 5, 1),
            retired_date=date(2025, 5, 1),
        )
        assert gear.purchase_date == date(2025, 5, 1)
        assert gear.retired_date == date(2025, 5, 1)

    def test_retired_date_before_purchase_date_is_rejected(self):
        from modules.gears.gear.schema import GearCreate, GearUpdate

        with pytest.raises(ValidationError):
            GearCreate(
                nickname="Bad Dates",
                gear_type=1,
                purchase_date=date(2025, 5, 2),
                retired_date=date(2025, 5, 1),
            )

        with pytest.raises(ValidationError):
            GearUpdate(
                id=1,
                nickname="Bad Dates",
                gear_type=1,
                purchase_date=date(2025, 5, 2),
                retired_date=date(2025, 5, 1),
            )

    @pytest.mark.parametrize(
        "field_name",
        ("frame_number", "size", "color", "groupset", "specs", "purchase_source", "notes"),
    )
    def test_whitespace_only_text_fields_normalize_to_none(self, field_name):
        from modules.gears.gear.schema import GearCreate

        gear = GearCreate(nickname="Clean Bike", gear_type=1, **{field_name: "  \t\n  "})
        assert getattr(gear, field_name) is None

    def test_text_fields_strip_surrounding_whitespace_and_preserve_newlines(self):
        from modules.gears.gear.schema import GearCreate

        gear = GearCreate(
            nickname="Trimmed Bike",
            gear_type=1,
            frame_number="  SN-42  ",
            size="  56  ",
            color="  Celeste  ",
            groupset="  10-speed  ",
            purchase_source="  Dealer  ",
            specs="  Line 1\n  Line 2  ",
            notes="\n  First note\nSecond note  \n",
        )
        assert gear.frame_number == "SN-42"
        assert gear.size == "56"
        assert gear.color == "Celeste"
        assert gear.groupset == "10-speed"
        assert gear.purchase_source == "Dealer"
        assert gear.specs == "Line 1\n  Line 2"
        assert gear.notes == "First note\nSecond note"

    @pytest.mark.parametrize(
        ("field_name", "max_len"),
        (
            ("frame_number", 100),
            ("size", 50),
            ("color", 100),
            ("groupset", 250),
            ("specs", 4000),
            ("purchase_source", 250),
            ("notes", 8000),
        ),
    )
    def test_length_caps_enforced(self, field_name, max_len):
        from modules.gears.gear.schema import GearCreate

        ok = GearCreate(nickname="Length OK", gear_type=1, **{field_name: "a" * max_len})
        assert len(getattr(ok, field_name)) == max_len

        with pytest.raises(ValidationError):
            GearCreate(nickname="Too Long", gear_type=1, **{field_name: "a" * (max_len + 1)})

    @pytest.mark.parametrize("year", (1900, 2013, 2100))
    def test_model_year_valid_bounds(self, year):
        from modules.gears.gear.schema import GearCreate

        gear = GearCreate(nickname="Year OK", gear_type=1, model_year=year)
        assert gear.model_year == year

    @pytest.mark.parametrize("year", (1899, 2101, 0, -5))
    def test_model_year_out_of_range_rejected(self, year):
        from modules.gears.gear.schema import GearCreate

        with pytest.raises(ValidationError):
            GearCreate(nickname="Bad Year", gear_type=1, model_year=year)


def _make_gear_row(**overrides) -> SimpleNamespace:
    """Build a Gear-like attribute object without triggering SQLAlchemy mapper init."""
    base = {
        "id": 1,
        "user_id": 1,
        "brand": None,
        "model": None,
        "nickname": "Road Bike",
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


class TestGearProfileCrud:
    """Persistence and partial-update behavior for gear profile fields."""

    def test_edit_omitting_profile_fields_preserves_existing_values(self, mock_db):
        import modules.gears.gear.crud as crud
        import modules.gears.gear.schema as s
        from tests._helpers.db import setup_mock_execute

        db_gear = _make_gear_row(
            nickname="Aero Bike",
            purchase_date=date(2023, 4, 1),
            retired_date=date(2026, 5, 1),
            frame_number="SYN-999",
            size="56",
            color="Black",
            model_year=2013,
            groupset="Di2 10s",
            specs="Carbon wheels",
            purchase_source="Bike shop",
            notes="Original note",
        )
        setup_mock_execute(mock_db, return_one_or_none=db_gear)

        # Old client payload omits all 10 new fields.
        update = s.GearUpdate(id=1, nickname="Aero Bike Renamed", gear_type=1)
        result = crud.edit_gear(gear=update, user_id=1, db=mock_db)

        assert result.nickname == "Aero Bike Renamed"
        assert db_gear.purchase_date == date(2023, 4, 1)
        assert db_gear.retired_date == date(2026, 5, 1)
        assert db_gear.frame_number == "SYN-999"
        assert db_gear.size == "56"
        assert db_gear.color == "Black"
        assert db_gear.model_year == 2013
        assert db_gear.groupset == "Di2 10s"
        assert db_gear.specs == "Carbon wheels"
        assert db_gear.purchase_source == "Bike shop"
        assert db_gear.notes == "Original note"

    def test_edit_explicit_none_or_whitespace_clears_profile_fields(self, mock_db):
        import modules.gears.gear.crud as crud
        import modules.gears.gear.schema as s
        from tests._helpers.db import setup_mock_execute

        db_gear = _make_gear_row(
            nickname="Commuter",
            active=False,
            purchase_date=date(2022, 1, 10),
            retired_date=date(2026, 5, 10),
            frame_number="SN-1",
            size="54",
            color="Blue",
            model_year=2021,
            groupset="105",
            specs="Alloy wheels",
            purchase_source="Online",
            notes="Stolen case note",
        )
        setup_mock_execute(mock_db, return_one_or_none=db_gear)

        update = s.GearUpdate(
            id=1,
            nickname="Commuter",
            gear_type=1,
            retired_date=None,
            notes="   ",
            model_year=None,
        )
        result = crud.edit_gear(gear=update, user_id=1, db=mock_db)

        assert result.retired_date is None
        assert result.notes is None
        assert result.model_year is None
        # Unmentioned profile fields remain intact.
        assert result.purchase_date == date(2022, 1, 10)
        assert result.frame_number == "SN-1"
        assert result.size == "54"

    def test_edit_rejects_retired_date_before_existing_purchase_date(self, mock_db):
        import modules.gears.gear.crud as crud
        import modules.gears.gear.schema as s
        from tests._helpers.db import setup_mock_execute

        db_gear = _make_gear_row(
            nickname="Road",
            purchase_date=date(2025, 6, 1),
        )
        setup_mock_execute(mock_db, return_one_or_none=db_gear)

        update = s.GearUpdate(id=1, nickname="Road", gear_type=1, retired_date=date(2025, 5, 31))
        with pytest.raises(HTTPException) as exc:
            crud.edit_gear(gear=update, user_id=1, db=mock_db)
        assert exc.value.status_code == 422
        mock_db.commit.assert_not_called()

    def test_edit_rejects_purchase_date_after_existing_retired_date(self, mock_db):
        import modules.gears.gear.crud as crud
        import modules.gears.gear.schema as s
        from tests._helpers.db import setup_mock_execute

        db_gear = _make_gear_row(
            nickname="Road",
            active=False,
            retired_date=date(2025, 5, 31),
        )
        setup_mock_execute(mock_db, return_one_or_none=db_gear)

        update = s.GearUpdate(id=1, nickname="Road", gear_type=1, purchase_date=date(2025, 6, 1))
        with pytest.raises(HTTPException) as exc:
            crud.edit_gear(gear=update, user_id=1, db=mock_db)
        assert exc.value.status_code == 422
        mock_db.commit.assert_not_called()


class TestGearProfileRouter:
    """HTTP contract for create, update, detail, and list endpoints with profile fields."""

    @patch("modules.gears.gear.router.gears_crud.create_gear")
    def test_post_round_trips_profile_fields(self, mock_create, mock_db):
        from modules.gears.gear.schema import GearRead

        client = TestClient(_build_app(mock_db))
        mock_create.return_value = GearRead(
            id=7,
            user_id=1,
            nickname="Synthetic Aero",
            gear_type=1,
            purchase_date=date(2024, 1, 2),
            retired_date=date(2026, 5, 3),
            frame_number="SYN-123",
            size="56",
            color="Black",
            model_year=2013,
            groupset="Electronic 10s",
            specs="82/101 wheels",
            purchase_source="Second-hand",
            notes="<script>alert(1)</script>",
        )

        response = client.post(
            "/gears",
            json={
                "nickname": "Synthetic Aero",
                "gear_type": 1,
                "purchase_date": "2024-01-02",
                "retired_date": "2026-05-03",
                "frame_number": "  SYN-123 ",
                "size": "56",
                "color": "Black",
                "model_year": 2013,
                "groupset": "Electronic 10s",
                "specs": "82/101 wheels",
                "purchase_source": "Second-hand",
                "notes": "<script>alert(1)</script>",
            },
            headers={"Authorization": "Bearer x"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["purchase_date"] == "2024-01-02"
        assert body["retired_date"] == "2026-05-03"
        assert body["frame_number"] == "SYN-123"
        assert body["size"] == "56"
        assert body["color"] == "Black"
        assert body["model_year"] == 2013
        assert body["groupset"] == "Electronic 10s"
        assert body["specs"] == "82/101 wheels"
        assert body["purchase_source"] == "Second-hand"
        assert body["notes"] == "<script>alert(1)</script>"

    def test_post_rejects_invalid_date_order_with_422(self, mock_db):
        client = TestClient(_build_app(mock_db))
        response = client.post(
            "/gears",
            json={
                "nickname": "Invalid Bike",
                "gear_type": 1,
                "purchase_date": "2026-05-10",
                "retired_date": "2026-05-01",
            },
            headers={"Authorization": "Bearer x"},
        )
        assert response.status_code == 422

    @patch("modules.gears.gear.router.gears_crud.get_gear_components_total_cost")
    @patch("modules.gears.gear.router.gears_crud.get_gear_activity_stats")
    @patch("modules.gears.gear.router.gears_crud.get_gear_user_by_id")
    def test_detail_endpoint_returns_profile_fields(self, mock_get, mock_stats, mock_cost, mock_db):
        from modules.gears.gear.schema import GearRead

        client = TestClient(_build_app(mock_db))
        mock_get.return_value = GearRead(
            id=3,
            user_id=1,
            nickname="Retired Road",
            gear_type=1,
            active=False,
            purchase_date=date(2020, 4, 1),
            retired_date=date(2026, 5, 12),
            size="53",
            notes="Retired after theft",
        )
        mock_stats.return_value = {"total_distance": 12000.0, "total_time": 1800.0}
        mock_cost.return_value = 250.0

        response = client.get("/gears/id/3", headers={"Authorization": "Bearer x"})
        assert response.status_code == 200
        body = response.json()
        assert body["purchase_date"] == "2020-04-01"
        assert body["retired_date"] == "2026-05-12"
        assert body["size"] == "53"
        assert body["notes"] == "Retired after theft"
        assert body["total_distance"] == 12000.0

    @patch("modules.gears.gear.router.gears_crud.get_gears_number")
    @patch("modules.gears.gear.router.gears_crud.get_gear_users_with_pagination")
    def test_list_endpoint_returns_profile_fields(self, mock_paginated, mock_number, mock_db):
        from modules.gears.gear.schema import GearRead

        client = TestClient(_build_app(mock_db))
        mock_paginated.return_value = [
            GearRead(
                id=1,
                user_id=1,
                nickname="Aero",
                gear_type=1,
                model_year=2013,
                retired_date=date(2026, 5, 1),
            )
        ]
        mock_number.return_value = 1

        response = client.get("/gears", headers={"Authorization": "Bearer x"})
        assert response.status_code == 200
        record = response.json()["records"][0]
        assert record["model_year"] == 2013
        assert record["retired_date"] == "2026-05-01"


class TestGearProfileModelAndMigration:
    """ORM column definitions match expected types, nullability, and migration comments."""

    def test_model_columns_are_nullable_with_expected_types(self):
        from modules.gears.gear.models import Gear

        cols = Gear.__table__.columns
        expected_types = {
            "purchase_date": Date,
            "retired_date": Date,
            "frame_number": String,
            "size": String,
            "color": String,
            "model_year": SmallInteger,
            "groupset": String,
            "specs": Text,
            "purchase_source": String,
            "notes": Text,
        }
        for name, expected_cls in expected_types.items():
            assert name in cols, f"Missing column gear.{name}"
            col = cols[name]
            assert col.nullable is True, f"Column gear.{name} must be nullable"
            assert isinstance(col.type, expected_cls), f"Column gear.{name} has unexpected type {col.type!r}"
            assert col.comment, f"Column gear.{name} must define a comment"

        assert cols["frame_number"].type.length == 100
        assert cols["size"].type.length == 50
        assert cols["color"].type.length == 100
        assert cols["groupset"].type.length == 250
        assert cols["purchase_source"].type.length == 250
