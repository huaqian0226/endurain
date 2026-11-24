"""User API key management endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import core.database as core_database
import modules.auth._internal.internal_dependencies as auth_internal_dependencies
import modules.auth._internal.services.step_up_service as step_up_service
import modules.auth.api_keys.crud as auth_api_keys_crud
import modules.auth.api_keys.schema as api_keys_schema
import modules.auth.api_keys.utils as api_keys_utils
import modules.auth.dependencies as auth_dependencies
import modules.auth.identity_service as auth_identity_service
import modules.users.users.crud as users_crud

# Define the API router
router = APIRouter()


def _serialize_api_key(db_api_key: object) -> api_keys_schema.UsersApiKeyRead:
    """Build a ``UsersApiKeyRead`` response with live temporary and effective scopes.

    Args:
        db_api_key: API key ORM object.

    Returns:
        Serialized ``UsersApiKeyRead`` payload.
    """
    now = api_keys_utils.utc_now()
    live_temp_scopes, live_temp_expires_at = api_keys_utils.get_live_temp_scopes(db_api_key, now=now)
    effective_scopes = api_keys_utils.get_effective_scopes(db_api_key, now=now)
    return api_keys_schema.UsersApiKeyRead(
        id=db_api_key.id,  # type: ignore[attr-defined]
        user_id=db_api_key.user_id,  # type: ignore[attr-defined]
        name=db_api_key.name,  # type: ignore[attr-defined]
        key_prefix=db_api_key.key_prefix,  # type: ignore[attr-defined]
        scopes=db_api_key.scopes,  # type: ignore[attr-defined]
        expires_at=db_api_key.expires_at,  # type: ignore[attr-defined]
        last_used_at=db_api_key.last_used_at,  # type: ignore[attr-defined]
        created_at=db_api_key.created_at,  # type: ignore[attr-defined]
        is_active=db_api_key.is_active,  # type: ignore[attr-defined]
        temp_scopes=live_temp_scopes,
        temp_scopes_expires_at=live_temp_expires_at,
        effective_scopes=effective_scopes,
    )


@router.get(
    "",
    response_model=list[api_keys_schema.UsersApiKeyRead],
    status_code=status.HTTP_200_OK,
)
async def get_user_api_keys(
    token_user_id: Annotated[
        int,
        Depends(auth_internal_dependencies.get_sub_from_access_token),
    ],
    db: Annotated[Session, Depends(core_database.get_db)],
) -> list[api_keys_schema.UsersApiKeyRead]:
    """
    Retrieve all API keys for the authenticated user.

    Args:
        token_user_id: User ID from access token.
        db: Database session dependency.

    Returns:
        List of API key objects. Raw keys and hashes
        are never included.
    """
    keys = auth_api_keys_crud.get_api_keys_by_user_id(token_user_id, db)
    return [_serialize_api_key(key) for key in keys]


@router.post(
    "",
    response_model=api_keys_schema.UsersApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_user_api_key(
    data: api_keys_schema.UsersApiKeyCreate,
    token_user_id: Annotated[
        int,
        Depends(auth_internal_dependencies.get_sub_from_access_token),
    ],
    identity_service: Annotated[
        auth_identity_service.IdentityService,
        Depends(auth_identity_service.get_identity_service),
    ],
    step_up_store: Annotated[
        auth_dependencies.StepUpStore,
        Depends(auth_dependencies.get_step_up_attempts),
    ],
    db: Annotated[Session, Depends(core_database.get_db)],
) -> api_keys_schema.UsersApiKeyCreated:
    """
    Create a new API key for the authenticated user.

    The raw key is returned once in this response and
    cannot be retrieved again. Requested scopes must be
    supported by API-key authentication.

    Step-up verification is required (current password,
    plus MFA code when MFA is enabled). API keys grant
    persistent, long-lived access — a stolen access
    token alone must not be sufficient to mint one.

    Args:
        data: Key creation data (name, scopes, expiry,
            step-up credentials).
        token_user_id: User ID from access token.
        identity_service: Identity service dependency.
        db: Database session dependency.

    Returns:
        Created API key including the raw key string.

    Raises:
        HTTPException: 401 if step-up verification fails.
        HTTPException: 400 if scopes are not supported for API keys.
        HTTPException: 404 if the user is not found.
    """
    db_user = users_crud.get_user_by_id(token_user_id, db)
    if db_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    step_up_service.verify_step_up_credentials(
        token_user_id,
        data.current_password,
        data.mfa_code,
        identity_service,
        step_up_store,
        db,
    )

    try:
        api_keys_utils.validate_api_key_scopes(data.scopes, db_user.access_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    db_api_key, raw_key = auth_api_keys_crud.create_api_key(token_user_id, data, db)
    serialized = _serialize_api_key(db_api_key)

    return api_keys_schema.UsersApiKeyCreated(
        **serialized.model_dump(),
        key=raw_key,
    )


@router.put(
    "/{api_key_id}/temp_scopes",
    response_model=api_keys_schema.UsersApiKeyRead,
    status_code=status.HTTP_200_OK,
)
async def grant_user_api_key_temp_scopes(
    api_key_id: str,
    data: api_keys_schema.UsersApiKeyTempScopesUpdate,
    token_user_id: Annotated[
        int,
        Depends(auth_internal_dependencies.get_sub_from_access_token),
    ],
    db: Annotated[Session, Depends(core_database.get_db)],
) -> api_keys_schema.UsersApiKeyRead:
    """
    Grant or replace temporary elevated scopes on an active API key.

    JWT-only: API keys cannot elevate themselves or other keys.

    Args:
        api_key_id: UUID of the API key to elevate.
        data: Temporary scopes and duration in minutes (1 to 10080).
        token_user_id: User ID from access token.
        db: Database session dependency.

    Returns:
        Updated API key object with live temporary and effective scopes.

    Raises:
        HTTPException: 404 if the key does not belong to the caller; 400 if
            the key is revoked or expired.
    """
    updated = auth_api_keys_crud.set_temp_scopes(
        api_key_id,
        token_user_id,
        data.scopes,
        data.duration_minutes,
        db,
    )
    return _serialize_api_key(updated)


@router.delete(
    "/{api_key_id}/temp_scopes",
    response_model=api_keys_schema.UsersApiKeyRead,
    status_code=status.HTTP_200_OK,
)
async def revoke_user_api_key_temp_scopes(
    api_key_id: str,
    token_user_id: Annotated[
        int,
        Depends(auth_internal_dependencies.get_sub_from_access_token),
    ],
    db: Annotated[Session, Depends(core_database.get_db)],
) -> api_keys_schema.UsersApiKeyRead:
    """
    Revoke temporary elevated scopes early on an active API key.

    JWT-only: API keys cannot manage temporary scopes.

    Args:
        api_key_id: UUID of the API key.
        token_user_id: User ID from access token.
        db: Database session dependency.

    Returns:
        Updated API key object with cleared temporary scopes.

    Raises:
        HTTPException: 404 if the key does not belong to the caller; 400 if
            the key is revoked or expired.
    """
    updated = auth_api_keys_crud.clear_temp_scopes(api_key_id, token_user_id, db)
    return _serialize_api_key(updated)


@router.patch(
    "/{api_key_id}/revoke",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_user_api_key(
    api_key_id: str,
    token_user_id: Annotated[
        int,
        Depends(auth_internal_dependencies.get_sub_from_access_token),
    ],
    db: Annotated[Session, Depends(core_database.get_db)],
) -> None:
    """
    Revoke an API key (soft-disable).

    The key record is retained for audit purposes but
    will be rejected on any subsequent use.

    Args:
        api_key_id: UUID of the API key to revoke.
        token_user_id: User ID from access token.
        db: Database session dependency.

    Returns:
        None.

    Raises:
        HTTPException: 404 if the key is not found or
            does not belong to the authenticated user.
    """
    auth_api_keys_crud.revoke_api_key(api_key_id, token_user_id, db)


@router.delete(
    "/{api_key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user_api_key(
    api_key_id: str,
    token_user_id: Annotated[
        int,
        Depends(auth_internal_dependencies.get_sub_from_access_token),
    ],
    db: Annotated[Session, Depends(core_database.get_db)],
) -> None:
    """
    Permanently delete an API key.

    Hard-delete. The key is gone and cannot be used
    or recovered after this operation.

    Args:
        api_key_id: UUID of the API key to delete.
        token_user_id: User ID from access token.
        db: Database session dependency.

    Returns:
        None.

    Raises:
        HTTPException: 404 if the key is not found or
            does not belong to the authenticated user.
    """
    auth_api_keys_crud.delete_api_key(api_key_id, token_user_id, db)
