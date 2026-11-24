"""Workbench behavior at the authenticated HTTP boundary using synthetic records."""

from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._helpers.db import create_sqlite_session

VEHICLE = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def client():
    import core.database as database
    import core.exceptions as exceptions
    import modules.activities.activity.workbench_router as router
    import modules.activities.saved_routes.router as routes
    import modules.auth.dependencies as auth
    from modules.activities.activity.models import Activity
    from modules.gears.gear.models import Gear

    db = create_sqlite_session()
    db.add(Gear(id=1, user_id=1, nickname="Venge", gear_type=1, purchase_value=321.5))
    db.add(
        Activity(
            id=1,
            user_id=1,
            name="Renamed demo",
            activity_type=1,
            gear_id=1,
            distance=99999,
            total_elapsed_time=720,
            total_timer_time=600,
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    db.add(
        Activity(
            id=2,
            user_id=1,
            name="Ride",
            activity_type=1,
            gear_id=1,
            distance=12000,
            total_elapsed_time=720,
            total_timer_time=600,
            start_time=datetime(2026, 1, 2, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, 1, tzinfo=UTC),
            created_at=datetime(2026, 1, 2, tzinfo=UTC),
        )
    )
    for row in db.new:
        if isinstance(row, Activity):
            for column in Activity.__table__.columns:
                if column.name.startswith("hide_"):
                    setattr(row, column.name, False)
    db.commit()
    app = FastAPI()
    app.state.test_db = db
    exceptions.register_exception_handlers(app)
    app.include_router(router.router, prefix="/workbench")
    app.include_router(routes.router, prefix="/workbench")
    app.dependency_overrides[database.get_db] = lambda: db
    app.dependency_overrides[auth.get_user_id_from_auth] = lambda: 1
    app.dependency_overrides[auth.get_user_id_from_auth] = lambda: 1
    app.dependency_overrides[auth.check_auth_scopes] = lambda: None
    app.dependency_overrides[auth.check_auth_scopes] = lambda: None
    with TestClient(app) as http:
        yield http
    db.close()


def test_existing_vehicle_mapping_preserves_price_and_excludes_renamed_demo(client):
    mapped = client.put(
        f"/workbench/vehicles/{VEHICLE}",
        json={
            "instance_id": "synthetic-instance",
            "gear_id": 1,
            "excluded_activity_ids": [1],
        },
    )
    assert mapped.status_code == 200, mapped.text
    response = client.get(f"/workbench/vehicles/{VEHICLE}")
    assert response.status_code == 200, response.text
    assert client.get(f"/workbench/vehicle-mappings/{VEHICLE}").json() == mapped.json()
    import modules.auth.dependencies as auth

    client.app.dependency_overrides[auth.get_user_id_from_auth] = lambda: 2
    assert client.get(f"/workbench/vehicle-mappings/{VEHICLE}").status_code == 404
    client.app.dependency_overrides[auth.get_user_id_from_auth] = lambda: 1

    body = response.json()
    assert body["gear"]["purchase_value"] == 321.5
    assert body["gear"]["gear_id"] == 1
    assert [a["activity_id"] for a in body["activities"]] == [2]
    assert body["activities"][0]["timer_seconds"] == 600
    assert body["activities"][0]["elapsed_seconds"] == 720
    assert body["excluded"]["count"] == 1
    assert body["complete"] is True
    assert body["coverage"]["history_complete"] is False
    assert client.get(f"/workbench/vehicles/{VEHICLE}").json()["revision"] == body["revision"]


def test_read_key_is_scoped_and_cannot_write_or_read_other_owners(client):
    import json
    from uuid import uuid4

    import modules.auth.dependencies as auth
    from modules.auth.api_keys.models import UsersApiKeys
    from modules.auth.api_keys.utils import hash_api_key
    from modules.users.users.models import Users

    client.put(
        f"/workbench/vehicles/{VEHICLE}",
        json={"instance_id": "synthetic-instance", "gear_id": 1, "excluded_activity_ids": [1]},
    )
    db = client.app.state.test_db
    for user_id in [1, 2]:
        db.add(
            Users(
                id=user_id,
                name="Synthetic user",
                username=f"synthetic{user_id}",
                email=f"synthetic{user_id}@example.com",
                preferred_language="en",
                access_type="regular",
            )
        )
    for raw, owner, scopes, active in [
        ("endurain_test_read", 1, ["workbench:read"], True),
        ("endurain_test_upload", 1, ["activities:upload"], True),
        ("endurain_test_other", 2, ["workbench:read"], True),
        ("endurain_test_revoked", 1, ["workbench:read"], False),
    ]:
        db.add(
            UsersApiKeys(
                id=str(uuid4()),
                user_id=owner,
                name="Synthetic test key",
                key_prefix="test",
                key_hash=hash_api_key(raw),
                scopes=json.dumps(scopes),
                created_at=datetime.now(UTC),
                is_active=active,
            )
        )
    db.commit()
    for dep in [auth.check_auth_scopes, auth.get_user_id_from_auth]:
        client.app.dependency_overrides.pop(dep, None)
    path = f"/workbench/vehicles/{VEHICLE}"
    assert client.get(path, headers={"X-API-Key": "endurain_test_read"}).status_code == 200
    assert client.get(path, headers={"X-API-Key": "endurain_test_upload"}).status_code == 403
    assert client.get(path, headers={"X-API-Key": "endurain_test_other"}).status_code == 404
    assert client.get(path, headers={"X-API-Key": "endurain_test_revoked"}).status_code == 401
    assert (
        client.put(
            path,
            headers={"X-API-Key": "endurain_test_read", "X-Client-Type": "web"},
            json={"instance_id": "synthetic-instance", "gear_id": 1},
        ).status_code
        == 403
    )


def test_native_edit_saves_primary_vehicle_and_all_equipment_atomically(client):
    import core.dependencies as dependencies
    import modules.activities.activity.router as activity_router
    from modules.gears.gear.models import Gear

    helmet = "00000000-0000-4000-8000-000000000101"
    lamp = "00000000-0000-4000-8000-000000000102"
    second_vehicle = "00000000-0000-4000-8000-000000000002"
    client.app.include_router(activity_router.router, prefix="/activities")
    client.app.state.test_db.add(Gear(id=2, user_id=1, nickname="Second bicycle", gear_type=1))
    client.app.state.test_db.commit()

    class Catalogue:
        def read(self, user_id):
            return {
                "schema_version": 1,
                "observed_at": "2026-11-16T00:00:00Z",
                "revision": "source-1",
                "items": [
                    {"result": "ok", "asset": {"asset_id": item, "label": "Synthetic item", "status": "active"}}
                    for item in [helmet, lamp]
                ],
            }

    client.app.dependency_overrides[dependencies.get_household_catalogue] = lambda: Catalogue().read
    for vehicle, gear in [(VEHICLE, 1), (second_vehicle, 2)]:
        assert (
            client.put(
                f"/workbench/vehicles/{vehicle}",
                json={"instance_id": "synthetic-instance", "gear_id": gear, "excluded_activity_ids": [1]},
            ).status_code
            == 200
        )
    selection = {
        "confirmed": True,
        "items": [{"asset_id": helmet, "use_mode": "used"}, {"asset_id": lamp, "use_mode": "carried"}],
    }
    response = client.patch(
        "/activities/2", headers={"If-Match": '"1"'}, json={"gear_id": 2, "equipment_selection": selection}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["gear_id"] == 2
    assert body["equipment_confirmed"] is True
    assert len(body["equipment"]) == 2
    assert client.get(f"/workbench/vehicles/{VEHICLE}").json()["activities"] == []
    usage = client.get(f"/workbench/assets/{helmet}/usage").json()
    assert usage["coverage"]["activity_count"] == 1
    assert usage["activities"][0]["vehicle_uuid"] == second_vehicle
    assert usage["activities"][0]["distance_m"] == 12000
    assert usage["activities"][0]["use_mode"] == "used"
    assert (
        client.patch(
            "/activities/2", headers={"If-Match": '"1"'}, json={"gear_id": 1, "equipment_selection": selection}
        ).status_code
        == 412
    )
    assert client.get(f"/workbench/assets/{helmet}/usage").json()["revision"] == usage["revision"]
    duplicate = {"confirmed": True, "items": [selection["items"][0]] * 2}
    assert (
        client.patch(
            "/activities/2", headers={"If-Match": f'"{body["version"]}"'}, json={"equipment_selection": duplicate}
        ).status_code
        == 422
    )
    unavailable = {
        "confirmed": True,
        "items": [{"asset_id": "00000000-0000-4000-8000-000000000999", "use_mode": "used"}],
    }
    rejected = client.patch(
        "/activities/2",
        headers={"If-Match": f'"{body["version"]}"'},
        json={"gear_id": 1, "equipment_selection": unavailable},
    )
    assert rejected.status_code == 400
    assert client.get(f"/workbench/assets/{helmet}/usage").json()["revision"] == usage["revision"]
    from core.exceptions import CatalogueUnavailableError

    def offline(user_id):
        raise CatalogueUnavailableError()

    client.app.dependency_overrides[dependencies.get_household_catalogue] = lambda: offline
    failed = client.patch(
        "/activities/2",
        headers={"If-Match": f'"{body["version"]}"'},
        json={"gear_id": 1, "equipment_selection": selection},
    )
    assert failed.status_code == 503
    assert client.get(f"/workbench/assets/{helmet}/usage").json()["revision"] == usage["revision"]
    empty = client.patch(
        "/activities/2",
        headers={"If-Match": f'"{body["version"]}"'},
        json={"equipment_selection": {"confirmed": True, "items": []}},
    )
    assert empty.status_code == 200
    assert empty.json()["equipment_confirmed"] is True
    assert empty.json()["equipment"] == []
    assert client.get(f"/workbench/assets/{helmet}/usage").json()["activities"] == []
    unknown = client.patch(
        "/activities/2",
        headers={"If-Match": f'"{empty.json()["version"]}"'},
        json={"equipment_selection": {"confirmed": False, "items": []}},
    )
    assert unknown.status_code == 200
    assert unknown.json()["equipment_confirmed"] is False
    assert client.delete("/activities/2").status_code == 204
    after = client.get(f"/workbench/assets/{helmet}/usage").json()
    assert after["activities"] == []
    assert after["revision"] != usage["revision"]


def test_fixed_exclusions_survive_mapping_changes_and_vehicle_changes(client, monkeypatch):
    import core.config as config
    from modules.activities.activity.models import Activity
    from modules.gears.gear.models import Gear

    monkeypatch.setattr(config.settings, "WORKBENCH_EXCLUDED_ACTIVITY_IDS", [1])
    db = client.app.state.test_db
    db.get(Activity, 1).name = "Ordinary renamed ride"
    db.add(Gear(id=2, user_id=1, nickname="Second", gear_type=1))
    db.commit()
    mapped = client.put(f"/workbench/vehicles/{VEHICLE}", json={"instance_id": "test", "gear_id": 1}).json()
    assert client.get(f"/workbench/vehicles/{VEHICLE}").json()["excluded"]["count"] == 1
    mapped = client.put(
        f"/workbench/vehicles/{VEHICLE}",
        json={"instance_id": "test", "gear_id": 1, "revision": mapped["revision"], "excluded_activity_ids": [2]},
    ).json()
    client.put(
        f"/workbench/vehicles/{VEHICLE}", json={"instance_id": "test", "gear_id": 1, "revision": mapped["revision"]}
    )
    assert client.get(f"/workbench/vehicles/{VEHICLE}").json()["excluded"]["count"] == 2
    other = "00000000-0000-4000-8000-000000000002"
    client.put(f"/workbench/vehicles/{other}", json={"instance_id": "test", "gear_id": 2})
    db.get(Activity, 1).gear_id = 2
    db.commit()
    assert client.get(f"/workbench/vehicles/{other}").json()["excluded"]["count"] == 1


def test_aggregated_api_reaches_workbench_before_frontend_fallback(client):
    import api
    import core.dependencies as dependencies

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides.update(client.app.dependency_overrides)
    app.dependency_overrides[dependencies.get_household_catalogue] = lambda: (
        lambda user_id: {
            "schema_version": 1,
            "observed_at": "2026-11-16T00:00:00Z",
            "revision": "synthetic-catalogue",
            "items": [],
        }
    )
    with TestClient(app) as http:
        response = http.get("/api/v1/workbench/equipment-candidates")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["revision"] == "synthetic-catalogue"


def test_saved_route_owns_snapshot_and_sends_once_per_trip(client):
    from xml.etree import ElementTree

    import modules.auth.dependencies as auth
    from modules.activities.activity.models import Activity
    from modules.activities.activity_streams.models import ActivityStreams

    db = client.app.state.test_db
    endpoint = "/workbench/activities/2/saved-route"
    assert client.put(endpoint, json={"name": "Test trail"}).status_code == 400
    db.get(Activity, 2).activity_type = 5
    db.add(
        ActivityStreams(
            activity_id=2,
            stream_type=7,
            stream_waypoints=[
                {"lat": 150, "lon": 12},
                {"lat": 51.2, "lon": 0, "time": 1, "hr": 130},
                {"lat": 51.2, "lon": 0},
                {"lat": 51.3, "lon": 0.2, "time": 2},
            ],
        )
    )
    db.add(
        ActivityStreams(
            activity_id=2,
            stream_type=4,
            stream_waypoints=[
                {"ele": 18.4, "time": 1},
                {"ele": 25.1, "time": 2},
            ],
        )
    )
    db.commit()
    route = client.put(endpoint, json={"name": "  Ridge & River  "}).json()
    assert route["name"] == "Ridge & River" and route["point_count"] == 2
    assert client.put(endpoint, json={"name": "Retry"}).json() == route
    assert client.get("/workbench/saved-routes").json() == [route]
    from core.dependencies import get_trek_route_tool

    calls = []

    def fake_trek(owner, name, args):
        assert owner == 1
        if name == "list_trips":
            return {"trips": [{"id": 7, "title": "Island"}]}
        assert name == "import_tour_gpx"
        assert args["tour_type"] == "bike" and args["bike_profile"] == "gravel"
        root = ElementTree.fromstring(args["gpx"])  # noqa: S314 -- generated synthetic XML
        assert root.find(".//{*}name").text == route["name"]
        assert len(root.findall(".//{*}trkpt")) == 2
        assert root.find(".//{*}ele").text == "18.4"
        assert "time" not in args["gpx"] and "130" not in args["gpx"]
        calls.append(args["tripId"])
        return {"tours": [{"place_id": 44}], "skipped": 0}

    client.app.dependency_overrides[get_trek_route_tool] = lambda: fake_trek
    assert client.get("/workbench/route-trips").json() == [{"id": 7, "title": "Island"}]
    push = f"/workbench/saved-routes/{route['id']}/trips"
    assert client.post(push + "/7").json()["already_added"] is False
    assert client.post(push + "/7").json()["already_added"] is True
    assert client.post(push + "/8").status_code == 200
    assert calls == [7, 8]
    client.app.dependency_overrides[auth.get_user_id_from_auth] = lambda: 2
    assert client.get("/workbench/saved-routes").json() == []
    assert client.put(endpoint, json={"name": "Other"}).status_code == 404
    assert client.post(push + "/7").status_code == 404


def test_saved_route_recovers_a_native_duplicate_without_overwriting_a_different_loop():
    from modules.activities.saved_routes import service

    xml, count = service._gpx("River Loop", [[51.0, -1.0, None], [51.02, -1.02, None], [51.0, -1.0, None]])
    other, _ = service._gpx("River Loop", [[51.0, -1.0, None], [51.05, -1.04, None], [51.0, -1.0, None]])
    assert count == 3
    remote = {1: other, 2: xml}

    def trek(_owner, tool, args):
        if tool == "import_tour_gpx":
            return {"skipped": 1, "tours": []}
        if tool == "list_tours":
            return {"tours": [{"name": "River Loop", "tour_type": "hike", "place_id": i} for i in remote]}
        assert tool == "export_tour_gpx"
        return {"gpx": remote[args["placeId"]]}

    args = {"tripId": 4, "gpx": xml, "file_name": "River Loop.gpx", "tour_type": "hike"}
    assert service._import_matching_tour(1, args, trek) == (2, True)
    del remote[2]
    assert service._import_matching_tour(1, args, trek) == (None, False)
