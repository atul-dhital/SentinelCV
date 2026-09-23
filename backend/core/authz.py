"""Cross-cutting authorization helpers.

These helpers are intentionally small and dependency-light so they can be
called from any router without dragging extra imports. They patch two
holes the audit flagged in the Phase 3 routers:

* `assert_belongs_to_org` — verify a foreign-key UUID coming from a
  request body actually belongs to the caller's organization. Without
  this, a tenant can write child rows referencing another tenant's
  parent rows. The global SQLAlchemy tenant filter only covers SELECTs,
  not INSERTs that pin foreign keys from user input.
* `validate_user_path` — verify a filesystem path coming from a request
  body resolves inside the data directory. Without this, endpoints that
  call ``cv2.imread`` / ``cv2.VideoCapture`` / ``torch.load`` on
  user-supplied paths are arbitrary-file-read sinks.
"""

from __future__ import annotations

import os
from typing import Type, TypeVar

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.paths import DATA_DIR
from core.storage import storage

T = TypeVar("T")

_DATA_DIR_ABS = os.path.abspath(DATA_DIR)


def assert_belongs_to_org(
    db: Session,
    model_cls: Type[T],
    pk,
    organization_id,
) -> T:
    """Return the row identified by ``pk`` if it belongs to ``organization_id``.

    Raises 404 otherwise so we do not leak existence information across
    tenants.
    """
    if pk is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing identifier")

    obj = (
        db.query(model_cls)
        .filter(
            model_cls.id == pk,  # type: ignore[attr-defined]
            model_cls.organization_id == organization_id,  # type: ignore[attr-defined]
        )
        .execution_options(skip_tenant_filter=True)
        .first()
    )
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{model_cls.__name__} not found in this organization",
        )
    return obj


def validate_user_path(user_path: str | None, *, must_exist: bool = True) -> str:
    """Resolve ``user_path`` to an absolute path inside ``DATA_DIR``.

    The traversal check is non-negotiable. The existence check can be
    skipped per call (``must_exist=False``) or globally via
    ``SKIP_USER_PATH_EXISTS_CHECK=1`` (test fixtures only — never set this
    in production).
    """
    if not user_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Path is required")

    cleaned = user_path.replace("\\", "/").lstrip("/")
    if cleaned.startswith("..") or "/../" in cleaned or cleaned in {".", ""}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid path")

    candidate = os.path.abspath(os.path.join(_DATA_DIR_ABS, cleaned))
    if not (candidate == _DATA_DIR_ABS or candidate.startswith(_DATA_DIR_ABS + os.sep)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path resolves outside the permitted data directory",
        )

    skip_exists = (os.getenv("SKIP_USER_PATH_EXISTS_CHECK") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if must_exist and not skip_exists:
        try:
            candidate = str(storage.ensure_local_file(cleaned))
        except FileNotFoundError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    return candidate
