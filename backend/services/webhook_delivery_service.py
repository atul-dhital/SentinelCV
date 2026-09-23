from __future__ import annotations

"""Webhook delivery helpers for signed dispatch and delivery logging."""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
from typing import Any, Dict, Optional

import requests
from sqlalchemy.orm import Session

from models import models


WEBHOOK_SIGNATURE_HEADER = "X-SentinelCV-Signature"


@dataclass(slots=True)
class WebhookDeliveryResult:
    success: bool
    status_code: Optional[int]
    response_body: Optional[str]
    response_headers: Dict[str, Any]
    execution_time_ms: float
    error_message: Optional[str] = None


def normalize_events(events: Optional[list[str]]) -> list[str]:
    """Return a de-duplicated, trimmed event list."""

    normalized: list[str] = []
    for event in events or []:
        cleaned = str(event).strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def build_payload(
    webhook: models.Webhook,
    event: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a standard SentinelCV webhook payload."""

    return {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "webhook_id": str(webhook.id),
        "organization_id": str(webhook.organization_id),
        "data": data,
    }


def build_signature(secret: str, payload: Dict[str, Any]) -> str:
    """Create an HMAC SHA-256 signature for a webhook payload."""

    serialized_payload = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hmac.new(
        secret.encode("utf-8"),
        serialized_payload.encode("utf-8"),
        sha256,
    ).hexdigest()


def deliver_webhook(
    webhook: models.Webhook,
    payload: Dict[str, Any],
    *,
    timeout: float = 10.0,
) -> WebhookDeliveryResult:
    """Send a webhook delivery request and return the outcome."""

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if webhook.secret:
        headers[WEBHOOK_SIGNATURE_HEADER] = build_signature(webhook.secret, payload)

    started_at = datetime.now(timezone.utc)
    try:
        response = requests.post(
            webhook.url,
            json=payload,
            timeout=timeout,
            headers=headers,
        )
        elapsed_ms = (datetime.now(timezone.utc) - started_at).total_seconds() * 1000
        response_body = response.text[:4000] if response.text else None
        return WebhookDeliveryResult(
            success=200 <= response.status_code < 300,
            status_code=response.status_code,
            response_body=response_body,
            response_headers=dict(response.headers),
            execution_time_ms=elapsed_ms,
        )
    except requests.RequestException as exc:
        elapsed_ms = (datetime.now(timezone.utc) - started_at).total_seconds() * 1000
        return WebhookDeliveryResult(
            success=False,
            status_code=None,
            response_body=None,
            response_headers={},
            execution_time_ms=elapsed_ms,
            error_message=str(exc),
        )


def record_delivery_log(
    db: Session,
    webhook: models.Webhook,
    *,
    event: str,
    payload: Dict[str, Any],
    delivery: WebhookDeliveryResult,
) -> models.WebhookLog:
    """Persist a webhook delivery attempt."""

    log = models.WebhookLog(
        webhook_id=webhook.id,
        event=event,
        payload=payload,
        response_status=delivery.status_code or 0,
        response_body=delivery.response_body if delivery.success else delivery.error_message,
        success=delivery.success,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def dispatch_event_async(organization_id, event: str, data: Dict[str, Any]) -> None:
    """Fire-and-forget delivery of *event* to every active org webhook subscribed
    to it (G3). Lets live-recognition events such as ``watchlist.hit`` reach an
    external channel (Slack/webhook) instead of only landing in the database.
    Every attempt is recorded via ``record_delivery_log``."""
    import logging
    import threading
    from db.base import SessionLocal

    logger = logging.getLogger("sentinelcv.webhooks")

    def _run() -> None:
        db = SessionLocal()
        try:
            webhooks = db.query(models.Webhook).filter(
                models.Webhook.organization_id == organization_id,
                models.Webhook.is_active == True,
            ).all()
            for webhook in webhooks:
                subscribed = webhook.events or []
                if subscribed and event not in subscribed:
                    continue
                payload = build_payload(webhook, event, data)
                result = deliver_webhook(webhook, payload)
                record_delivery_log(db, webhook, event=event, payload=payload, delivery=result)
        except Exception as exc:
            logger.error("Webhook dispatch failed for %s: %s", event, exc)
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()
