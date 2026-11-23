"""API-key authorization at the aggregated public HTTP boundary."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._helpers.db import create_sqlite_session


@pytest.fixture
def http():
    import api
    import core.database as database
    import core.dependencies as core_dependencies
    import core.exceptions as exceptions
    from modules.activities.activity.models import Activity
    from modules.auth.api_keys.models import UsersApiKeys
    from modules.auth.api_keys.utils import hash_api_key
    from modules.gears.gear.models import Gear
    from modules.users.users.models import Users

    db = create_sqlite_session()
    for user_id in (1, 2):
        db.add(
            Users(
                id=user_id,
                name=f"Synthetic user {user_id}",
                username=f"synthetic{user_id}",
                email=f"synthetic{user_id}@example.com",
                preferred_language="en",
                access_type="regular",
            )
        )
    activities = []
    for activity_id, owner_id, visibility in ((1, 1, 2), (2, 2, 2)):
        activities.append(
            Activity(
                id=activity_id,
                user_id=owner_id,
                name=f"Synthetic activity {activity_id}",
                activity_type=1,
                distance=1000,
                total_elapsed_time=600,
                total_timer_time=600,
                start_time=datetime(2026, 1, activity_id, tzinfo=UTC),
                end_time=datetime(2026, 1, activity_id, 1, tzinfo=UTC),
                created_at=datetime(2026, 1, activity_id, tzinfo=UTC),
                visibility=visibility,
                version=1,
            )
        )
    for activity in activities:
        for column in Activity.__table__.columns:
            if column.name.startswith("hide_"):
                setattr(activity, column.name, False)
        db.add(activity)
    db.add(Gear(id=1, user_id=1, nickname="Synthetic bike", gear_type=1))
    keys = {
        "read": ("endurain_m20_activity_read", 1, ["activities:read"]),
        "workbench": ("endurain_m20_workbench_read", 1, ["workbench:read"]),
        "write": ("endurain_m20_activity_write", 1, ["activities:write"]),
        "other": ("endurain_m20_other_user", 2, ["activities:read"]),
        "gears_read": ("endurain_m20_gears_read", 1, ["gears:read"]),
        "gears_write": ("endurain_m20_gears_write", 1, ["gears:write"]),
        "health_read": ("endurain_m20_health_read", 1, ["health:read"]),
        "health_write": ("endurain_m20_health_write", 1, ["health:write"]),
        "followers_read": ("endurain_m20_followers_read", 1, ["followers:read"]),
        "followers_write": ("endurain_m20_followers_write", 1, ["followers:write"]),
        "notifications_read": ("endurain_m20_notifications_read", 1, ["notifications:read"]),
        "notifications_write": ("endurain_m20_notifications_write", 1, ["notifications:write"]),
        "users_read": ("endurain_m20_users_read", 1, ["users:read"]),
    }
    for raw, owner, scopes in keys.values():
        db.add(
            UsersApiKeys(
                id=str(uuid4()),
                user_id=owner,
                name="Synthetic M20 key",
                key_prefix="synthetic",
                key_hash=hash_api_key(raw),
                scopes=json.dumps(scopes),
                created_at=datetime.now(UTC),
                is_active=True,
            )
        )
    db.commit()

    app = FastAPI()
    exceptions.register_exception_handlers(app)
    app.include_router(api.router)
    app.dependency_overrides[database.get_db] = lambda: db
    app.dependency_overrides[core_dependencies.get_household_catalogue] = lambda: (
        lambda _user_id: {
            "schema_version": 1,
            "observed_at": "2026-11-21T00:00:00Z",
            "revision": "synthetic",
            "items": [],
        }
    )
    with TestClient(app) as client:
        yield client, keys
    db.close()


def test_activities_read_key_reads_own_routes_but_not_another_users_private_activity(http):
    client, keys = http
    headers = {"X-API-Key": keys["read"][0]}

    for path in (
        "/api/v1/activities",
        "/api/v1/activities/1",
        "/api/v1/activities/1/streams",
        "/api/v1/activities/1/laps",
    ):
        response = client.get(path, headers=headers)
        assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"
        assert response.headers["content-type"].startswith("application/json")

    assert client.get("/api/v1/activities/2", headers=headers).status_code == 404


def test_missing_and_read_only_activity_scopes_return_forbidden(http):
    client, keys = http
    workbench_key = {"X-API-Key": keys["workbench"][0]}
    read_key = {"X-API-Key": keys["read"][0]}

    assert client.get("/api/v1/activities/1", headers=workbench_key).status_code == 403
    assert client.patch("/api/v1/activities/1", headers=read_key, json={"name": "Changed"}).status_code == 403
    assert client.delete("/api/v1/activities/1", headers=read_key).status_code == 403


def test_activity_write_key_can_patch_activity(http):
    client, keys = http
    response = client.patch(
        "/api/v1/activities/1",
        headers={"X-API-Key": keys["write"][0], "If-Match": '"1"'},
        json={"name": "Updated synthetic activity"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Updated synthetic activity"


def test_aggregated_routes_keep_literal_activity_paths_before_dynamic_id(http):
    client, keys = http
    headers = {"X-API-Key": keys["read"][0]}

    summaries = client.get("/api/v1/activities/summaries", headers=headers)
    assert summaries.status_code != 422
    assert summaries.status_code != 404


def test_about_reports_workbench_version(http):
    client, _ = http
    response = client.get("/api/v1/about")
    assert response.status_code == 200
    assert response.json()["version"] == "v0.20.2+workbench.4"


@pytest.mark.parametrize(
    ("key_name", "path"),
    [
        ("gears_read", "/api/v1/gears"),
        ("health_read", "/api/v1/health/weight"),
        ("followers_read", "/api/v1/followers/follow-requests"),
        ("notifications_read", "/api/v1/notifications/number"),
        ("users_read", "/api/v1/users/id/1"),
    ],
)
def test_each_other_read_scope_accepts_its_http_endpoint_and_rejects_missing_scope(http, key_name, path):
    client, keys = http

    allowed = client.get(path, headers={"X-API-Key": keys[key_name][0]})
    assert allowed.status_code == 200, f"{path}: {allowed.status_code} {allowed.text}"
    assert allowed.headers["content-type"].startswith("application/json")

    denied = client.get(path, headers={"X-API-Key": keys["read"][0]})
    assert denied.status_code == 403, f"{path}: {denied.status_code} {denied.text}"


@pytest.mark.parametrize(
    ("key_name", "method", "path", "kwargs"),
    [
        (
            "gears_write",
            "put",
            "/api/v1/workbench/vehicles/00000000-0000-4000-8000-000000000001",
            {"json": {"instance_id": "synthetic-instance", "gear_id": 1}},
        ),
        ("health_write", "post", "/api/v1/health/weight", {"json": {"weight": 70.0}}),
        ("followers_write", "post", "/api/v1/followers/users/2/followers", {}),
        ("notifications_write", "put", "/api/v1/notifications/mark_all_as_read", {}),
    ],
)
def test_each_other_write_scope_accepts_a_scoped_write_and_rejects_missing_scope(http, key_name, method, path, kwargs):
    client, keys = http
    allowed = getattr(client, method)(path, headers={"X-API-Key": keys[key_name][0]}, **kwargs)
    assert allowed.status_code in {200, 201, 204}, f"{path}: {allowed.status_code} {allowed.text}"

    denied = getattr(client, method)(path, headers={"X-API-Key": keys["read"][0]}, **kwargs)
    assert denied.status_code == 403, f"{path}: {denied.status_code} {denied.text}"
