"""S19: Webhooks & API Key Management."""

from datetime import datetime, timezone
from typing import List
from uuid import UUID
import hashlib
import ipaddress
import os
import secrets
import socket
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.security import get_current_user
from db.base import get_db
from models import models
from schemas import schemas
from services import user_service, visitor_service, webhook_delivery_service

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# ─── Webhook URL SSRF protection ─────────────────────────────────────────────
#
# Webhooks are admin-configured outbound HTTP calls. Without URL validation an
# admin can point a webhook at an internal metadata endpoint (169.254.169.254),
# the Redis port, or any private-network service, making the backend a
# free SSRF proxy. We enforce HTTPS-only and block all RFC-1918 / loopback /
# link-local destinations.

_ALLOWED_WEBHOOK_SCHEMES = {"https"}


def _allow_private_webhook_targets() -> bool:
    """Allow private/loopback targets only in non-production when explicitly opted in."""
    is_production = (os.getenv("SENTINELCV_ENV") or "development").strip().lower() == "production"
    if is_production:
        return False
    raw = (os.getenv("ALLOW_PRIVATE_WEBHOOK_TARGETS") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _validate_webhook_url(url: str) -> str:
    """Validate that ``url`` is a public HTTPS endpoint.

    Blocks http://, file://, private IPs, loopback, link-local, and metadata
    service addresses (e.g. 169.254.169.254).
    """
    if not url or not url.strip():
        raise HTTPException(status_code=400, detail="Webhook URL is required")

    try:
        parsed = urlparse(url.strip())
    except Exception:
        raise HTTPException(status_code=400, detail="Webhook URL is malformed")

    if parsed.scheme.lower() not in _ALLOWED_WEBHOOK_SCHEMES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Webhook URL must use https:// (got '{parsed.scheme}://'). "
                "Plain http://, file://, and other schemes are not allowed."
            ),
        )

    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise HTTPException(status_code=400, detail="Webhook URL must include a hostname")

    if _allow_private_webhook_targets():
        return url

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not resolve webhook hostname '{host}': {exc}",
        )

    for info in infos:
        ip_str = info[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Webhook hostname resolved to invalid IP '{ip_str}'",
            )
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Webhook URL '{host}' resolves to a private/internal address "
                    f"({ip_str}). Only public HTTPS endpoints are allowed. "
                    "Set ALLOW_PRIVATE_WEBHOOK_TARGETS=1 in non-production to override."
                ),
            )
    return url


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _require_admin(user: models.User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


# ── Webhook CRUD ─────────────────────────────────────────────────────────────


@router.get("/", response_model=List[schemas.WebhookResponse])
async def list_webhooks(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all webhooks for the organization."""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    webhooks = db.query(models.Webhook).filter(
        models.Webhook.organization_id == user.organization_id
    ).order_by(models.Webhook.created_at.desc()).limit(10000).all()
    return webhooks


@router.post("/", response_model=schemas.WebhookResponse)
async def create_webhook(
    data: schemas.WebhookCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new webhook. Admin only."""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    _validate_webhook_url(data.url)

    webhook = models.Webhook(
        organization_id=user.organization_id,
        url=data.url,
        secret=data.secret,
        events=webhook_delivery_service.normalize_events(data.events),
        is_active=data.is_active,
    )
    db.add(webhook)
    db.commit()
    db.refresh(webhook)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "create", "webhook", str(webhook.id)
    )
    return webhook


@router.put("/{webhook_id}", response_model=schemas.WebhookResponse)
async def update_webhook(
    webhook_id: UUID,
    data: schemas.WebhookUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a webhook. Admin only."""
    user = _get_user(db, current_user_id)
    _require_admin(user)

    webhook = db.query(models.Webhook).filter(
        models.Webhook.id == webhook_id,
        models.Webhook.organization_id == user.organization_id,
    ).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    update_dict = data.model_dump(exclude_unset=True)
    if "url" in update_dict:
        _validate_webhook_url(update_dict["url"])
    if "events" in update_dict:
        update_dict["events"] = webhook_delivery_service.normalize_events(update_dict["events"])
    for key, value in update_dict.items():
        setattr(webhook, key, value)
    db.commit()
    db.refresh(webhook)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update", "webhook", str(webhook_id)
    )
    return webhook


@router.delete("/{webhook_id}")
async def delete_webhook(
    webhook_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a webhook. Admin only."""
    user = _get_user(db, current_user_id)
    _require_admin(user)

    webhook = db.query(models.Webhook).filter(
        models.Webhook.id == webhook_id,
        models.Webhook.organization_id == user.organization_id,
    ).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "delete", "webhook", str(webhook_id)
    )
    db.delete(webhook)
    db.commit()
    return {"message": "Webhook deleted"}


@router.post("/{webhook_id}/test")
async def test_webhook(
    webhook_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Send a test event to a webhook."""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    webhook = db.query(models.Webhook).filter(
        models.Webhook.id == webhook_id,
        models.Webhook.organization_id == user.organization_id,
    ).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    test_payload = webhook_delivery_service.build_payload(
        webhook,
        "test",
        {"message": "This is a test webhook event from SentinelCV"},
    )
    delivery = webhook_delivery_service.deliver_webhook(webhook, test_payload)
    webhook_delivery_service.record_delivery_log(
        db,
        webhook,
        event="test",
        payload=test_payload,
        delivery=delivery,
    )

    response_text = delivery.response_body or delivery.error_message or ""
    return {"success": delivery.success, "status_code": delivery.status_code, "response": response_text[:500]}


@router.get("/{webhook_id}/logs", response_model=List[schemas.WebhookLogResponse])
async def get_webhook_logs(
    webhook_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get delivery logs for a webhook."""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    webhook = db.query(models.Webhook).filter(
        models.Webhook.id == webhook_id,
        models.Webhook.organization_id == user.organization_id,
    ).first()
    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    logs = db.query(models.WebhookLog).filter(
        models.WebhookLog.webhook_id == webhook_id
    ).order_by(models.WebhookLog.created_at.desc()).limit(50).all()
    return logs


# ── API Key Management ───────────────────────────────────────────────────────


@router.get("/api-keys", response_model=List[schemas.ApiKeyResponse])
async def list_api_keys(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all API keys for the organization."""
    user = _get_user(db, current_user_id)
    _require_admin(user)
    keys = db.query(models.ApiKey).filter(
        models.ApiKey.organization_id == user.organization_id
    ).order_by(models.ApiKey.created_at.desc()).limit(10000).all()
    return keys


@router.post("/api-keys", response_model=schemas.ApiKeyCreatedResponse)
async def create_api_key(
    data: schemas.ApiKeyCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new API key. Admin only. The full key is only returned once."""
    user = _get_user(db, current_user_id)
    _require_admin(user)

    raw_key = f"scv_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:12]

    api_key = models.ApiKey(
        organization_id=user.organization_id,
        name=data.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        permissions=data.permissions,
        is_active=True,
        expires_at=data.expires_at,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "create", "api_key", str(api_key.id)
    )

    return schemas.ApiKeyCreatedResponse(
        id=api_key.id,
        organization_id=api_key.organization_id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        permissions=api_key.permissions or [],
        is_active=api_key.is_active,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
        full_key=raw_key,
    )


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke (deactivate) an API key. Admin only."""
    user = _get_user(db, current_user_id)
    _require_admin(user)

    key = db.query(models.ApiKey).filter(
        models.ApiKey.id == key_id,
        models.ApiKey.organization_id == user.organization_id,
    ).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    key.is_active = False
    db.commit()

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "revoke", "api_key", str(key_id)
    )
    return {"message": "API key revoked"}
