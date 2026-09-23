"""Inbound/outbound email for missing-person intake (MP).

Two directions:

* **Inbound** — a mail provider (SendGrid Inbound Parse, Mailgun Routes,
  Postmark, or an IMAP poller) posts a received message to
  ``POST /api/v1/missing-persons/intake/email``. `parse_inbound_payload`
  normalises the several provider shapes into one dict so the API layer does
  not care which provider is in front of it.
* **Outbound** — acknowledgement to whoever wrote in, telling them the case
  reference their information was filed under and the reply-to address that
  keeps their next message on the same case.

The reply address is plus-addressed with the case's intake token
(``tips+<intake_token>@domain``) so a reply routes back to the right case
even when the sender strips the reference from the subject line.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import re
from email.utils import parseaddr
from typing import Any, Dict, List, Optional

from models import models
from services.email_service import email_service

logger = logging.getLogger(__name__)

# Mailbox that receives public tips. The local part is plus-addressed per case.
MP_INTAKE_ADDRESS = os.getenv("MP_INTAKE_ADDRESS", "missing-persons@sentinelcv.local")
MP_PUBLIC_BASE_URL = (os.getenv("MP_PUBLIC_BASE_URL", "") or "").rstrip("/")


def case_reply_address(case: models.MissingPersonCase) -> str:
    """Plus-addressed reply-to that routes a reply straight back to this case."""
    local, _, domain = MP_INTAKE_ADDRESS.partition("@")
    if not domain:
        return MP_INTAKE_ADDRESS
    return f"{local}+{case.intake_token}@{domain}"


def case_tip_url(case: models.MissingPersonCase) -> Optional[str]:
    """Public tip-submission link carrying the case's intake token."""
    if not MP_PUBLIC_BASE_URL:
        return None
    return f"{MP_PUBLIC_BASE_URL}/missing-persons/tip?token={case.intake_token}"


# ─── Inbound normalisation ──────────────────────────────────────────────────


def _first(payload: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _headers_lookup(payload: Dict[str, Any]) -> Dict[str, str]:
    """Flatten whatever header representation the provider used."""
    raw = payload.get("headers") or payload.get("Headers") or {}
    flat: Dict[str, str] = {}

    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, str):
                flat[str(key).lower()] = value
    elif isinstance(raw, list):
        # Postmark: [{"Name": "...", "Value": "..."}]
        for item in raw:
            if isinstance(item, dict):
                name = item.get("Name") or item.get("name")
                value = item.get("Value") or item.get("value")
                if isinstance(name, str) and isinstance(value, str):
                    flat[name.lower()] = value
    elif isinstance(raw, str):
        # SendGrid Inbound Parse sends the raw header block as one string.
        for line in raw.splitlines():
            if ":" in line:
                name, _, value = line.partition(":")
                flat.setdefault(name.strip().lower(), value.strip())

    return flat


def _decode_attachment_content(item: Dict[str, Any]) -> Optional[bytes]:
    content = item.get("content") or item.get("Content") or item.get("data")
    if content is None:
        return None
    if isinstance(content, (bytes, bytearray)):
        return bytes(content)
    if not isinstance(content, str):
        return None
    try:
        return base64.b64decode(content, validate=False)
    except (binascii.Error, ValueError):
        logger.warning("Skipping inbound attachment with undecodable content")
        return None


