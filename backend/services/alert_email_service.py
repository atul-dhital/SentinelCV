"""Alert notification email delivery service.

Checks alert rules against an incoming visitor-log event and sends
email notifications when conditions match and email_alerts_enabled=True.

Called from the internal log-ingestion route after a new VisitorLog is
persisted by the AI service.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("sentinelcv.alert_email")


def _build_alert_message(
    to_email: str,
    event_type: str,
    confidence: float,
    camera_name: str,
    visitor_name: Optional[str],
    log_id: str,
    frontend_url: str,
) -> EmailMessage:
    identified = visitor_name is not None
    subject = (
        f"[SentinelCV Alert] {'Known visitor: ' + visitor_name if identified else 'Unidentified visitor'} detected"
    )
    detail_url = f"{frontend_url.rstrip('/')}/logs/{log_id}"
    body = "\n".join([
        "SentinelCV Alert Notification",
        "=" * 40,
        f"Event type  : {event_type}",
        f"Camera      : {camera_name}",
        f"Visitor     : {visitor_name or 'Unknown'}",
        f"Confidence  : {confidence:.0%}",
        f"View log    : {detail_url}",
        "",
        "This alert was triggered by your organization's alert rules.",
        "Manage alerts at: " + f"{frontend_url.rstrip('/')}/alerts",
    ])

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = _smtp_from()
    msg["To"] = to_email
    msg.set_content(body)
    return msg


def _smtp_from() -> str:
    import os
    return (os.getenv("PASSWORD_RESET_FROM_EMAIL") or "noreply@sentinelcv.local").strip()


def _send_smtp(msg: EmailMessage) -> bool:
    import os
    host = (os.getenv("SMTP_HOST") or "").strip()
    port_raw = (os.getenv("SMTP_PORT") or "587").strip()
    user = (os.getenv("SMTP_USER") or "").strip()
    password = (os.getenv("SMTP_PASSWORD") or "").strip()
    use_ssl = (os.getenv("SMTP_USE_SSL") or "").strip().lower() in {"1", "true", "yes"}
    use_tls = (os.getenv("SMTP_USE_TLS") or "true").strip().lower() not in {"0", "false", "no"}

    if not host:
        logger.debug("Alert email skipped: SMTP_HOST not configured")
        return False

    try:
        port = int(port_raw)
    except ValueError:
        logger.warning("Alert email: invalid SMTP_PORT %r", port_raw)
        return False

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.ehlo()
                if use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                if user and password:
                    smtp.login(user, password)
                smtp.send_message(msg)
        return True
    except Exception as exc:
        logger.warning("Alert email delivery failed: %s", exc)
        return False


def maybe_send_alert_email(
    db: Session,
    organization_id,
    log_id: str,
    camera_name: str,
    visitor_name: Optional[str],
    confidence: float,
    identified: bool,
) -> None:
    """Fire alert email if org rules and config permit.

    Called non-blocking; all exceptions are caught so a delivery failure
    never breaks the log-ingestion flow.
    """
    import os
    from models import models

    try:
        config = (
            db.query(models.AlertConfig)
            .filter(models.AlertConfig.organization_id == organization_id)
            .first()
        )
        if not config or not config.alerts_enabled or not config.email_alerts_enabled:
            return

        # Find matching active rules
        rules = (
            db.query(models.AlertRule)
            .filter(
                models.AlertRule.alert_config_id == config.id,
                models.AlertRule.is_active.is_(True),
            )
            .order_by(models.AlertRule.order)
            .all()
        )

        matched = False
        for rule in rules:
            trigger = (rule.trigger_type or "").lower()
            min_conf = float(rule.min_confidence or 0)
            if confidence < min_conf:
                continue
            if trigger == "unidentified_visitor" and not identified:
                matched = True
                break
            if trigger == "identified_visitor" and identified:
                matched = True
                break
            if trigger == "any_detection":
                matched = True
                break

        if not matched:
            return

        # Collect recipient email addresses.
        # Use the org's dedicated notification_email_address when configured;
        # otherwise fall back to all active admin emails.
        org = (
            db.query(models.Organization)
            .filter(models.Organization.id == organization_id)
            .first()
        )
        dedicated = (getattr(org, "notification_email_address", None) or "").strip()
        if dedicated:
            recipients = [dedicated]
        else:
            admins = (
                db.query(models.User)
                .filter(
                    models.User.organization_id == organization_id,
                    models.User.role == "admin",
                    models.User.is_active.is_(True),
                )
                .limit(5)
                .all()
            )
            recipients = [u.email for u in admins if u.email]

        if not recipients:
            logger.debug(
                "Alert email skipped for org %s: no recipient addresses found",
                organization_id,
            )
            return

        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3001")
        event_type = "identified_detection" if identified else "unidentified_detection"

        for recipient in recipients:
            msg = _build_alert_message(
                to_email=recipient,
                event_type=event_type,
                confidence=confidence,
                camera_name=camera_name,
                visitor_name=visitor_name,
                log_id=log_id,
                frontend_url=frontend_url,
            )
            sent = _send_smtp(msg)
            if sent:
                logger.info(
                    "Alert email sent to %s for log %s (trigger=%s)",
                    recipient, log_id, event_type,
                )

    except Exception as exc:
        logger.warning("Alert email evaluation error for log %s: %s", log_id, exc)
