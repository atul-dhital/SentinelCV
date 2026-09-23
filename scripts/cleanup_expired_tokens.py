#!/usr/bin/env python3
"""
Remove expired password-reset tokens and refresh-token sessions from the DB.
Run nightly — e.g. cron: 0 3 * * * /app/scripts/cleanup_expired_tokens.py

Kubernetes CronJob example (add to ops/k8s/platform.yaml):
  apiVersion: batch/v1
  kind: CronJob
  metadata:
    name: sentinelcv-token-cleanup
    namespace: sentinelcv
  spec:
    schedule: "0 3 * * *"
    jobTemplate:
      spec:
        template:
          spec:
            containers:
              - name: cleanup
                image: ghcr.io/sentinelcv/backend:latest
                command: ["python", "scripts/cleanup_expired_tokens.py"]
                envFrom:
                  - configMapRef:
                      name: sentinelcv-platform-config
                env:
                  - name: DATABASE_URL
                    valueFrom:
                      secretKeyRef:
                        name: sentinelcv-secrets
                        key: DATABASE_URL
                  - name: SECRET_KEY
                    valueFrom:
                      secretKeyRef:
                        name: sentinelcv-secrets
                        key: SECRET_KEY
            restartPolicy: OnFailure
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv
load_dotenv()

from db.base import SessionLocal
from models import models

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def run() -> None:
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        deleted_prt = (
            db.query(models.PasswordResetToken)
            .filter(models.PasswordResetToken.expires_at < now)
            .delete(synchronize_session=False)
        )
        deleted_rts = (
            db.query(models.RefreshTokenSession)
            .filter(models.RefreshTokenSession.expires_at < now)
            .delete(synchronize_session=False)
        )
        db.commit()
        log.info(
            "Cleanup done — removed %d password-reset tokens, %d expired refresh sessions",
            deleted_prt,
            deleted_rts,
        )
    except Exception:
        db.rollback()
        log.exception("Cleanup failed — rolled back")
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    run()