def parse_inbound_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a provider webhook body into a single intake shape.

    Returns keys: ``from_address``, ``from_name``, ``to_address``, ``subject``,
    ``body``, ``message_id``, ``in_reply_to``, ``references``, ``attachments``
    (list of ``{filename, content_type, content: bytes}``).
    """
    headers = _headers_lookup(payload)

    raw_from = _first(payload, "from", "From", "sender", "Sender") or headers.get("from", "")
    from_name, from_address = parseaddr(raw_from)

    raw_to = (
        _first(payload, "to", "To", "recipient", "Recipient", "envelope_to")
        or headers.get("to", "")
        or headers.get("delivered-to", "")
    )
    # A tip mail may be addressed to several mailboxes; keep them all so the
    # plus-address extractor can find ours among them.
    to_address = raw_to

    body = (
        _first(payload, "text", "TextBody", "body-plain", "plain", "stripped-text")
        or _first(payload, "html", "HtmlBody", "body-html")
        or ""
    )
    # Strip tags if only an HTML part was supplied — the router only needs text.
    if body and "<" in body and ">" in body and not payload.get("text"):
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"\s{2,}", " ", body).strip()

    attachments: List[Dict[str, Any]] = []
    raw_attachments = payload.get("attachments") or payload.get("Attachments") or []
    if isinstance(raw_attachments, list):
        for item in raw_attachments:
            if not isinstance(item, dict):
                continue
            content = _decode_attachment_content(item)
            if not content:
                continue
            attachments.append(
                {
                    "filename": item.get("filename")
                    or item.get("Name")
                    or item.get("name")
                    or "attachment",
                    "content_type": item.get("content_type")
                    or item.get("ContentType")
                    or item.get("type"),
                    "content": content,
                }
            )

    return {
        "from_address": from_address or raw_from,
        "from_name": from_name or None,
        "to_address": to_address,
        "subject": _first(payload, "subject", "Subject") or headers.get("subject"),
        "body": body,
        "message_id": _first(payload, "message_id", "MessageID", "Message-Id")
        or headers.get("message-id"),
        "in_reply_to": _first(payload, "in_reply_to", "InReplyTo")
        or headers.get("in-reply-to"),
        "references": _first(payload, "references", "References")
        or headers.get("references"),
        "attachments": attachments,
    }


# ─── Outbound acknowledgements ──────────────────────────────────────────────


def send_submission_acknowledgement(
    case: Optional[models.MissingPersonCase],
    submission: models.MissingPersonSubmission,
    *,
    attachment_count: int = 0,
) -> bool:
    """Tell the sender what happened to the information they sent in."""
    recipient = (submission.submitter_email or "").strip()
    if not recipient or submission.is_anonymous:
        return False

    if case is not None:
        reference = case.case_reference
        reply_to = case_reply_address(case)
        headline = f"Your information has been filed under case {reference}."
        follow_up = (
            f"Reply to this email or write to {reply_to} to add anything else — "
            "your reply is attached to the same case automatically."
        )
    else:
        reference = "pending review"
        headline = (
            "Your information has been received. We could not match it to a "
            "specific case automatically, so an investigator will review it."
        )
        follow_up = (
            "If you know the case reference (it looks like MP-2026-0001), "
            "include it in your next message and we can file it directly."
        )

    attachment_line = (
        f"We received {attachment_count} attached file(s)." if attachment_count else ""
    )

    subject = f"Received: missing person information ({reference})"
    text_body = "\n\n".join(
        part
        for part in [
            headline,
            attachment_line,
            follow_up,
            "Thank you for helping.",
        ]
        if part
    )
    html_body = email_service._base_template(  # noqa: SLF001 — shared house template
        "Information received",
        "".join(f"<p>{part}</p>" for part in text_body.split("\n\n")),
    )
    return email_service._send_email(recipient, subject, html_body, text_body)  # noqa: SLF001


def send_case_status_notification(
    case: models.MissingPersonCase, *, previous_status: str
) -> bool:
    """Tell the original reporter that the case status moved."""
    recipient = (case.reporter_email or "").strip()
    if not recipient:
        return False

    subject = f"Case {case.case_reference} status update: {case.status.replace('_', ' ')}"
    lines = [
        f"Case {case.case_reference} for {case.full_name} has moved from "
        f"'{previous_status.replace('_', ' ')}' to '{case.status.replace('_', ' ')}'.",
    ]
    if case.resolution_notes:
        lines.append(case.resolution_notes)
    text_body = "\n\n".join(lines)
    html_body = email_service._base_template(  # noqa: SLF001
        "Case status update",
        "".join(f"<p>{line}</p>" for line in lines),
    )
    return email_service._send_email(recipient, subject, html_body, text_body)  # noqa: SLF001
