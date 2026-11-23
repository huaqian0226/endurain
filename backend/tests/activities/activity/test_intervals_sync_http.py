"""HTTP boundary tests for the workbench intervals.icu sync bridge."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._helpers.db import create_sqlite_session

STATUS_URL = "/api/v1/workbench/intervals-sync"
REQUEST_URL = "/api/v1/workbench/intervals-sync/requests"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Build an isolated FastAPI app with synthetic users, API keys, and a temp bridge dir."""
    import api
    import core.config as config
    import core.database as database
    import core.exceptions as exceptions
    from modules.auth.api_keys.models import UsersApiKeys
    from modules.auth.api_keys.utils import hash_api_key
    from modules.users.users.models import Users

    bridge_dir = tmp_path / "bridge"
    (bridge_dir / "trigger").mkdir(parents=True)
    (bridge_dir / "status").mkdir(parents=True)

    monkeypatch.setattr(config.settings, "WORKBENCH_INTERVALS_SYNC_DIR", str(bridge_dir))
    monkeypatch.setattr(config.settings, "WORKBENCH_INTERVALS_SYNC_USER_ID", None)
    monkeypatch.setattr(config.settings, "WORKBENCH_JIADANG_USER_ID", 1)

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

    keys = {
        "owner": ("endurain_m22_owner_full", 1, ["activities:read", "activities:upload"]),
        "owner_read_only": ("endurain_m22_owner_read", 1, ["activities:read"]),
        "owner_workbench_only": ("endurain_m22_owner_wb", 1, ["workbench:read"]),
        "other": ("endurain_m22_other_full", 2, ["activities:read", "activities:upload"]),
    }
    for raw, owner, scopes in keys.values():
        db.add(
            UsersApiKeys(
                id=str(uuid4()),
                user_id=owner,
                name="Synthetic M22 key",
                key_prefix="m22",
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

    with TestClient(app) as client:
        yield client, keys, bridge_dir
    db.close()


def _write_json(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_unauthenticated_requests_return_401(env):
    client, _, _ = env
    assert client.get(STATUS_URL).status_code == 401
    assert client.post(REQUEST_URL).status_code == 401


def test_feature_off_returns_enabled_false_and_404_on_post(env, monkeypatch):
    import core.config as config

    client, keys, _ = env
    monkeypatch.setattr(config.settings, "WORKBENCH_INTERVALS_SYNC_DIR", None)
    headers = {"X-API-Key": keys["owner"][0]}

    resp = client.get(STATUS_URL, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"enabled": False}

    post = client.post(REQUEST_URL, headers=headers)
    assert post.status_code == 404


def test_non_owner_gets_enabled_false_and_404_on_post(env):
    client, keys, _ = env
    headers = {"X-API-Key": keys["other"][0]}

    resp = client.get(STATUS_URL, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"enabled": False}

    post = client.post(REQUEST_URL, headers=headers)
    assert post.status_code == 404


def test_explicit_intervals_sync_user_id_overrides_jiadang_fallback(env, monkeypatch):
    import core.config as config

    client, keys, _ = env
    monkeypatch.setattr(config.settings, "WORKBENCH_INTERVALS_SYNC_USER_ID", 2)

    assert client.get(STATUS_URL, headers={"X-API-Key": keys["owner"][0]}).json() == {"enabled": False}
    assert client.post(REQUEST_URL, headers={"X-API-Key": keys["owner"][0]}).status_code == 404

    other_resp = client.get(STATUS_URL, headers={"X-API-Key": keys["other"][0]})
    assert other_resp.status_code == 200
    assert other_resp.json()["enabled"] is True


def test_api_key_scopes_enforced(env):
    client, keys, _ = env

    read_only = {"X-API-Key": keys["owner_read_only"][0]}
    assert client.get(STATUS_URL, headers=read_only).status_code == 200
    assert client.post(REQUEST_URL, headers=read_only).status_code == 403

    workbench_only = {"X-API-Key": keys["owner_workbench_only"][0]}
    assert client.get(STATUS_URL, headers=workbench_only).status_code == 403
    assert client.post(REQUEST_URL, headers=workbench_only).status_code == 403


def test_owner_post_writes_request_file_and_blocks_recent_repeat(env):
    client, keys, bridge_dir = env
    headers = {"X-API-Key": keys["owner"][0]}

    post = client.post(REQUEST_URL, headers=headers)
    assert post.status_code == 202, post.text
    body = post.json()
    assert body["accepted"] is True
    assert "requested_at" in body

    req_file = bridge_dir / "trigger" / "request.json"
    assert req_file.is_file()
    written = json.loads(req_file.read_text(encoding="utf-8"))
    assert set(written.keys()) == {"request_id", "requested_at"}
    assert len(written["request_id"]) == 32
    int(written["request_id"], 16)
    datetime.fromisoformat(written["requested_at"])

    status_resp = client.get(STATUS_URL, headers=headers)
    assert status_resp.status_code == 200
    status_body = status_resp.json()
    assert status_body["enabled"] is True
    assert status_body["state"] == "unknown"
    assert status_body["request_pending"] is True
    assert status_body["last_requested_at"] is not None

    repeat = client.post(REQUEST_URL, headers=headers)
    assert repeat.status_code == 409
    assert repeat.json()["detail"] == "recent"


def test_handled_recent_request_allows_new_post(env):
    client, keys, bridge_dir = env
    headers = {"X-API-Key": keys["owner"][0]}

    first = client.post(REQUEST_URL, headers=headers)
    assert first.status_code == 202
    req_id = json.loads((bridge_dir / "trigger" / "request.json").read_text(encoding="utf-8"))["request_id"]

    now = datetime.now(UTC)
    _write_json(
        bridge_dir / "status" / "status.json",
        {
            "schema": 1,
            "state": "idle",
            "trigger": "manual",
            "started_at": (now - timedelta(seconds=10)).isoformat().replace("+00:00", "Z"),
            "finished_at": now.isoformat().replace("+00:00", "Z"),
            "result": "ok",
            "counts": {"done": 2, "failed": 0, "gave_up": 0, "skipped": 1, "pending": 0},
            "handled_request_id": req_id,
        },
    )

    status_body = client.get(STATUS_URL, headers=headers).json()
    assert status_body["request_pending"] is False
    assert status_body["state"] == "idle"
    assert status_body["last_result"] == "ok"

    second = client.post(REQUEST_URL, headers=headers)
    assert second.status_code == 202


def test_running_status_returns_409_running_and_stale_running_returns_202(env):
    client, keys, bridge_dir = env
    headers = {"X-API-Key": keys["owner"][0]}
    status_file = bridge_dir / "status" / "status.json"

    recent_start = (datetime.now(UTC) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    _write_json(
        status_file,
        {
            "schema": 1,
            "state": "running",
            "trigger": "manual",
            "started_at": recent_start,
            "finished_at": None,
            "result": None,
            "counts": None,
            "handled_request_id": None,
        },
    )
    running_resp = client.post(REQUEST_URL, headers=headers)
    assert running_resp.status_code == 409
    assert running_resp.json()["detail"] == "running"

    stale_start = (datetime.now(UTC) - timedelta(minutes=31)).isoformat().replace("+00:00", "Z")
    _write_json(
        status_file,
        {
            "schema": 1,
            "state": "running",
            "trigger": "scheduled",
            "started_at": stale_start,
            "finished_at": None,
            "result": None,
            "counts": None,
            "handled_request_id": None,
        },
    )
    stale_resp = client.post(REQUEST_URL, headers=headers)
    assert stale_resp.status_code == 202


@pytest.mark.parametrize(
    "raw_content",
    [
        "{not valid json",
        json.dumps(["a", "list"]),
        json.dumps({"schema": 999, "state": "idle"}),
        json.dumps({"schema": 1, "state": "hacked_state"}),
        json.dumps({"schema": 1, "state": "idle", "result": "secret_leak_string"}),
        json.dumps({"schema": 1, "state": "idle", "trigger": "injected_trigger"}),
        json.dumps({"schema": 1, "state": "idle", "counts": {"done": "not_int"}}),
        json.dumps(
            {
                "schema": 1,
                "state": "idle",
                "counts": {"done": True, "failed": 0, "gave_up": 0, "skipped": 0, "pending": 0},
            }
        ),
    ],
)
def test_corrupt_or_unknown_status_file_returns_200_unknown_without_echoing_strings(env, raw_content):
    client, keys, bridge_dir = env
    headers = {"X-API-Key": keys["owner"][0]}
    (bridge_dir / "status" / "status.json").write_text(raw_content, encoding="utf-8")

    resp = client.get(STATUS_URL, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["state"] == "unknown"
    assert body["last_result"] is None
    assert body["trigger"] is None
    assert body["counts"] is None
    assert "secret_leak_string" not in resp.text
    assert "hacked_state" not in resp.text
    assert "injected_trigger" not in resp.text


def test_valid_status_returns_whitelisted_fields_only(env):
    client, keys, bridge_dir = env
    headers = {"X-API-Key": keys["owner"][0]}
    _write_json(
        bridge_dir / "status" / "status.json",
        {
            "schema": 1,
            "state": "idle",
            "trigger": "scheduled",
            "started_at": "2026-11-23T22:00:00Z",
            "finished_at": "2026-11-23T22:01:15Z",
            "result": "partial",
            "counts": {"done": 3, "failed": 1, "gave_up": 0, "skipped": 2, "pending": 0},
            "handled_request_id": "abc123",
            "arbitrary_extra": "should-never-appear",
        },
    )

    resp = client.get(STATUS_URL, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "enabled",
        "state",
        "last_started_at",
        "last_finished_at",
        "last_result",
        "counts",
        "trigger",
        "last_requested_at",
        "request_pending",
    }
    assert body["enabled"] is True
    assert body["state"] == "idle"
    assert body["trigger"] == "scheduled"
    assert body["last_result"] == "partial"
    assert body["counts"] == {"done": 3, "failed": 1, "gave_up": 0, "skipped": 2, "pending": 0}
    assert body["request_pending"] is False
    assert "should-never-appear" not in resp.text
    assert "abc123" not in resp.text


def test_missing_trigger_dir_returns_503_and_does_not_create_it(env):
    client, keys, bridge_dir = env
    headers = {"X-API-Key": keys["owner"][0]}
    trigger_dir = bridge_dir / "trigger"
    trigger_dir.rmdir()

    resp = client.post(REQUEST_URL, headers=headers)
    assert resp.status_code == 503
    assert not trigger_dir.exists()
