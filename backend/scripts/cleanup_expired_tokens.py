from __future__ import annotations

from datetime import datetime, timezone

from db.base import SessionLocal
from models import models


def main() -> None:
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc)
        db.query(models.PasswordResetToken).filter(
            models.PasswordResetToken.expires_at < cutoff
        ).delete(synchronize_session=False)
        db.query(models.RefreshTokenSession).filter(
            models.RefreshTokenSession.expires_at < cutoff
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
