"""Periodic GDPR data-retention cleanup scheduler.

Runs ``GDPRService.cleanup_expired_data`` for every organization that has
pending or processing deletion requests.  Designed to be started once at
application startup and run as a background daemon thread.

Interval: configurable via ``GDPR_CLEANUP_INTERVAL_HOURS`` env var (default 24 h).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("sentinelcv.gdpr_cleanup")

_INTERVAL_SECONDS: int = int(os.getenv("GDPR_CLEANUP_INTERVAL_HOURS", "24")) * 3600
_FIRST_RUN_DELAY_SECONDS: int = int(os.getenv("GDPR_CLEANUP_FIRST_RUN_DELAY_SECONDS", "60"))


class GDPRCleanupScheduler:
    """Background daemon that periodically purges expired personal data."""

    def __init__(self, interval_seconds: int = _INTERVAL_SECONDS) -> None:
        self.interval_seconds = interval_seconds
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_run_at: Optional[datetime] = None
        self._last_run_stats: dict = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            logger.warning("GDPR cleanup scheduler already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="gdpr-cleanup-scheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "GDPR cleanup scheduler started (interval=%dh, first run in %ds)",
            self.interval_seconds // 3600,
            _FIRST_RUN_DELAY_SECONDS,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("GDPR cleanup scheduler stopped")

    def status(self) -> dict:
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "interval_seconds": self.interval_seconds,
            "last_run_at": self._last_run_at.isoformat() if self._last_run_at else None,
            "last_run_stats": self._last_run_stats,
        }

    def _loop(self) -> None:
        # Short initial delay so the app finishes starting before first cleanup.
        if self._stop_event.wait(timeout=_FIRST_RUN_DELAY_SECONDS):
            return

        while not self._stop_event.is_set():
            try:
                self._run_cleanup()
            except Exception as exc:
                logger.error("GDPR cleanup run failed: %s", exc, exc_info=True)
            self._stop_event.wait(timeout=self.interval_seconds)

    def _run_cleanup(self) -> None:
        from db.base import SessionLocal
        from models.models import Organization
        from services.gdpr_service import GDPRService

        gdpr_svc = GDPRService()
        db = SessionLocal()
        total_stats: dict = {}
        try:
            org_ids = [str(row.id) for row in db.query(Organization.id).all()]
            logger.info("GDPR cleanup: processing %d organization(s)", len(org_ids))
            for org_id in org_ids:
                try:
                    import asyncio
                    from uuid import UUID
                    stats = asyncio.run(
                        gdpr_svc.cleanup_expired_data(db, UUID(org_id))
                    )
                    for key, value in stats.items():
                        total_stats[key] = total_stats.get(key, 0) + value
                    # Blanket time-based retention purge (independent of deletion requests).
                    purge = gdpr_svc.purge_expired_logs(db, UUID(org_id))
                    for key in ("detection_logs_deleted", "visitor_log_media_removed", "files_removed"):
                        total_stats[key] = total_stats.get(key, 0) + purge.get(key, 0)
                except Exception as exc:
                    logger.error("GDPR cleanup failed for org %s: %s", org_id, exc)
        finally:
            db.close()

        self._last_run_at = datetime.now(timezone.utc)
        self._last_run_stats = total_stats
        if any(v > 0 for v in total_stats.values()):
            logger.info("GDPR cleanup completed: %s", total_stats)
        else:
            logger.debug("GDPR cleanup: no expired data found")


# Module-level singleton started by main.py
_scheduler: Optional[GDPRCleanupScheduler] = None


def start_gdpr_cleanup_scheduler() -> GDPRCleanupScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = GDPRCleanupScheduler()
    _scheduler.start()
    return _scheduler


def stop_gdpr_cleanup_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.stop()


def get_gdpr_cleanup_scheduler() -> Optional[GDPRCleanupScheduler]:
    return _scheduler
