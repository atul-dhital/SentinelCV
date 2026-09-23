"""LDAP configuration API endpoints."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from core.security import get_current_user
from db.base import get_db
from models import models
from schemas import schemas
from services import user_service
from services.ldap_service import LdapService

router = APIRouter(prefix="/ldap", tags=["LDAP"])


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _serialize_config(config: models.LdapConfig) -> schemas.LdapConfigResponse:
    return schemas.LdapConfigResponse(
        id=config.id,
        organization_id=config.organization_id,
        ldap_server=config.ldap_server,
        ldap_port=config.ldap_port,
        use_ssl=config.use_ssl,
        bind_dn=config.bind_dn,
        user_search_base=config.user_search_base,
        group_search_base=config.group_search_base,
        user_attribute=config.user_attribute,
        group_attribute=config.group_attribute,
        active=config.active,
        has_bind_password=bool(config.bind_password),
        last_sync_at=config.last_sync_at,
        last_sync_status=config.last_sync_status,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.get("/config", response_model=Optional[schemas.LdapConfigResponse])
async def get_ldap_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Optional[schemas.LdapConfigResponse]:
    user = _get_user(db, current_user_id)
    service = LdapService(db)
    config = service.get_config(user.organization_id)
    return _serialize_config(config) if config else None


@router.get("/configs", response_model=list[schemas.LdapConfigResponse])
async def list_ldap_configs(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[schemas.LdapConfigResponse]:
    user = _get_user(db, current_user_id)
    service = LdapService(db)
    configs = service.list_configs(user.organization_id)
    return [_serialize_config(config) for config in configs]


@router.post("/config", response_model=schemas.LdapConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_ldap_config(
    payload: schemas.LdapConfigCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.LdapConfigResponse:
    user = _get_user(db, current_user_id)
    service = LdapService(db)
    config = service.create_config(user.organization_id, payload.model_dump())
    return _serialize_config(config)


@router.put("/config/{config_id}", response_model=schemas.LdapConfigResponse)
async def update_ldap_config(
    config_id: UUID,
    payload: schemas.LdapConfigUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.LdapConfigResponse:
    user = _get_user(db, current_user_id)
    service = LdapService(db)
    config = db.query(models.LdapConfig).filter(
        models.LdapConfig.id == config_id,
        models.LdapConfig.organization_id == user.organization_id,
    ).first()
    if not config:
        raise HTTPException(status_code=404, detail="LDAP config not found")
    updated = service.update_config(config, payload.model_dump(exclude_unset=True))
    return _serialize_config(updated)


@router.delete("/config/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ldap_config(
    config_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    user = _get_user(db, current_user_id)
    config = db.query(models.LdapConfig).filter(
        models.LdapConfig.id == config_id,
        models.LdapConfig.organization_id == user.organization_id,
    ).first()
    if not config:
        raise HTTPException(status_code=404, detail="LDAP config not found")
    LdapService(db).delete_config(config)
    return None


@router.post("/config/{config_id}/test", response_model=schemas.LdapConnectionTestResponse)
async def test_ldap_config(
    config_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.LdapConnectionTestResponse:
    user = _get_user(db, current_user_id)
    config = db.query(models.LdapConfig).filter(
        models.LdapConfig.id == config_id,
        models.LdapConfig.organization_id == user.organization_id,
    ).first()
    if not config:
        raise HTTPException(status_code=404, detail="LDAP config not found")
    status_value, details = LdapService(db).test_connection(config)
    if status_value == "ok":
        message = "LDAP configuration verified"
    else:
        validation_errors = details.get("validation_errors") or []
        error_suffix = f": {', '.join(str(item) for item in validation_errors)}" if validation_errors else ""
        message = f"LDAP configuration failed validation{error_suffix}"
    return schemas.LdapConnectionTestResponse(status=status_value, message=message, details=details)


@router.post("/config/{config_id}/sync", response_model=schemas.LdapSyncResponse)
async def sync_ldap_users(
    config_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.LdapSyncResponse:
    user = _get_user(db, current_user_id)
    config = db.query(models.LdapConfig).filter(
        models.LdapConfig.id == config_id,
        models.LdapConfig.organization_id == user.organization_id,
    ).first()
    if not config:
        raise HTTPException(status_code=404, detail="LDAP config not found")

    service = LdapService(db)
    result = service.sync_directory(
        organization_id=user.organization_id,
        config=config,
    )
    return schemas.LdapSyncResponse(
        status=result.status,
        message=result.message,
        users_synced=result.users_synced,
        groups_synced=result.groups_synced,
        users_disabled=result.users_disabled,
        log_id=result.log_id,
    )


@router.get("/sync-logs", response_model=schemas.LdapSyncLogListResponse)
async def list_sync_logs(
    limit: int = Query(25, ge=1, le=200),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> schemas.LdapSyncLogListResponse:
    user = _get_user(db, current_user_id)
    service = LdapService(db)
    logs = service.list_sync_logs(user.organization_id, limit=limit)
    return schemas.LdapSyncLogListResponse(
        total=len(logs),
        items=[
            schemas.LdapSyncLogResponse.model_validate(log)
            for log in logs
        ],
    )
