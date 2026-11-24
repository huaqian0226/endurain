"""Unified JWT and API-key authorization tests for import and job-poll routes (M26 R2)."""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests._helpers.db import create_sqlite_session

import model_registry
import modules.activities.activity_ingestion.constants as ingestion_constants
import modules.activities.activity_ingestion.router as ingestion_router
import modules.activities.activity_ingestion.schema as ingestion_schema
import modules.auth.api_keys.utils as api_keys_utils

model_registry.import_all_models()


def _synthetic_job(job_id: str = "11111111-1111-4111-8111-111111111111") -> ingestion_schema.ActivityIngestionJobRead:
    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    return ingestion_schema.ActivityIngestionJobRead(
        id=job_id,
        kind=ingestion_constants.IngestionJobKind.BULK_IMPORT,
        filename="export.zip",
        status=ingestion_constants.IngestionJobStatus.PENDING,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def env():
    """Isolated SQLite + full aggregated API router with real JWT and API-key auth."""
    import api
    import core.database as database
    import core.dependencies as core_dependencies
    import core.exceptions as exceptions
    from modules.activities.activity_ingestion.models import ActivityIngestionJob
    from modules.auth._internal.token_manager import get_token_manager
    from modules.auth.api_keys.models import UsersApiKeys
    from modules.auth.api_keys.utils import hash_api_key
    from modules.auth.utils import create_tokens
    from modules.users.users.models import Users
    from modules.users.users.schema import UsersRead

    db = create_sqlite_session()
    tokens: dict[int, str] = {}
    token_manager = get_token_manager()

    for user_id in (1, 2):
        user = Users(
            id=user_id,
            name=f"Synthetic importer {user_id}",
            username=f"synth_imp_{user_id}",
            email=f"synth_imp_{user_id}@example.com",
            preferred_language="en",
            access_type="regular",
            active=True,
        )
        db.add(user)
        db.flush()
        user_read = UsersRead.model_validate(user)
        _, _, access_token, _, _, _ = create_tokens(user_read, token_manager)
        tokens[user_id] = access_token

    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
    job_user1_id = "11111111-1111-4111-8111-111111111111"
    job_user2_id = "22222222-2222-4222-8222-222222222222"
    db.add(
        ActivityIngestionJob(
            id=job_user1_id,
            user_id=1,
            kind=ingestion_constants.IngestionJobKind.BULK_IMPORT,
            filename="user1.zip",
            status=ingestion_constants.IngestionJobStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
    )
    db.add(
        ActivityIngestionJob(
            id=job_user2_id,
            user_id=2,
            kind=ingestion_constants.IngestionJobKind.BULK_IMPORT,
            filename="user2.zip",
            status=ingestion_constants.IngestionJobStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()

    def make_key(
        user_id: int = 1,
        scopes: list[str] | None = None,
        *,
        temp_scopes: list[str] | None = None,
        temp_scopes_expires_at: datetime | None = None,
    ) -> tuple[str, str]:
        raw_key = f"endurain_{uuid4().hex}{uuid4().hex[:11]}"
        key_id = str(uuid4())
        db.add(
            UsersApiKeys(
                id=key_id,
                user_id=user_id,
                name="Synthetic import key",
                key_prefix=raw_key[9:17],
                key_hash=hash_api_key(raw_key),
                scopes=json.dumps(scopes if scopes is not None else ["users:read"]),
                created_at=now,
                is_active=True,
                temp_scopes=json.dumps(temp_scopes) if temp_scopes is not None else None,
                temp_scopes_expires_at=temp_scopes_expires_at,
            )
        )
        db.commit()
        return key_id, raw_key

    app = FastAPI()
    exceptions.register_exception_handlers(app)
    app.include_router(api.router)
    app.dependency_overrides[database.get_db] = lambda: db
    app.dependency_overrides[core_dependencies.get_storage] = lambda: object()

    with TestClient(app) as client:
        yield client, db, tokens, make_key, job_user1_id, job_user2_id

    db.close()


def _jwt_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Client-Type": "web"}


class TestBulkImportArchiveAuth:
    """POST /api/v1/activities/bulk-import requires activities:write (JWT or API key)."""

    def _call(self, client: TestClient, headers: dict[str, str]):
        with patch.object(
            ingestion_router.activity_ingestion_bulk_import_service,
            "accept_archive",
            return_value=_synthetic_job(),
        ) as accept:
            resp = client.post(
                "/api/v1/activities/bulk-import?source=strava",
                headers=headers,
                files={"file": ("export.zip", b"PK\x05\x06" + b"\x00" * 18, "application/zip")},
            )
        return resp, accept

    def test_jwt_base_temp_and_expired_scope(self, env, monkeypatch):
        client, _db, tokens, make_key, _, _ = env
        t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        current_time = [t0]
        monkeypatch.setattr(api_keys_utils, "utc_now", lambda: current_time[0])

        # Unauthenticated -> 401
        resp, accept = self._call(client, {})
        assert resp.status_code == 401
        accept.assert_not_called()

        # Browser JWT -> 202
        resp, accept = self._call(client, _jwt_headers(tokens[1]))
        assert resp.status_code == 202, resp.text
        assert accept.call_args.args[0] == 1

        # API key without activities:write -> 403
        _, read_only = make_key(scopes=["activities:read"])
        resp, accept = self._call(client, {"X-API-Key": read_only})
        assert resp.status_code == 403
        accept.assert_not_called()

        # API key with base activities:write -> 202
        _, base_write = make_key(scopes=["activities:write"])
        resp, accept = self._call(client, {"X-API-Key": base_write})
        assert resp.status_code == 202, resp.text
        assert accept.call_args.args[0] == 1

        # API key with unexpired temp activities:write -> 202
        _, temp_write = make_key(
            scopes=["activities:read"],
            temp_scopes=["activities:write"],
            temp_scopes_expires_at=t0 + timedelta(minutes=30),
        )
        resp, accept = self._call(client, {"X-API-Key": temp_write})
        assert resp.status_code == 202, resp.text
        assert accept.call_args.args[0] == 1

        # After temp expiry -> 403
        current_time[0] = t0 + timedelta(minutes=30)
        resp, accept = self._call(client, {"X-API-Key": temp_write})
        assert resp.status_code == 403
        accept.assert_not_called()


class TestBulkImportFolderAuth:
    """POST /api/v1/activities/bulk-import/folder requires activities:write (JWT or API key)."""

    def _call(self, client: TestClient, headers: dict[str, str]):
        with patch.object(
            ingestion_router.activity_ingestion_bulk_import_service,
            "start_from_directory",
            return_value=_synthetic_job(),
        ) as start:
            resp = client.post(
                "/api/v1/activities/bulk-import/folder?source=strava",
                headers=headers,
            )
        return resp, start

    def test_jwt_base_temp_and_expired_scope(self, env, monkeypatch):
        client, _db, tokens, make_key, _, _ = env
        t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        current_time = [t0]
        monkeypatch.setattr(api_keys_utils, "utc_now", lambda: current_time[0])

        # Browser JWT -> 202
        resp, start = self._call(client, _jwt_headers(tokens[1]))
        assert resp.status_code == 202, resp.text
        assert start.call_args.args[0] == 1

        # API key without activities:write -> 403
        _, read_only = make_key(scopes=["activities:read"])
        resp, start = self._call(client, {"X-API-Key": read_only})
        assert resp.status_code == 403
        start.assert_not_called()

        # API key with base activities:write -> 202
        _, base_write = make_key(scopes=["activities:write"])
        resp, start = self._call(client, {"X-API-Key": base_write})
        assert resp.status_code == 202, resp.text
        assert start.call_args.args[0] == 1

        # API key with unexpired temp activities:write -> 202
        _, temp_write = make_key(
            scopes=["activities:read"],
            temp_scopes=["activities:write"],
            temp_scopes_expires_at=t0 + timedelta(minutes=15),
        )
        resp, start = self._call(client, {"X-API-Key": temp_write})
        assert resp.status_code == 202, resp.text
        assert start.call_args.args[0] == 1

        # After temp expiry -> 403
        current_time[0] = t0 + timedelta(minutes=15)
        resp, start = self._call(client, {"X-API-Key": temp_write})
        assert resp.status_code == 403
        start.assert_not_called()


class TestIngestionJobPollAuth:
    """GET /api/v1/activities/ingestion-jobs/{job_id} requires activities:read and enforces owner isolation."""

    def test_jwt_base_temp_expired_and_ownership(self, env, monkeypatch):
        client, _db, tokens, make_key, job1_id, job2_id = env
        t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        current_time = [t0]
        monkeypatch.setattr(api_keys_utils, "utc_now", lambda: current_time[0])

        path1 = f"/api/v1/activities/ingestion-jobs/{job1_id}"
        path2 = f"/api/v1/activities/ingestion-jobs/{job2_id}"

        # Unauthenticated -> 401
        assert client.get(path1).status_code == 401

        # Browser JWT -> 200 for own job, 404 for another user's job
        own_jwt = client.get(path1, headers=_jwt_headers(tokens[1]))
        assert own_jwt.status_code == 200, own_jwt.text
        assert own_jwt.json()["id"] == job1_id
        assert client.get(path2, headers=_jwt_headers(tokens[1])).status_code == 404

        # API key without activities:read -> 403
        _, upload_only = make_key(scopes=["activities:upload"])
        assert client.get(path1, headers={"X-API-Key": upload_only}).status_code == 403

        # API key with base activities:read -> 200 for own job, 404 for other user's job
        _, user1_read = make_key(user_id=1, scopes=["activities:read"])
        _, user2_read = make_key(user_id=2, scopes=["activities:read"])
        resp = client.get(path1, headers={"X-API-Key": user1_read})
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == job1_id
        assert client.get(path2, headers={"X-API-Key": user1_read}).status_code == 404
        assert client.get(path1, headers={"X-API-Key": user2_read}).status_code == 404
        assert client.get(path2, headers={"X-API-Key": user2_read}).status_code == 200

        # API key with unexpired temp activities:read -> 200, after expiry -> 403
        _, temp_read = make_key(
            user_id=1,
            scopes=["gears:read"],
            temp_scopes=["activities:read"],
            temp_scopes_expires_at=t0 + timedelta(minutes=20),
        )
        assert client.get(path1, headers={"X-API-Key": temp_read}).status_code == 200
        current_time[0] = t0 + timedelta(minutes=20)
        assert client.get(path1, headers={"X-API-Key": temp_read}).status_code == 403


class TestStravaGearImportAuth:
    """POST /api/v1/strava/import/bikes and /shoes require gears:write (JWT or API key)."""

    @pytest.mark.parametrize(
        ("path", "filename", "csv_bytes"),
        [
            ("/api/v1/strava/import/bikes", "bikes.csv", b"Bike Name,Bike Brand,Bike Model\nSynthBike,BrandA,M1\n"),
            ("/api/v1/strava/import/shoes", "shoes.csv", b"Shoe Name,Shoe Brand,Shoe Model\nSynthShoe,BrandB,S1\n"),
        ],
    )
    def test_jwt_base_temp_and_expired_scope(self, env, monkeypatch, path: str, filename: str, csv_bytes: bytes):
        import modules.strava.router as strava_router

        client, _db, tokens, make_key, _, _ = env
        t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        current_time = [t0]
        monkeypatch.setattr(api_keys_utils, "utc_now", lambda: current_time[0])

        def send(headers: dict[str, str]):
            with patch.object(strava_router.gears_crud, "create_multiple_gears") as create_gears:
                resp = client.post(
                    path,
                    headers=headers,
                    files={"file": (filename, csv_bytes, "text/csv")},
                )
            return resp, create_gears

        # Unauthenticated -> 401
        resp, create_gears = send({})
        assert resp.status_code == 401
        create_gears.assert_not_called()

        # Browser JWT -> 201
        resp, create_gears = send(_jwt_headers(tokens[1]))
        assert resp.status_code == 201, resp.text
        assert create_gears.call_args.args[1] == 1

        # API key without gears:write -> 403
        _, read_only = make_key(scopes=["gears:read"])
        resp, create_gears = send({"X-API-Key": read_only})
        assert resp.status_code == 403
        create_gears.assert_not_called()

        # API key with base gears:write -> 201
        _, base_write = make_key(scopes=["gears:write"])
        resp, create_gears = send({"X-API-Key": base_write})
        assert resp.status_code == 201, resp.text
        assert create_gears.call_args.args[1] == 1

        # API key with unexpired temp gears:write -> 201
        _, temp_write = make_key(
            scopes=["gears:read"],
            temp_scopes=["gears:write"],
            temp_scopes_expires_at=t0 + timedelta(minutes=10),
        )
        resp, create_gears = send({"X-API-Key": temp_write})
        assert resp.status_code == 201, resp.text
        assert create_gears.call_args.args[1] == 1

        # After temp expiry -> 403
        current_time[0] = t0 + timedelta(minutes=10)
        resp, create_gears = send({"X-API-Key": temp_write})
        assert resp.status_code == 403
        create_gears.assert_not_called()
