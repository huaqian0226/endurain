"""Tests for temporary scope elevation on existing API keys (M26 R1)."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

import model_registry
import modules.auth.api_keys.models as api_keys_models
import modules.auth.api_keys.schema as api_keys_schema
import modules.auth.api_keys.utils as api_keys_utils
from tests._helpers.db import create_sqlite_session

# Ensure all SQLAlchemy relationships on Users are registered before any earlier
# unit test in tests/auth/ triggers mapper configuration.
model_registry.import_all_models()


@pytest.fixture
def env():
    """Isolated SQLite + full aggregated API router with real JWT and API-key auth."""
    import api
    import core.database as database
    import core.exceptions as exceptions
    from modules.auth._internal.token_manager import get_token_manager
    from modules.auth.api_keys.models import UsersApiKeys
    from modules.auth.api_keys.utils import hash_api_key
    from modules.auth.utils import create_tokens
    from modules.gears.gear.models import Gear
    from modules.users.users.models import Users
    from modules.users.users.schema import UsersRead

    db = create_sqlite_session()
    users = {}
    tokens = {}
    token_manager = get_token_manager()

    for user_id in (1, 2):
        user = Users(
            id=user_id,
            name=f"Synthetic user {user_id}",
            username=f"synth_temp_{user_id}",
            email=f"synth_temp_{user_id}@example.com",
            preferred_language="en",
            access_type="regular",
            active=True,
        )
        db.add(user)
        db.flush()
        users[user_id] = user
        user_read = UsersRead.model_validate(user)
        _, _, access_token, _, _, _ = create_tokens(user_read, token_manager)
        tokens[user_id] = access_token

    db.add(Gear(id=1, user_id=1, nickname="Synth Bike", gear_type=1))
    db.commit()

    def make_key(
        user_id: int = 1,
        scopes: list[str] | None = None,
        *,
        is_active: bool = True,
        expires_at: datetime | None = None,
        temp_scopes: list[str] | None = None,
        temp_scopes_expires_at: datetime | None = None,
    ) -> tuple[str, str]:
        raw_key = f"endurain_{uuid4().hex}{uuid4().hex[:11]}"
        key_id = str(uuid4())
        db.add(
            UsersApiKeys(
                id=key_id,
                user_id=user_id,
                name="Synthetic key",
                key_prefix=raw_key[9:17],
                key_hash=hash_api_key(raw_key),
                scopes=json.dumps(scopes if scopes is not None else ["activities:read"]),
                expires_at=expires_at,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                is_active=is_active,
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

    with TestClient(app) as client:
        yield client, db, tokens, make_key

    db.close()


def _jwt_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Client-Type": "web"}


class TestTempScopesModelAndSchema:
    """Model columns and Pydantic validation for temporary scope elevation."""

    def test_model_has_nullable_temp_scope_columns(self):
        model = api_keys_models.UsersApiKeys
        assert hasattr(model, "temp_scopes")
        assert hasattr(model, "temp_scopes_expires_at")
        assert model.temp_scopes.nullable is True
        assert model.temp_scopes_expires_at.nullable is True

    def test_schema_accepts_valid_scopes_and_duration_bounds(self):
        low = api_keys_schema.UsersApiKeyTempScopesUpdate(
            scopes=["gears:write"],
            duration_minutes=1,
        )
        high = api_keys_schema.UsersApiKeyTempScopesUpdate(
            scopes=["activities:write", "gears:write"],
            duration_minutes=10080,
        )
        assert low.duration_minutes == 1
        assert high.duration_minutes == 10080

    @pytest.mark.parametrize("duration", [0, -1, 10081, 999999])
    def test_schema_rejects_out_of_bounds_duration(self, duration: int):
        with pytest.raises(ValidationError):
            api_keys_schema.UsersApiKeyTempScopesUpdate(
                scopes=["gears:write"],
                duration_minutes=duration,
            )

    def test_schema_rejects_empty_scopes(self):
        with pytest.raises(ValidationError):
            api_keys_schema.UsersApiKeyTempScopesUpdate(
                scopes=[],
                duration_minutes=60,
            )

    @pytest.mark.parametrize("bad_scope", ["profile", "users:write", "admin:all", "unknown:scope"])
    def test_schema_rejects_scopes_outside_whitelist(self, bad_scope: str):
        with pytest.raises(ValidationError):
            api_keys_schema.UsersApiKeyTempScopesUpdate(
                scopes=[bad_scope],
                duration_minutes=60,
            )


class TestTempScopesLifecycle:
    """End-to-end HTTP tests for grant, effective scopes, expiry, and revoke."""

    def test_legacy_key_without_temp_scopes_returns_base_effective_scopes(self, env):
        client, _db, tokens, make_key = env
        key_id, raw_key = make_key(scopes=["activities:read"])

        resp = client.get("/api/v1/profile/api_keys", headers=_jwt_headers(tokens[1]))
        assert resp.status_code == 200
        item = next(k for k in resp.json() if k["id"] == key_id)
        assert item["scopes"] == '["activities:read"]'
        assert item["temp_scopes"] == []
        assert item["temp_scopes_expires_at"] is None
        assert item["effective_scopes"] == ["activities:read"]

        # Base scope works, ungranted scope is 403.
        assert client.get("/api/v1/activities", headers={"X-API-Key": raw_key}).status_code == 200
        assert client.get("/api/v1/gears", headers={"X-API-Key": raw_key}).status_code == 403

    def test_grant_and_replace_temp_scopes_elevates_auth_and_auto_expires(self, env, monkeypatch):
        client, _db, tokens, make_key = env
        t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        current_time = [t0]
        monkeypatch.setattr(api_keys_utils, "utc_now", lambda: current_time[0])

        key_id, raw_key = make_key(scopes=["activities:read"])

        # Initially denied gears:read
        assert client.get("/api/v1/gears", headers={"X-API-Key": raw_key}).status_code == 403

        # Grant temporary gears:read for 60 minutes
        grant = client.put(
            f"/api/v1/profile/api_keys/{key_id}/temp_scopes",
            headers=_jwt_headers(tokens[1]),
            json={"scopes": ["gears:read"], "duration_minutes": 60},
        )
        assert grant.status_code == 200, grant.text
        body = grant.json()
        assert body["scopes"] == '["activities:read"]'
        assert body["temp_scopes"] == ["gears:read"]
        assert body["temp_scopes_expires_at"] == "2026-06-01T13:00:00Z"
        assert body["effective_scopes"] == ["activities:read", "gears:read"]

        # Now allowed while unexpired
        assert client.get("/api/v1/gears", headers={"X-API-Key": raw_key}).status_code == 200
        assert client.get("/api/v1/activities", headers={"X-API-Key": raw_key}).status_code == 200
        # Still denied ungranted scope
        assert client.get("/api/v1/health/weight", headers={"X-API-Key": raw_key}).status_code == 403

        # Replace temp scopes with health:read for 15 minutes
        replace = client.put(
            f"/api/v1/profile/api_keys/{key_id}/temp_scopes",
            headers=_jwt_headers(tokens[1]),
            json={"scopes": ["health:read"], "duration_minutes": 15},
        )
        assert replace.status_code == 200
        rbody = replace.json()
        assert rbody["temp_scopes"] == ["health:read"]
        assert rbody["temp_scopes_expires_at"] == "2026-06-01T12:15:00Z"
        assert rbody["effective_scopes"] == ["activities:read", "health:read"]

        # Previous temp scope is gone; new temp scope is active
        assert client.get("/api/v1/gears", headers={"X-API-Key": raw_key}).status_code == 403
        assert client.get("/api/v1/health/weight", headers={"X-API-Key": raw_key}).status_code == 200

        # Advance clock to exact expiry -> must auto-expire (now < expires_at is False)
        current_time[0] = datetime(2026, 6, 1, 12, 15, 0, tzinfo=UTC)
        assert client.get("/api/v1/health/weight", headers={"X-API-Key": raw_key}).status_code == 403
        # Base scope still works
        assert client.get("/api/v1/activities", headers={"X-API-Key": raw_key}).status_code == 200

        # List endpoint reports live (expired) temp scopes as empty / null
        listed = client.get("/api/v1/profile/api_keys", headers=_jwt_headers(tokens[1]))
        assert listed.status_code == 200
        item = next(k for k in listed.json() if k["id"] == key_id)
        assert item["temp_scopes"] == []
        assert item["temp_scopes_expires_at"] is None
        assert item["effective_scopes"] == ["activities:read"]

    def test_early_revoke_removes_temp_scopes_immediately(self, env, monkeypatch):
        client, _db, tokens, make_key = env
        t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(api_keys_utils, "utc_now", lambda: t0)

        key_id, raw_key = make_key(scopes=["activities:read"])

        grant = client.put(
            f"/api/v1/profile/api_keys/{key_id}/temp_scopes",
            headers=_jwt_headers(tokens[1]),
            json={"scopes": ["gears:read"], "duration_minutes": 60},
        )
        assert grant.status_code == 200
        assert client.get("/api/v1/gears", headers={"X-API-Key": raw_key}).status_code == 200

        revoke = client.delete(
            f"/api/v1/profile/api_keys/{key_id}/temp_scopes",
            headers=_jwt_headers(tokens[1]),
        )
        assert revoke.status_code == 200
        body = revoke.json()
        assert body["temp_scopes"] == []
        assert body["temp_scopes_expires_at"] is None
        assert body["effective_scopes"] == ["activities:read"]

        # Immediately blocked again, base scope unaffected
        assert client.get("/api/v1/gears", headers={"X-API-Key": raw_key}).status_code == 403
        assert client.get("/api/v1/activities", headers={"X-API-Key": raw_key}).status_code == 200


class TestTempScopesSecurityBoundaries:
    """Authorization, ownership, and revoked/expired key invariants."""

    def test_api_key_cannot_self_elevate_or_revoke_temp_scopes(self, env):
        client, _db, _tokens, make_key = env
        key_id, raw_key = make_key(scopes=["activities:read", "gears:write"])

        put_resp = client.put(
            f"/api/v1/profile/api_keys/{key_id}/temp_scopes",
            headers={"X-API-Key": raw_key, "X-Client-Type": "web"},
            json={"scopes": ["health:write"], "duration_minutes": 60},
        )
        assert put_resp.status_code in {401, 403}

        del_resp = client.delete(
            f"/api/v1/profile/api_keys/{key_id}/temp_scopes",
            headers={"X-API-Key": raw_key, "X-Client-Type": "web"},
        )
        assert del_resp.status_code in {401, 403}

    def test_cannot_elevate_other_users_or_unknown_key(self, env):
        client, _db, tokens, make_key = env
        other_key_id, _ = make_key(user_id=2, scopes=["activities:read"])

        other_resp = client.put(
            f"/api/v1/profile/api_keys/{other_key_id}/temp_scopes",
            headers=_jwt_headers(tokens[1]),
            json={"scopes": ["gears:read"], "duration_minutes": 30},
        )
        assert other_resp.status_code == 404

        missing_resp = client.put(
            "/api/v1/profile/api_keys/00000000-0000-4000-8000-000000000000/temp_scopes",
            headers=_jwt_headers(tokens[1]),
            json={"scopes": ["gears:read"], "duration_minutes": 30},
        )
        assert missing_resp.status_code == 404

        del_other = client.delete(
            f"/api/v1/profile/api_keys/{other_key_id}/temp_scopes",
            headers=_jwt_headers(tokens[1]),
        )
        assert del_other.status_code == 404

    def test_revoked_key_cannot_be_elevated_and_temp_grant_never_revives_it(self, env, monkeypatch):
        client, _db, tokens, make_key = env
        t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(api_keys_utils, "utc_now", lambda: t0)

        revoked_id, revoked_raw = make_key(
            scopes=["activities:read"],
            is_active=False,
            temp_scopes=["gears:read"],
            temp_scopes_expires_at=t0 + timedelta(hours=1),
        )

        # Even if DB has unexpired temp_scopes on a revoked key, auth rejects with 401
        assert client.get("/api/v1/gears", headers={"X-API-Key": revoked_raw}).status_code == 401
        assert client.get("/api/v1/activities", headers={"X-API-Key": revoked_raw}).status_code == 401

        # Cannot grant temp scopes to a revoked key
        resp = client.put(
            f"/api/v1/profile/api_keys/{revoked_id}/temp_scopes",
            headers=_jwt_headers(tokens[1]),
            json={"scopes": ["gears:read"], "duration_minutes": 30},
        )
        assert resp.status_code == 400

    def test_expired_key_cannot_be_elevated_and_temp_grant_never_revives_it(self, env, monkeypatch):
        client, _db, tokens, make_key = env
        t0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
        monkeypatch.setattr(api_keys_utils, "utc_now", lambda: t0)

        expired_id, expired_raw = make_key(
            scopes=["activities:read"],
            expires_at=t0 - timedelta(minutes=5),
            temp_scopes=["gears:read"],
            temp_scopes_expires_at=t0 + timedelta(hours=1),
        )

        # Even with unexpired temp_scopes, expired key is rejected with 401
        assert client.get("/api/v1/gears", headers={"X-API-Key": expired_raw}).status_code == 401

        # Cannot grant temp scopes to an expired key
        resp = client.put(
            f"/api/v1/profile/api_keys/{expired_id}/temp_scopes",
            headers=_jwt_headers(tokens[1]),
            json={"scopes": ["gears:read"], "duration_minutes": 30},
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        "payload",
        [
            {"scopes": ["profile"], "duration_minutes": 60},
            {"scopes": ["users:write"], "duration_minutes": 60},
            {"scopes": [], "duration_minutes": 60},
            {"scopes": ["gears:read"], "duration_minutes": 0},
            {"scopes": ["gears:read"], "duration_minutes": 10081},
            {"scopes": ["gears:read"], "duration_minutes": -10},
        ],
    )
    def test_invalid_grant_payload_returns_422(self, env, payload):
        client, _db, tokens, make_key = env
        key_id, _ = make_key(scopes=["activities:read"])

        resp = client.put(
            f"/api/v1/profile/api_keys/{key_id}/temp_scopes",
            headers=_jwt_headers(tokens[1]),
            json=payload,
        )
        assert resp.status_code == 422
