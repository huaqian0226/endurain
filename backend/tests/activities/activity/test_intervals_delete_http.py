"""HTTP boundary tests for workbench intervals.icu delete lookup and delete requests."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._helpers.db import create_sqlite_session

STATUS_URL = "/api/v1/workbench/intervals-sync"
SYNC_REQUEST_URL = "/api/v1/workbench/intervals-sync/requests"
ACTIVITY_LOOKUP_URL = "/api/v1/workbench/intervals-sync/activities/{activity_id}"
DELETE_REQUEST_URL = "/api/v1/workbench/intervals-sync/delete-requests"


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
    (bridge_dir / "delete-requests").mkdir(parents=True)

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
        "owner": (
            "endurain_m23_owner_full",
            1,
            ["activities:read", "activities:write", "activities:upload"],
        ),
        "owner_read_only": ("endurain_m23_owner_read", 1, ["activities:read"]),
        "owner_upload_only": ("endurain_m23_owner_upload", 1, ["activities:upload"]),
        "owner_workbench_only": ("endurain_m23_owner_wb", 1, ["workbench:read"]),
        "other": (
            "endurain_m23_other_full",
            2,
            ["activities:read", "activities:write", "activities:upload"],
        ),
    }
    for raw, owner, scopes in keys.values():
        db.add(
            UsersApiKeys(
                id=str(uuid4()),
                user_id=owner,
                name="Synthetic M23 key",
                key_prefix="m23",
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


# ---------------------------------------------------------------------------
# Acceptance 1: GET /api/v1/workbench/intervals-sync/activities/{activity_id}
# ---------------------------------------------------------------------------


def test_lookup_returns_intervals_id_for_owner_and_null_for_others_or_disabled(env, monkeypatch):
    import core.config as config

    client, keys, bridge_dir = env
    _write_json(
        bridge_dir / "status" / "imported.json",
        {"schema": 1, "activities": {"7": "i42", "9": "9876543210"}},
    )

    owner_headers = {"X-API-Key": keys["owner_read_only"][0]}
    resp7 = client.get(ACTIVITY_LOOKUP_URL.format(activity_id=7), headers=owner_headers)
    assert resp7.status_code == 200
    assert resp7.json() == {"intervals_id": "i42"}

    resp9 = client.get(ACTIVITY_LOOKUP_URL.format(activity_id=9), headers=owner_headers)
    assert resp9.status_code == 200
    assert resp9.json() == {"intervals_id": "9876543210"}

    resp8 = client.get(ACTIVITY_LOOKUP_URL.format(activity_id=8), headers=owner_headers)
    assert resp8.status_code == 200
    assert resp8.json() == {"intervals_id": None}

    other_resp = client.get(
        ACTIVITY_LOOKUP_URL.format(activity_id=7),
        headers={"X-API-Key": keys["other"][0]},
    )
    assert other_resp.status_code == 200
    assert other_resp.json() == {"intervals_id": None}

    monkeypatch.setattr(config.settings, "WORKBENCH_INTERVALS_SYNC_DIR", None)
    off_resp = client.get(ACTIVITY_LOOKUP_URL.format(activity_id=7), headers=owner_headers)
    assert off_resp.status_code == 200
    assert off_resp.json() == {"intervals_id": None}


def test_lookup_enforces_auth_and_scope(env):
    client, keys, _ = env
    assert client.get(ACTIVITY_LOOKUP_URL.format(activity_id=7)).status_code == 401
    assert (
        client.get(
            ACTIVITY_LOOKUP_URL.format(activity_id=7),
            headers={"X-API-Key": keys["owner_workbench_only"][0]},
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "raw_content",
    [
        "{not valid json",
        json.dumps(["a", "list"]),
        json.dumps({"schema": 2, "activities": {"7": "i42"}}),
        json.dumps({"schema": 1, "activities": ["i42"]}),
        json.dumps({"schema": 1, "activities": {"7": "../etc/passwd"}}),
        json.dumps({"schema": 1, "activities": {"7": "i42\n"}}),
        json.dumps({"schema": 1, "activities": {"7": "x42"}}),
        json.dumps({"schema": 1, "activities": {"7": "i" + "1" * 21}}),
        json.dumps({"schema": 1, "activities": {"7": ""}}),
        json.dumps({"schema": 1, "activities": {"7": 42}}),
    ],
)
def test_lookup_handles_corrupt_or_invalid_imported_json_as_null(env, raw_content):
    client, keys, bridge_dir = env
    (bridge_dir / "status" / "imported.json").write_text(raw_content, encoding="utf-8")

    resp = client.get(
        ACTIVITY_LOOKUP_URL.format(activity_id=7),
        headers={"X-API-Key": keys["owner"][0]},
    )
    assert resp.status_code == 200
    assert resp.json() == {"intervals_id": None}


# ---------------------------------------------------------------------------
# Acceptance 2 & 7: POST /api/v1/workbench/intervals-sync/delete-requests
# ---------------------------------------------------------------------------


def test_delete_request_writes_file_and_trigger_and_is_idempotent(env):
    client, keys, bridge_dir = env
    _write_json(bridge_dir / "status" / "imported.json", {"schema": 1, "activities": {"7": "i42"}})
    headers = {"X-API-Key": keys["owner"][0]}

    # Note: activity 7 does not exist in DB; endpoint must still accept.
    first = client.post(DELETE_REQUEST_URL, json={"activity_id": 7}, headers=headers)
    assert first.status_code == 202, first.text
    first_body = first.json()
    assert first_body["accepted"] is True
    assert first_body["intervals_id"] == "i42"
    req_id = first_body["request_id"]
    assert isinstance(req_id, str) and len(req_id) == 32
    int(req_id, 16)

    req_file = bridge_dir / "delete-requests" / f"{req_id}.json"
    assert req_file.is_file()
    written = json.loads(req_file.read_text(encoding="utf-8"))
    assert set(written.keys()) == {"schema", "request_id", "activity_id", "intervals_id", "requested_at"}
    assert written["schema"] == 1
    assert written["request_id"] == req_id
    assert written["activity_id"] == 7
    assert written["intervals_id"] == "i42"
    datetime.fromisoformat(written["requested_at"])
    raw_written = req_file.read_text(encoding="utf-8")
    assert "synthetic1" not in raw_written
    assert "user_id" not in raw_written

    # Trigger file also written in M22 format when no unhandled trigger exists.
    trigger_file = bridge_dir / "trigger" / "request.json"
    assert trigger_file.is_file()
    trigger_data = json.loads(trigger_file.read_text(encoding="utf-8"))
    assert set(trigger_data.keys()) == {"request_id", "requested_at"}
    assert len(trigger_data["request_id"]) == 32
    int(trigger_data["request_id"], 16)
    datetime.fromisoformat(trigger_data["requested_at"])

    # Repeat POST for same unhandled activity -> 200 with same request_id, no extra file.
    second = client.post(DELETE_REQUEST_URL, json={"activity_id": 7}, headers=headers)
    assert second.status_code == 200, second.text
    assert second.json() == first_body
    delete_files = list((bridge_dir / "delete-requests").glob("*.json"))
    assert len(delete_files) == 1

    # Once marked handled in status.json, a subsequent POST creates a new request (202).
    _write_json(
        bridge_dir / "status" / "status.json",
        {
            "schema": 1,
            "state": "idle",
            "handled_request_id": trigger_data["request_id"],
            "handled_delete_request_ids": [req_id],
        },
    )
    third = client.post(DELETE_REQUEST_URL, json={"activity_id": 7}, headers=headers)
    assert third.status_code == 202, third.text
    assert third.json()["request_id"] != req_id


def test_delete_request_preserves_unhandled_trigger_and_replaces_handled_trigger(env):
    client, keys, bridge_dir = env
    _write_json(
        bridge_dir / "status" / "imported.json",
        {"schema": 1, "activities": {"7": "i42", "8": "i43"}},
    )
    headers = {"X-API-Key": keys["owner"][0]}

    # Existing unhandled trigger must NOT be overwritten.
    existing_trigger = {"request_id": "a" * 32, "requested_at": "2026-11-23T18:00:00Z"}
    _write_json(bridge_dir / "trigger" / "request.json", existing_trigger)

    resp7 = client.post(DELETE_REQUEST_URL, json={"activity_id": 7}, headers=headers)
    assert resp7.status_code == 202
    assert json.loads((bridge_dir / "trigger" / "request.json").read_text(encoding="utf-8")) == existing_trigger

    # Once that trigger is marked handled, a new delete request writes a fresh trigger.
    _write_json(
        bridge_dir / "status" / "status.json",
        {"schema": 1, "state": "idle", "handled_request_id": "a" * 32},
    )
    resp8 = client.post(DELETE_REQUEST_URL, json={"activity_id": 8}, headers=headers)
    assert resp8.status_code == 202
    updated_trigger = json.loads((bridge_dir / "trigger" / "request.json").read_text(encoding="utf-8"))
    assert updated_trigger["request_id"] != "a" * 32


def test_delete_request_rejects_not_imported_auth_scope_non_owner_and_disabled(env, monkeypatch):
    import core.config as config

    client, keys, bridge_dir = env
    _write_json(bridge_dir / "status" / "imported.json", {"schema": 1, "activities": {"7": "i42"}})

    # Not imported -> 409 not_imported
    not_imp = client.post(
        DELETE_REQUEST_URL,
        json={"activity_id": 8},
        headers={"X-API-Key": keys["owner"][0]},
    )
    assert not_imp.status_code == 409
    assert not_imp.json()["detail"] == "not_imported"
    assert list((bridge_dir / "delete-requests").glob("*.json")) == []

    # Unauthenticated -> 401
    assert client.post(DELETE_REQUEST_URL, json={"activity_id": 7}).status_code == 401

    # Read-only or upload-only key -> 403
    assert (
        client.post(
            DELETE_REQUEST_URL,
            json={"activity_id": 7},
            headers={"X-API-Key": keys["owner_read_only"][0]},
        ).status_code
        == 403
    )
    assert (
        client.post(
            DELETE_REQUEST_URL,
            json={"activity_id": 7},
            headers={"X-API-Key": keys["owner_upload_only"][0]},
        ).status_code
        == 403
    )

    # Non-owner -> 404
    assert (
        client.post(
            DELETE_REQUEST_URL,
            json={"activity_id": 7},
            headers={"X-API-Key": keys["other"][0]},
        ).status_code
        == 404
    )

    # Feature disabled -> 404
    monkeypatch.setattr(config.settings, "WORKBENCH_INTERVALS_SYNC_DIR", None)
    assert (
        client.post(
            DELETE_REQUEST_URL,
            json={"activity_id": 7},
            headers={"X-API-Key": keys["owner"][0]},
        ).status_code
        == 404
    )


def test_delete_request_returns_503_when_dirs_missing_without_creating_them(env):
    client, keys, bridge_dir = env
    _write_json(bridge_dir / "status" / "imported.json", {"schema": 1, "activities": {"7": "i42"}})
    headers = {"X-API-Key": keys["owner"][0]}

    delete_dir = bridge_dir / "delete-requests"
    delete_dir.rmdir()
    resp = client.post(DELETE_REQUEST_URL, json={"activity_id": 7}, headers=headers)
    assert resp.status_code == 503
    assert not delete_dir.exists()

    delete_dir.mkdir()
    trigger_dir = bridge_dir / "trigger"
    trigger_dir.rmdir()
    resp2 = client.post(DELETE_REQUEST_URL, json={"activity_id": 7}, headers=headers)
    assert resp2.status_code == 503
    assert not trigger_dir.exists()
    assert list(delete_dir.glob("*.json")) == []


# ---------------------------------------------------------------------------
# Acceptance 3: GET /api/v1/workbench/intervals-sync last_delete & pending_deletes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("result", ["ok", "not_found", "rejected", "failed", "pending"])
def test_status_exposes_whitelisted_last_delete_and_pending_count(env, result):
    client, keys, bridge_dir = env
    headers = {"X-API-Key": keys["owner"][0]}
    _write_json(
        bridge_dir / "status" / "status.json",
        {
            "schema": 1,
            "state": "idle",
            "trigger": "manual",
            "started_at": "2026-11-23T18:00:00Z",
            "finished_at": "2026-11-23T18:00:05Z",
            "result": "ok",
            "counts": {"done": 1, "failed": 0, "gave_up": 0, "skipped": 0, "pending": 0},
            "handled_request_id": "req-1",
            "handled_delete_request_ids": ["1" * 32],
            "last_delete": {
                "requested_at": "2026-11-23T17:59:50Z",
                "finished_at": None if result == "pending" else "2026-11-23T18:00:04Z",
                "result": result,
                "activity_id": 7,
                "secret_extra": "must-not-leak",
            },
        },
    )
    # One handled delete file, one unhandled delete file, one corrupt file
    _write_json(
        bridge_dir / "delete-requests" / f"{'1' * 32}.json",
        {
            "schema": 1,
            "request_id": "1" * 32,
            "activity_id": 5,
            "intervals_id": "i5",
            "requested_at": "2026-11-23T17:50:00Z",
        },
    )
    _write_json(
        bridge_dir / "delete-requests" / f"{'2' * 32}.json",
        {
            "schema": 1,
            "request_id": "2" * 32,
            "activity_id": 7,
            "intervals_id": "i42",
            "requested_at": "2026-11-23T17:59:50Z",
        },
    )
    (bridge_dir / "delete-requests" / "corrupt.json").write_text("{bad", encoding="utf-8")

    resp = client.get(STATUS_URL, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["pending_deletes"] == 1
    assert set(body["last_delete"].keys()) == {"requested_at", "finished_at", "result", "activity_id"}
    assert body["last_delete"]["result"] == result
    assert body["last_delete"]["activity_id"] == 7
    assert "must-not-leak" not in resp.text


@pytest.mark.parametrize(
    "bad_last_delete",
    [
        "not-a-dict",
        {"result": "secret_leak_result", "activity_id": 7, "requested_at": "2026-11-23T18:00:00Z"},
        {"result": "ok", "activity_id": "7", "requested_at": "2026-11-23T18:00:00Z"},
        {"result": "ok", "activity_id": True, "requested_at": "2026-11-23T18:00:00Z"},
        {"result": "ok", "activity_id": 0, "requested_at": "2026-11-23T18:00:00Z"},
        {"result": "ok", "activity_id": 7, "requested_at": "not-a-date"},
        {"result": "ok", "activity_id": 7, "finished_at": "not-a-date"},
    ],
)
def test_status_ignores_corrupt_last_delete_as_null_without_500(env, bad_last_delete):
    client, keys, bridge_dir = env
    headers = {"X-API-Key": keys["owner"][0]}
    _write_json(
        bridge_dir / "status" / "status.json",
        {
            "schema": 1,
            "state": "idle",
            "trigger": "scheduled",
            "started_at": "2026-11-23T22:00:00Z",
            "finished_at": "2026-11-23T22:00:10Z",
            "result": "ok",
            "counts": {"done": 1, "failed": 0, "gave_up": 0, "skipped": 0, "pending": 0},
            "last_delete": bad_last_delete,
        },
    )

    resp = client.get(STATUS_URL, headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "idle"
    assert body["last_result"] == "ok"
    assert body["last_delete"] is None
    assert "secret_leak_result" not in resp.text


# ---------------------------------------------------------------------------
# Acceptance 9: Legacy state without imported.json / delete-requests / new fields
# ---------------------------------------------------------------------------


def test_legacy_bridge_without_m23_files_or_fields_works_and_m22_sync_unchanged(env):
    client, keys, bridge_dir = env
    headers = {"X-API-Key": keys["owner"][0]}
    (bridge_dir / "delete-requests").rmdir()
    _write_json(
        bridge_dir / "status" / "status.json",
        {
            "schema": 1,
            "state": "idle",
            "trigger": "scheduled",
            "started_at": "2026-11-23T22:00:00Z",
            "finished_at": "2026-11-23T22:00:10Z",
            "result": "ok",
            "counts": {"done": 2, "failed": 0, "gave_up": 0, "skipped": 0, "pending": 0},
        },
    )

    status_resp = client.get(STATUS_URL, headers=headers)
    assert status_resp.status_code == 200
    body = status_resp.json()
    assert body["enabled"] is True
    assert body["state"] == "idle"
    assert body["last_result"] == "ok"
    assert body["last_delete"] is None
    assert body["pending_deletes"] == 0

    lookup_resp = client.get(ACTIVITY_LOOKUP_URL.format(activity_id=7), headers=headers)
    assert lookup_resp.status_code == 200
    assert lookup_resp.json() == {"intervals_id": None}

    sync_resp = client.post(SYNC_REQUEST_URL, headers=headers)
    assert sync_resp.status_code == 202
    assert (bridge_dir / "trigger" / "request.json").is_file()
