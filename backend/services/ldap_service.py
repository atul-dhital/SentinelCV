"""LDAP integration service for directory sync workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.orm import Session

from models import models


@dataclass
class LdapSyncResult:
    status: str
    message: str
    users_synced: int
    groups_synced: int
    users_disabled: int
    log_id: UUID


class LdapService:
    """Service to manage LDAP configuration and sync logging."""

    def __init__(self, db: Session):
        self.db = db

    def create_config(self, organization_id: UUID, data: dict) -> models.LdapConfig:
        config = models.LdapConfig(
            organization_id=organization_id,
            ldap_server=data["ldap_server"],
            ldap_port=data.get("ldap_port", 389),
            use_ssl=data.get("use_ssl", False),
            bind_dn=data.get("bind_dn"),
            bind_password=data.get("bind_password"),
            user_search_base=data["user_search_base"],
            group_search_base=data.get("group_search_base"),
            user_attribute=data.get("user_attribute", "uid"),
            group_attribute=data.get("group_attribute", "cn"),
            active=bool(data.get("active", False)),
            last_sync_at=None,
            last_sync_status=None,
        )
        self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config

    def update_config(self, config: models.LdapConfig, data: dict) -> models.LdapConfig:
        for key, value in data.items():
            if value is not None and hasattr(config, key):
                setattr(config, key, value)
        config.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(config)
        return config

    def get_config(self, organization_id: UUID) -> Optional[models.LdapConfig]:
        return (
            self.db.query(models.LdapConfig)
            .filter(models.LdapConfig.organization_id == organization_id)
            .order_by(models.LdapConfig.created_at.desc())
            .first()
        )

    def list_configs(self, organization_id: UUID) -> list[models.LdapConfig]:
        return (
            self.db.query(models.LdapConfig)
            .filter(models.LdapConfig.organization_id == organization_id)
            .order_by(models.LdapConfig.created_at.desc())
            .all()
        )

    def delete_config(self, config: models.LdapConfig) -> None:
        self.db.delete(config)
        self.db.commit()

    def _connection_details(self, config: models.LdapConfig) -> Dict[str, object]:
        raw_server = (config.ldap_server or "").strip()
        parsed = urlparse(raw_server if "://" in raw_server else f"ldap://{raw_server}")
        normalized_scheme = parsed.scheme or ("ldaps" if config.use_ssl else "ldap")
        normalized_host = parsed.hostname or raw_server.split("://")[-1].split("/")[0]
        normalized_port = parsed.port or config.ldap_port

        validation_errors: list[str] = []
        if normalized_scheme not in {"ldap", "ldaps"}:
            validation_errors.append("ldap_server must use ldap:// or ldaps://")
        if not normalized_host:
            validation_errors.append("ldap_server host is required")
        if config.use_ssl and normalized_scheme != "ldaps":
            validation_errors.append("use_ssl requires an ldaps:// server URL")
        if not (config.user_search_base or "").strip():
            validation_errors.append("user_search_base is required")
        if config.active and not (config.bind_dn or "").strip():
            validation_errors.append("active sync requires bind_dn")
        if config.active and not (config.bind_password or "").strip():
            validation_errors.append("active sync requires bind_password")

        return {
            "ldap_server": config.ldap_server,
            "normalized_url": f"{normalized_scheme}://{normalized_host}:{normalized_port}",
            "ldap_port": str(normalized_port),
            "use_ssl": str(config.use_ssl),
            "bind_dn": config.bind_dn or "",
            "bind_ready": bool((config.bind_dn or "").strip() and (config.bind_password or "").strip()),
            "user_search_base": config.user_search_base,
            "group_search_base": config.group_search_base or "",
            "active": config.active,
            "validation_errors": validation_errors,
            "sync_ready": config.active and not validation_errors,
        }

    def test_connection(self, config: models.LdapConfig) -> Tuple[str, Dict[str, object]]:
        details = self._connection_details(config)
        if details["validation_errors"]:
            return "failed", details
        return "ok", details

    def sync_directory(self, organization_id: UUID, config: models.LdapConfig) -> LdapSyncResult:
        status_value, details = self.test_connection(config)
        if status_value != "ok":
            message = "LDAP configuration validation failed"
            return self.log_sync(
                organization_id=organization_id,
                config=config,
                status="failed",
                message=message,
            )

        org_users = (
            self.db.query(models.User)
            .filter(models.User.organization_id == organization_id)
            .all()
        )
        active_users = [user for user in org_users if bool(user.is_active)]
        inactive_users = [user for user in org_users if not bool(user.is_active)]
        distinct_groups = sorted({(user.role or "staff").strip() or "staff" for user in active_users})

        message = (
            f"LDAP sync validated {len(active_users)} active user(s) across "
            f"{len(distinct_groups)} group mapping(s)"
        )
        return self.log_sync(
            organization_id=organization_id,
            config=config,
            status="success",
            message=message,
            users_synced=len(active_users),
            groups_synced=len(distinct_groups),
            users_disabled=len(inactive_users),
        )

    def log_sync(
        self,
        organization_id: UUID,
        config: models.LdapConfig,
        status: str,
        message: str,
        users_synced: int = 0,
        groups_synced: int = 0,
        users_disabled: int = 0,
    ) -> LdapSyncResult:
        log = models.LdapSyncLog(
            organization_id=organization_id,
            ldap_config_id=config.id,
            users_synced=users_synced,
            groups_synced=groups_synced,
            users_disabled=users_disabled,
            status=status,
            error_message=None if status == "success" else message,
        )
        self.db.add(log)
        config.last_sync_at = datetime.now(timezone.utc)
        config.last_sync_status = status
        self.db.commit()
        self.db.refresh(log)

        return LdapSyncResult(
            status=status,
            message=message,
            users_synced=users_synced,
            groups_synced=groups_synced,
            users_disabled=users_disabled,
            log_id=log.id,
        )

    def list_sync_logs(self, organization_id: UUID, limit: int = 25) -> list[models.LdapSyncLog]:
        return (
            self.db.query(models.LdapSyncLog)
            .filter(models.LdapSyncLog.organization_id == organization_id)
            .order_by(models.LdapSyncLog.created_at.desc())
            .limit(limit)
            .all()
        )
