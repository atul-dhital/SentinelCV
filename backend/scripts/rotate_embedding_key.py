"""Re-wrap stored face embeddings under a new embedding-encryption key.

Why this script exists
======================

When the audit-driven crypto split landed, the embedding-encryption key
became distinct from ``SECRET_KEY`` and gained a versioned ciphertext
envelope (``v1:<blob>``). Rotating ``EMBEDDING_KEY_SECRET`` therefore
requires re-encrypting every ``face_data.embedding`` row with the new key.

Operational flow
================

1. Generate the new key:
   ``python -c "import secrets; print(secrets.token_urlsafe(48))"``
2. Stage the new key as ``EMBEDDING_KEY_SECRET_NEW`` in the deployment
   environment alongside the existing ``EMBEDDING_KEY_SECRET``.
3. Run this script (idempotent, batched, dry-run-first):
   ``python -m backend.scripts.rotate_embedding_key --dry-run``
   ``python -m backend.scripts.rotate_embedding_key --execute``
4. Once every row reports ``embedding_key_version`` matching the new
   version label, swap ``EMBEDDING_KEY_SECRET`` to the new value and
   restart the backend. The previous key can be retired.

Scope
=====

* SQLite: stores Fernet ciphertext in a JSON-text column. This script
  re-wraps each row.
* PostgreSQL with pgvector: embeddings are plaintext ``vector`` values;
  this script logs a no-op and exits 0. Encryption at rest is provided
  by storage-level TDE (RDS ``storage_encrypted``, ``pg_tde``, etc.) —
  see ``doc/compliance/DPIA_TEMPLATE.md`` §5.

Safety
======

* ``--dry-run`` (default) decrypts and re-encrypts in memory but does
  NOT write anything back.
* ``--execute`` writes back per batch (``--batch-size``). Each batch
  commits independently so an interruption only loses the in-flight
  batch.
* The previous key must remain available as ``EMBEDDING_KEY_SECRET``
  during the migration so legacy and current ciphertext can both be
  decrypted. The new key is read from ``EMBEDDING_KEY_SECRET_NEW``.
"""

from __future__ import annotations

import argparse
import base64
import logging
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


sys.path.insert(0, str(_project_root()))

from db.base import IS_SQLITE, SessionLocal  # noqa: E402
from models import models  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("rotate_embedding_key")


_HKDF_INFO = b"sentinelcv-embedding-encryption-v1"
_HKDF_SALT = b"sentinelcv|embedding|v1"
_NEW_VERSION = "v1"  # bump when introducing v2 envelope
_NEW_PREFIX = f"{_NEW_VERSION}:"


def _derive_fernet(secret: str) -> Fernet:
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    ).derive(secret.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(derived))


def _legacy_fernet(secret: str) -> Fernet:
    import hashlib

    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest()))


def _resolve_keys() -> tuple[Fernet, Fernet, Fernet]:
    """Return (current_fernet, new_fernet, legacy_fernet)."""
    current = os.getenv("EMBEDDING_KEY_SECRET") or os.getenv("SECRET_KEY")
    new = os.getenv("EMBEDDING_KEY_SECRET_NEW")
    legacy = os.getenv("SECRET_KEY")
    if not current:
        raise SystemExit("EMBEDDING_KEY_SECRET (or SECRET_KEY fallback) must be set")
    if not new:
        raise SystemExit("EMBEDDING_KEY_SECRET_NEW must be set to the rotation target key")
    if not legacy:
        raise SystemExit("SECRET_KEY must be set so legacy ciphertext can still be read")
    return _derive_fernet(current), _derive_fernet(new), _legacy_fernet(legacy)


def _decrypt(value: str, current: Fernet, legacy: Fernet) -> str:
    if value.startswith(_NEW_PREFIX):
        return current.decrypt(value[len(_NEW_PREFIX):].encode("utf-8")).decode("utf-8")
    return legacy.decrypt(value.encode("utf-8")).decode("utf-8")


def _encrypt(plaintext: str, new: Fernet) -> str:
    return f"{_NEW_PREFIX}{new.encrypt(plaintext.encode('utf-8')).decode('utf-8')}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("Operational flow")[0].strip())
    parser.add_argument("--execute", action="store_true", help="Write changes back. Default is dry-run.")
    parser.add_argument("--batch-size", type=int, default=200, help="Rows per commit batch")
    parser.add_argument("--limit", type=int, default=0, help="Optional cap on total rows processed")
    args = parser.parse_args()

    if not IS_SQLITE:
        logger.info(
            "DATABASE backend is not SQLite — face_data.embedding is plaintext "
            "pgvector and is not encrypted at the application layer. Storage-level "
            "TDE handles at-rest encryption on PostgreSQL. Nothing to do."
        )
        return 0

    current, new, legacy = _resolve_keys()
    db = SessionLocal()
    db.info["skip_tenant_filter"] = True

    processed = 0
    rewrapped = 0
    failed = 0
    try:
        query = (
            db.query(models.FaceData)
            .filter(models.FaceData.embedding.isnot(None))
            .order_by(models.FaceData.created_at.asc())
        )
        if args.limit > 0:
            query = query.limit(args.limit)

        batch: list[models.FaceData] = []
        for face in query.yield_per(args.batch_size):
            processed += 1
            current_value = face.embedding
            if not isinstance(current_value, str) or not current_value:
                continue

            try:
                plaintext = _decrypt(current_value, current, legacy)
            except Exception as exc:
                failed += 1
                logger.warning("Decrypt failed for face_data.id=%s: %s", face.id, exc)
                continue

            new_ciphertext = _encrypt(plaintext, new)
            if args.execute:
                face.embedding = new_ciphertext
                face.embedding_key_version = _NEW_VERSION
                batch.append(face)

            rewrapped += 1
            if args.execute and len(batch) >= args.batch_size:
                db.commit()
                logger.info("Committed batch of %d rows (total rewrapped=%d)", len(batch), rewrapped)
                batch.clear()

        if args.execute and batch:
            db.commit()
            logger.info("Committed final batch of %d rows", len(batch))

    finally:
        db.close()

    mode = "EXECUTE" if args.execute else "DRY RUN"
    logger.info(
        "%s complete — processed=%d rewrapped=%d failed=%d",
        mode,
        processed,
        rewrapped,
        failed,
    )
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
