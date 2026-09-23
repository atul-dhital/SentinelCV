from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from typing import Any


class JsonLogFormatter(logging.Formatter):
    """Minimal JSON formatter for production log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_sentinelcv_configured", False):
        return

    level_name = (os.getenv("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    log_format = (os.getenv("LOG_FORMAT") or "plain").strip().lower()

    handler = logging.StreamHandler()
    if log_format == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )

    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root._sentinelcv_configured = True  # type: ignore[attr-defined]


def init_sentry() -> None:
    dsn = (os.getenv("SENTRY_DSN") or "").strip()
    enabled = (os.getenv("SENTRY_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled or not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    except ImportError:
        logging.getLogger("sentinelcv.sentry").warning(
            "Sentry is enabled but sentry-sdk is not installed."
        )
        return

    traces_sample_rate_raw = (os.getenv("SENTRY_TRACES_SAMPLE_RATE") or "0.1").strip()
    try:
        traces_sample_rate = float(traces_sample_rate_raw)
    except ValueError:
        traces_sample_rate = 0.1

    def _scrub_pii(event: dict, hint: dict) -> dict:
        """Strip PII from Sentry events before they leave the process.

        Removes Authorization headers (contain bearer tokens), Cookie headers
        (contain refresh tokens), and query parameters that may contain tokens
        or UUIDs from path-based requests.  Keeps the stack trace and message
        intact so errors are still actionable.
        """
        request = event.get("request", {})
        headers = request.get("headers", {})
        if isinstance(headers, dict):
            for sensitive in ("Authorization", "authorization", "Cookie", "cookie", "X-Internal-API-Key"):
                headers.pop(sensitive, None)

        # Redact body — may contain passwords, tokens, or biometric payloads
        if "data" in request:
            request["data"] = "[filtered]"

        # Scrub query_string — may contain ?token=... cursors
        if "query_string" in request:
            request["query_string"] = "[filtered]"

        return event

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTINELCV_ENV", "development"),
        traces_sample_rate=max(0.0, min(traces_sample_rate, 1.0)),
        before_send=_scrub_pii,
        send_default_pii=False,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
    )
