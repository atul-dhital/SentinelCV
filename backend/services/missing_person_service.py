"""Missing-person case service (MP).

Owns three things the API layer should not re-implement:

1. **Case lifecycle** — reference allocation, status transitions, and the
   append-only case timeline.
2. **Evidence intake** — storing uploaded/emailed files as attachments with
   content de-duplication, and enrolling reference photos into the biometric
   `Visitor` record so live recognition can raise a sighting.
3. **Routing** — deciding which case an inbound submission belongs to. This is
   the part that makes "email a tip" and "upload a photo" usable: a submission
   is matched by case reference, per-case intake token, email thread, name, or
   face, and anything that cannot be matched confidently is left unrouted for
   human triage rather than guessed at.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.storage import storage
from models import models
from services import visitor_service

logger = logging.getLogger(__name__)

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001")

# ─── Vocabularies ───────────────────────────────────────────────────────────

CASE_STATUSES = {
    "pending_verification",
    "open",
    "possible_match",
    "located",
    "hospitalized",
    "found_safe",
    "found_deceased",
    "closed",
    "withdrawn",
}
# Statuses that mean the case no longer needs public appeals.
RESOLVED_STATUSES = {"found_safe", "found_deceased", "closed", "withdrawn"}
CASE_PRIORITIES = {"low", "medium", "high", "critical"}

SUBMISSION_SOURCES = {"web_form", "public_form", "email", "api", "internal"}
SUBMISSION_TYPES = {
    "sighting",
    "evidence",
    "safe_report",
    "information",
    "duplicate_report",
}
SUBMISSION_STATUSES = {"new", "triage", "reviewing", "verified", "rejected", "duplicate"}

ATTACHMENT_KINDS = {
    "photo",
    "reference_photo",
    "cctv_footage",
    "video",
    "document",
    "audio",
    "other",
}

UPDATE_TYPES = {
    "case_created",
    "status_change",
    "safe_report",
    "sighting",
    "note",
    "evidence_added",
    "assignment",
}

# Extension → attachment kind. Anything unrecognised is stored as "other" so
# an unusual but legitimate evidence file is never silently dropped.
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".mpg", ".mpeg"}
_DOC_EXTS = {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".csv", ".xlsx"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".aac"}

# Maximum bytes accepted for one evidence file. CCTV clips are large, so this
# is deliberately higher than the face-enrolment limit.
MAX_ATTACHMENT_BYTES = int(os.getenv("MP_MAX_ATTACHMENT_BYTES", str(256 * 1024 * 1024)))

# Confidence floor for accepting an automatic (non-explicit) case link. Below
# this the submission goes to the triage queue with its candidates recorded.
AUTO_LINK_THRESHOLD = float(os.getenv("MP_AUTO_LINK_THRESHOLD", "0.72"))
# Cosine-similarity floor for treating a face match as a case link.
FACE_LINK_THRESHOLD = float(os.getenv("MP_FACE_LINK_THRESHOLD", "0.62"))

CASE_REFERENCE_PATTERN = re.compile(r"\bMP-(\d{4})-(\d{3,6})\b", re.IGNORECASE)
# Plus-addressed intake mailbox: tips+<intake_token>@example.org
INTAKE_ADDRESS_PATTERN = re.compile(r"\+([A-Za-z0-9_\-]{8,64})@")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─── Routing result ─────────────────────────────────────────────────────────


@dataclass
class CaseMatch:
    """Outcome of routing one submission to a case."""

    case: Optional[models.MissingPersonCase] = None
    method: str = "unmatched"
    confidence: float = 0.0
    # Every case the router considered, so a reviewer can see the reasoning
    # and override it from the triage queue.
    candidates: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return self.case is not None


# ─── Case reference / token allocation ──────────────────────────────────────


def generate_intake_token() -> str:
    """Opaque, unguessable per-case token used for email + public tip links."""
    return secrets.token_urlsafe(24)[:48]


def generate_case_reference(db: Session, organization_id: UUID) -> str:
    """Allocate the next ``MP-<year>-<seq>`` reference for an organization.

    Sequence restarts each calendar year. The unique index on
    (organization_id, case_reference) is the real guard — on collision the
    caller retries, which is why `create_case` loops.
    """
    year = utcnow().year
    prefix = f"MP-{year}-"
    latest = (
        db.query(models.MissingPersonCase.case_reference)
        .filter(
            models.MissingPersonCase.organization_id == organization_id,
            models.MissingPersonCase.case_reference.like(f"{prefix}%"),
        )
        .order_by(models.MissingPersonCase.case_reference.desc())
        .limit(1)
        .first()
    )
    next_seq = 1
    if latest and latest[0]:
        try:
            next_seq = int(str(latest[0]).rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            next_seq = 1
    return f"{prefix}{next_seq:04d}"


# ─── Case CRUD ──────────────────────────────────────────────────────────────


def create_case(
    db: Session,
    organization_id: UUID,
    *,
    full_name: str,
    created_by: Optional[UUID] = None,
    **fields: Any,
) -> models.MissingPersonCase:
    """Create a case, allocate its reference/intake token, and seed the timeline."""
    allowed = {c.name for c in models.MissingPersonCase.__table__.columns}
    payload = {k: v for k, v in fields.items() if k in allowed and v is not None}
    payload.pop("case_reference", None)
    payload.pop("intake_token", None)
    payload.pop("organization_id", None)

    status = payload.get("status", "open")
    if status not in CASE_STATUSES:
        raise ValueError(f"status must be one of {sorted(CASE_STATUSES)}")
    priority = payload.get("priority", "medium")
    if priority not in CASE_PRIORITIES:
        raise ValueError(f"priority must be one of {sorted(CASE_PRIORITIES)}")

    last_error: Optional[Exception] = None
    for _ in range(5):
        case = models.MissingPersonCase(
            organization_id=organization_id,
            case_reference=generate_case_reference(db, organization_id),
            intake_token=generate_intake_token(),
            full_name=full_name.strip(),
            created_by=created_by,
            **payload,
        )
        db.add(case)
        try:
            db.commit()
        except Exception as exc:  # pragma: no cover - concurrent reference clash
            db.rollback()
            last_error = exc
            continue
        db.refresh(case)
        record_case_update(
            db,
            case,
            update_type="case_created",
            new_status=case.status,
            notes=f"Case opened for {case.full_name}",
            created_by=created_by,
        )
        return case

    raise RuntimeError(f"Could not allocate a unique case reference: {last_error}")


def get_case(
    db: Session, organization_id: UUID, case_id: UUID
) -> Optional[models.MissingPersonCase]:
    return (
        db.query(models.MissingPersonCase)
        .filter(
            models.MissingPersonCase.id == case_id,
            models.MissingPersonCase.organization_id == organization_id,
        )
        .first()
    )


def get_case_by_reference(
    db: Session, organization_id: UUID, case_reference: str
) -> Optional[models.MissingPersonCase]:
    return (
        db.query(models.MissingPersonCase)
        .filter(
            models.MissingPersonCase.organization_id == organization_id,
            func.upper(models.MissingPersonCase.case_reference) == case_reference.strip().upper(),
        )
        .first()
    )


def get_case_by_intake_token(
    db: Session, intake_token: str
) -> Optional[models.MissingPersonCase]:
    """Look a case up by its intake token.

    Deliberately *not* organization-scoped: the token is the credential, and
    inbound email has no session to derive a tenant from. The token is 24
    bytes of entropy and unique across the table.
    """
    if not intake_token:
        return None
    return (
        db.query(models.MissingPersonCase)
        .filter(models.MissingPersonCase.intake_token == intake_token.strip())
        .execution_options(skip_tenant_filter=True)
        .first()
    )


def list_cases(
    db: Session,
    organization_id: UUID,
    *,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    query: Optional[str] = None,
    public_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> Tuple[List[models.MissingPersonCase], int]:
    q = db.query(models.MissingPersonCase).filter(
        models.MissingPersonCase.organization_id == organization_id
    )
    if status:
        q = q.filter(models.MissingPersonCase.status == status)
    if priority:
        q = q.filter(models.MissingPersonCase.priority == priority)
    if public_only:
        q = q.filter(models.MissingPersonCase.is_public.is_(True))
    if query:
        like = f"%{query.strip()}%"
        q = q.filter(
            models.MissingPersonCase.full_name.ilike(like)
            | models.MissingPersonCase.nickname.ilike(like)
            | models.MissingPersonCase.case_reference.ilike(like)
            | models.MissingPersonCase.last_seen_location.ilike(like)
        )
    total = q.count()
    rows = (
        q.order_by(models.MissingPersonCase.created_at.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), 500))
        .all()
    )
    return rows, total


def update_case_status(
    db: Session,
    case: models.MissingPersonCase,
    new_status: str,
    *,
    user_id: Optional[UUID] = None,
    notes: Optional[str] = None,
) -> models.MissingPersonCase:
    if new_status not in CASE_STATUSES:
        raise ValueError(f"status must be one of {sorted(CASE_STATUSES)}")

    previous = case.status
    case.status = new_status
    if new_status in RESOLVED_STATUSES:
        case.resolved_at = utcnow()
        case.resolved_by = user_id
        if notes:
            case.resolution_notes = notes
        # A resolved case stops being publicly appealed for.
        case.is_public = False
    else:
        case.resolved_at = None
        case.resolved_by = None
    db.commit()
    db.refresh(case)

    record_case_update(
        db,
        case,
        update_type="status_change",
        previous_status=previous,
        new_status=new_status,
        notes=notes,
        created_by=user_id,
        is_verified=True,
        verified_by=user_id,
    )
    return case


# ─── Case timeline ──────────────────────────────────────────────────────────


def record_case_update(
    db: Session,
    case: models.MissingPersonCase,
    *,
    update_type: str = "note",
    previous_status: Optional[str] = None,
    new_status: Optional[str] = None,
    notes: Optional[str] = None,
    submission_id: Optional[UUID] = None,
    reported_by_name: Optional[str] = None,
    reported_by_contact: Optional[str] = None,
    reported_by_relationship: Optional[str] = None,
    is_verified: bool = False,
    verified_by: Optional[UUID] = None,
    created_by: Optional[UUID] = None,
) -> models.MissingPersonCaseUpdate:
    if update_type not in UPDATE_TYPES:
        raise ValueError(f"update_type must be one of {sorted(UPDATE_TYPES)}")

    entry = models.MissingPersonCaseUpdate(
        organization_id=case.organization_id,
        case_id=case.id,
        submission_id=submission_id,
        update_type=update_type,
        previous_status=previous_status,
        new_status=new_status,
        notes=notes,
        reported_by_name=reported_by_name,
        reported_by_contact=reported_by_contact,
        reported_by_relationship=reported_by_relationship,
        is_verified=is_verified,
        verified_by=verified_by,
        verified_at=utcnow() if is_verified else None,
        created_by=created_by,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_case_timeline(
    db: Session, case: models.MissingPersonCase, limit: int = 500
) -> List[models.MissingPersonCaseUpdate]:
    return (
        db.query(models.MissingPersonCaseUpdate)
        .filter(models.MissingPersonCaseUpdate.case_id == case.id)
        .order_by(models.MissingPersonCaseUpdate.created_at.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    )


# ─── Attachments ────────────────────────────────────────────────────────────


def classify_attachment(filename: Optional[str], content_type: Optional[str]) -> str:
    """Best-effort evidence kind from filename extension / MIME type."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in _IMAGE_EXTS:
        return "photo"
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _DOC_EXTS:
        return "document"
    if ext in _AUDIO_EXTS:
        return "audio"

    ctype = (content_type or "").lower()
    if ctype.startswith("image/"):
        return "photo"
    if ctype.startswith("video/"):
        return "video"
    if ctype.startswith("audio/"):
        return "audio"
    if ctype.startswith(("application/pdf", "text/", "application/msword", "application/vnd")):
        return "document"
    return "other"


def find_duplicate_attachment(
    db: Session, organization_id: UUID, checksum: str
) -> Optional[models.MissingPersonAttachment]:
    if not checksum:
        return None
    return (
        db.query(models.MissingPersonAttachment)
        .filter(
            models.MissingPersonAttachment.organization_id == organization_id,
            models.MissingPersonAttachment.checksum_sha256 == checksum,
        )
        .first()
    )


def store_attachment(
    db: Session,
    organization_id: UUID,
    content: bytes,
    *,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
    file_kind: Optional[str] = None,
    case: Optional[models.MissingPersonCase] = None,
    submission: Optional[models.MissingPersonSubmission] = None,
    captured_at: Optional[datetime] = None,
    capture_location: Optional[str] = None,
    camera_id: Optional[UUID] = None,
    uploaded_by: Optional[UUID] = None,
) -> models.MissingPersonAttachment:
    """Persist one evidence file and attach it to a case and/or submission.

    The same bytes submitted twice reuse the stored object rather than writing
    a second copy — a single photo shared by twenty people is one file on disk
    with twenty attachment rows pointing at it.
    """
    if not content:
        raise ValueError("Empty file")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise ValueError(
            f"File exceeds the {MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB evidence limit"
        )

    kind = file_kind or classify_attachment(filename, content_type)
    if kind not in ATTACHMENT_KINDS:
        raise ValueError(f"file_kind must be one of {sorted(ATTACHMENT_KINDS)}")

    checksum = hashlib.sha256(content).hexdigest()
    existing = find_duplicate_attachment(db, organization_id, checksum)
    if existing is not None:
        relative_path = existing.file_url
    else:
        ext = os.path.splitext(filename or "")[1].lower() or ""
        relative_path = f"missing_persons/{organization_id}/{checksum[:2]}/{checksum}{ext}"
        storage.save_file(
            relative_path,
            content,
            content_type=content_type or "application/octet-stream",
        )

    attachment = models.MissingPersonAttachment(
        organization_id=organization_id,
        case_id=case.id if case else None,
        submission_id=submission.id if submission else None,
        file_kind=kind,
        file_url=relative_path,
        original_filename=(filename or "")[:512] or None,
        content_type=(content_type or "")[:128] or None,
        size_bytes=len(content),
        checksum_sha256=checksum,
        captured_at=captured_at,
        capture_location=capture_location,
        camera_id=camera_id,
        uploaded_by=uploaded_by,
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


def list_case_attachments(
    db: Session,
    case: models.MissingPersonCase,
    *,
    file_kind: Optional[str] = None,
    limit: int = 500,
) -> List[models.MissingPersonAttachment]:
    q = db.query(models.MissingPersonAttachment).filter(
        models.MissingPersonAttachment.case_id == case.id
    )
    if file_kind:
        q = q.filter(models.MissingPersonAttachment.file_kind == file_kind)
    return (
        q.order_by(models.MissingPersonAttachment.created_at.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    )


# ─── Biometric linking (reference photos → Visitor → live sightings) ────────


def embed_image(image_path: str) -> Tuple[Optional[List[float]], float, Optional[str], Optional[str]]:
    """Call the AI service for a face embedding.

    Returns ``(embedding, quality_score, face_angle, error)``. Never raises —
    evidence intake must not fail because the AI service is down; the file is
    still stored and can be re-processed later.
    """
    try:
        response = requests.post(
            f"{AI_SERVICE_URL}/embed-face",
            json={"image_path": image_path},
            timeout=60,
        )
    except requests.RequestException as exc:
        logger.warning("AI service unreachable for missing-person embedding: %s", exc)
        return None, 0.0, None, "AI service unavailable"

    if response.status_code != 200:
        return None, 0.0, None, f"AI service returned status {response.status_code}"

    result = response.json()
    if result.get("error"):
        return None, 0.0, None, str(result["error"])
    embedding = result.get("embedding")
    if not embedding:
        return None, 0.0, None, "No face found in image"
    return (
        embedding,
        float(result.get("quality_score", 0.0)),
        result.get("face_angle"),
        None,
    )


def ensure_case_visitor(
    db: Session, case: models.MissingPersonCase
) -> models.Visitor:
    """Get (or lazily create) the Visitor record that holds the case's faces.

    The Visitor is what the live recognition path in `api/camera.py` searches,
    so enrolling a reference photo here is what turns a paper report into
    something the cameras can actually match against.
    """
    if case.visitor_id:
        visitor = visitor_service.get_visitor(db, case.visitor_id)
        if visitor is not None:
            return visitor

    visitor = models.Visitor(
        organization_id=case.organization_id,
        name=case.full_name,
        description=f"Missing person case {case.case_reference}",
        is_known=True,
        visitor_metadata={
            "missing_person_case_id": str(case.id),
            "missing_person_case_reference": case.case_reference,
        },
    )
    db.add(visitor)
    db.commit()
    db.refresh(visitor)

    case.visitor_id = visitor.id
    db.commit()
    db.refresh(case)
    return visitor


def index_reference_photo(
    db: Session, case: models.MissingPersonCase, attachment: models.MissingPersonAttachment
) -> Tuple[bool, Optional[str]]:
    """Enrol a stored reference photo as face data on the case's Visitor.

    Returns ``(indexed, error)``. A failure is recorded on the attachment and
    reported back — it never rolls the upload itself back.
    """
    if attachment.file_kind not in {"photo", "reference_photo"}:
        return False, "Only photo attachments can be face-indexed"

    try:
        local_path = str(storage.ensure_local_file(attachment.file_url))
    except Exception as exc:  # pragma: no cover - storage fetch failure
        return False, f"Could not read stored file: {exc}"

    embedding, quality, angle, error = embed_image(local_path)
    if error or not embedding:
        attachment.processing_notes = error or "No embedding produced"
        db.commit()
        return False, error or "No embedding produced"

    visitor = ensure_case_visitor(db, case)
    is_primary = visitor_service.get_face_data_count(db, visitor.id) == 0
    face_data = visitor_service.create_face_data(
        db,
        visitor.id,
        embedding,
        image_url=attachment.file_url,
        quality_score=quality,
        face_angle=angle,
        is_primary=is_primary,
    )

    attachment.face_indexed = True
    attachment.face_data_id = face_data.id
    attachment.file_kind = "reference_photo"
    attachment.processing_notes = None
    db.commit()
    db.refresh(attachment)
    return True, None


def get_case_sightings(
    db: Session, case: models.MissingPersonCase, limit: int = 200
) -> List[models.VisitorLog]:
    """Camera detections of the case's linked Visitor — automated sightings."""
    if not case.visitor_id:
        return []
    return (
        db.query(models.VisitorLog)
        .filter(models.VisitorLog.visitor_id == case.visitor_id)
        .order_by(models.VisitorLog.timestamp.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    )


# ─── Routing: which case does this submission belong to? ────────────────────


def _normalize_name(value: Optional[str]) -> str:
    return re.sub(r"[^a-z ]+", " ", (value or "").lower()).strip()


def _name_similarity(a: Optional[str], b: Optional[str]) -> float:
    left, right = _normalize_name(a), _normalize_name(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    # Token overlap catches "Sita Devi Sharma" vs "Sita Sharma", which plain
    # sequence ratio scores poorly.
    left_tokens, right_tokens = set(left.split()), set(right.split())
    overlap = len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)
    ratio = SequenceMatcher(None, left, right).ratio()
    return max(ratio, overlap)


def extract_case_reference(*texts: Optional[str]) -> Optional[str]:
    """Pull an ``MP-YYYY-NNNN`` reference out of a subject line or body."""
    for text in texts:
        if not text:
            continue
        match = CASE_REFERENCE_PATTERN.search(text)
        if match:
            return match.group(0).upper()
    return None


def extract_intake_token(*addresses: Optional[str]) -> Optional[str]:
    """Pull the intake token out of a plus-addressed recipient address."""
    for address in addresses:
        if not address:
            continue
        match = INTAKE_ADDRESS_PATTERN.search(address)
        if match:
            return match.group(1)
    return None


def find_case_by_email_thread(
    db: Session, organization_id: UUID, *, in_reply_to: Optional[str], references: Optional[str]
) -> Optional[models.MissingPersonCase]:
    """Follow an email reply chain back to the case its parent landed on."""
    candidate_ids: List[str] = []
    for value in (in_reply_to, references):
        if value:
            candidate_ids.extend(re.findall(r"<[^<>]+>", value) or [value.strip()])
    if not candidate_ids:
        return None

    prior = (
        db.query(models.MissingPersonSubmission)
        .filter(
            models.MissingPersonSubmission.organization_id == organization_id,
            models.MissingPersonSubmission.email_message_id.in_(candidate_ids[:20]),
            models.MissingPersonSubmission.case_id.isnot(None),
        )
        .order_by(models.MissingPersonSubmission.created_at.desc())
        .first()
    )
    if prior is None:
        return None
    return get_case(db, organization_id, prior.case_id)


def find_cases_by_name(
    db: Session, organization_id: UUID, name: Optional[str], *, limit: int = 5
) -> List[Tuple[models.MissingPersonCase, float]]:
    """Rank open cases by name similarity to the supplied name."""
    if not _normalize_name(name):
        return []
    open_cases = (
        db.query(models.MissingPersonCase)
        .filter(
            models.MissingPersonCase.organization_id == organization_id,
            models.MissingPersonCase.status == "open",
        )
        .limit(1000)
        .all()
    )
    scored = []
    for case in open_cases:
        score = max(
            _name_similarity(name, case.full_name),
            _name_similarity(name, case.nickname),
        )
        if score > 0:
            scored.append((case, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]


def find_case_by_face(
    db: Session, organization_id: UUID, image_paths: Sequence[str]
) -> Tuple[Optional[models.MissingPersonCase], float]:
    """Match an uploaded photo against the reference faces on open cases.

    This is what connects a stranger's phone snapshot to the right case with
    no reference number: the photo is embedded, searched against enrolled
    faces, and if the winning Visitor belongs to a case, that case wins.
    """
    best_case: Optional[models.MissingPersonCase] = None
    best_score = 0.0

    for image_path in image_paths:
        embedding, _quality, _angle, error = embed_image(image_path)
        if error or not embedding:
            continue
        match = visitor_service.search_visitor_by_embedding(
            db, organization_id, embedding, threshold=FACE_LINK_THRESHOLD
        )
        if not match:
            continue
        visitor, confidence, _face_id, _meta = match
        case = (
            db.query(models.MissingPersonCase)
            .filter(
                models.MissingPersonCase.organization_id == organization_id,
                models.MissingPersonCase.visitor_id == visitor.id,
            )
            .first()
        )
        if case is not None and confidence > best_score:
            best_case, best_score = case, float(confidence)

    return best_case, best_score


def route_submission(
    db: Session,
    organization_id: UUID,
    *,
    case_id: Optional[UUID] = None,
    case_reference: Optional[str] = None,
    intake_token: Optional[str] = None,
    subject: Optional[str] = None,
    message: Optional[str] = None,
    email_to: Optional[str] = None,
    email_in_reply_to: Optional[str] = None,
    email_references: Optional[str] = None,
    person_name: Optional[str] = None,
    image_paths: Optional[Sequence[str]] = None,
) -> CaseMatch:
    """Decide which case an inbound submission belongs to.

    Signals are tried strongest-first and stop at the first confident hit:

    1. explicit case id supplied by an authenticated caller
    2. per-case intake token (plus-addressed mailbox or tip link)
    3. an ``MP-YYYY-NNNN`` reference quoted in the subject or body
    4. an email reply chain leading back to an earlier routed submission
    5. a face match against reference photos enrolled on open cases
    6. a name match against open cases

    Anything scoring below ``AUTO_LINK_THRESHOLD`` returns unmatched with its
    candidates attached, so it lands in triage instead of on the wrong case.
    """
    candidates: List[Dict[str, Any]] = []

    def _candidate(case: models.MissingPersonCase, method: str, score: float) -> None:
        candidates.append(
            {
                "case_id": str(case.id),
                "case_reference": case.case_reference,
                "full_name": case.full_name,
                "method": method,
                "confidence": round(float(score), 4),
            }
        )

    # 1. Explicit id.
    if case_id:
        case = get_case(db, organization_id, case_id)
        if case is not None:
            _candidate(case, "explicit_id", 1.0)
            return CaseMatch(case, "explicit_id", 1.0, candidates)

    # 2. Intake token — the strongest signal available to unauthenticated
    #    senders, because only someone given the tip link or reply address
    #    has it.
    token = intake_token or extract_intake_token(email_to)
    if token:
        case = get_case_by_intake_token(db, token)
        if case is not None and case.organization_id == organization_id:
            _candidate(case, "intake_token", 1.0)
            return CaseMatch(case, "intake_token", 1.0, candidates)

    # 3. Quoted case reference.
    reference = case_reference or extract_case_reference(subject, message)
    if reference:
        case = get_case_by_reference(db, organization_id, reference)
        if case is not None:
            _candidate(case, "case_reference", 0.98)
            return CaseMatch(case, "case_reference", 0.98, candidates)

    # 4. Email thread continuation.
    if email_in_reply_to or email_references:
        case = find_case_by_email_thread(
            db, organization_id, in_reply_to=email_in_reply_to, references=email_references
        )
        if case is not None:
            _candidate(case, "email_thread", 0.9)
            return CaseMatch(case, "email_thread", 0.9, candidates)

    # 5. Face match on attached photos.
    if image_paths:
        case, score = find_case_by_face(db, organization_id, image_paths)
        if case is not None:
            _candidate(case, "face_match", score)
            if score >= AUTO_LINK_THRESHOLD:
                return CaseMatch(case, "face_match", score, candidates)

    # 6. Name similarity against open cases.
    for case, score in find_cases_by_name(db, organization_id, person_name):
        _candidate(case, "name_match", score)
    name_hits = [c for c in candidates if c["method"] == "name_match"]
    if name_hits:
        best = name_hits[0]
        if best["confidence"] >= AUTO_LINK_THRESHOLD:
            case = get_case(db, organization_id, UUID(str(best["case_id"])))
            if case is not None:
                return CaseMatch(case, "name_match", best["confidence"], candidates)

    return CaseMatch(None, "unmatched", 0.0, candidates)


# ─── Submissions ────────────────────────────────────────────────────────────


def create_submission(
    db: Session,
    organization_id: UUID,
    *,
    match: CaseMatch,
    source: str = "web_form",
    submission_type: str = "information",
    **fields: Any,
) -> models.MissingPersonSubmission:
    """Persist a routed submission. An unmatched one lands in the triage queue."""
    if source not in SUBMISSION_SOURCES:
        raise ValueError(f"source must be one of {sorted(SUBMISSION_SOURCES)}")
    if submission_type not in SUBMISSION_TYPES:
        raise ValueError(f"submission_type must be one of {sorted(SUBMISSION_TYPES)}")

    allowed = {c.name for c in models.MissingPersonSubmission.__table__.columns}
    payload = {k: v for k, v in fields.items() if k in allowed and v is not None}
    for reserved in ("organization_id", "case_id", "source", "submission_type",
                     "match_method", "match_confidence", "match_candidates", "status"):
        payload.pop(reserved, None)

    submission = models.MissingPersonSubmission(
        organization_id=organization_id,
        case_id=match.case.id if match.matched else None,
        source=source,
        submission_type=submission_type,
        match_method=match.method,
        match_confidence=match.confidence,
        match_candidates=match.candidates,
        # Routed submissions are still unreviewed; unrouted ones say so.
        status="new" if match.matched else "triage",
        **payload,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    if match.matched:
        record_case_update(
            db,
            match.case,
            update_type="sighting" if submission_type == "sighting" else "evidence_added",
            notes=(
                f"{submission_type.replace('_', ' ').title()} received via {source} "
                f"(linked by {match.method}, confidence {match.confidence:.2f})"
            ),
            submission_id=submission.id,
            reported_by_name=submission.submitter_name,
            reported_by_contact=submission.submitter_email or submission.submitter_phone,
            reported_by_relationship=submission.submitter_relationship,
        )
    return submission


def link_submission_to_case(
    db: Session,
    submission: models.MissingPersonSubmission,
    case: models.MissingPersonCase,
    *,
    user_id: Optional[UUID] = None,
    method: str = "manual",
    confidence: float = 1.0,
    notes: Optional[str] = None,
) -> models.MissingPersonSubmission:
    """Attach a triaged submission (and its files) to a case."""
    if case.organization_id != submission.organization_id:
        raise ValueError("Submission and case belong to different organizations")

    submission.case_id = case.id
    submission.match_method = method
    submission.match_confidence = confidence
    if submission.status == "triage":
        submission.status = "reviewing"
    submission.reviewed_by = user_id
    submission.reviewed_at = utcnow()

    # Carry the evidence across with the submission.
    db.query(models.MissingPersonAttachment).filter(
        models.MissingPersonAttachment.submission_id == submission.id
    ).update({"case_id": case.id}, synchronize_session=False)
    db.commit()
    db.refresh(submission)

    record_case_update(
        db,
        case,
        update_type="assignment",
        notes=notes or f"Submission linked to case by {method}",
        submission_id=submission.id,
        created_by=user_id,
        is_verified=method == "manual",
        verified_by=user_id if method == "manual" else None,
    )
    return submission


def list_submissions(
    db: Session,
    organization_id: UUID,
    *,
    case_id: Optional[UUID] = None,
    status: Optional[str] = None,
    unrouted_only: bool = False,
    submission_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Tuple[List[models.MissingPersonSubmission], int]:
    q = db.query(models.MissingPersonSubmission).filter(
        models.MissingPersonSubmission.organization_id == organization_id
    )
    if case_id:
        q = q.filter(models.MissingPersonSubmission.case_id == case_id)
    if unrouted_only:
        q = q.filter(models.MissingPersonSubmission.case_id.is_(None))
    if status:
        q = q.filter(models.MissingPersonSubmission.status == status)
    if submission_type:
        q = q.filter(models.MissingPersonSubmission.submission_type == submission_type)
    total = q.count()
    rows = (
        q.order_by(models.MissingPersonSubmission.created_at.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), 500))
        .all()
    )
    return rows, total


def get_submission(
    db: Session, organization_id: UUID, submission_id: UUID
) -> Optional[models.MissingPersonSubmission]:
    return (
        db.query(models.MissingPersonSubmission)
        .filter(
            models.MissingPersonSubmission.id == submission_id,
            models.MissingPersonSubmission.organization_id == organization_id,
        )
        .first()
    )


# ─── Safe / found reports ───────────────────────────────────────────────────


def record_safe_report(
    db: Session,
    case: models.MissingPersonCase,
    *,
    reported_by_name: Optional[str] = None,
    reported_by_contact: Optional[str] = None,
    reported_by_relationship: Optional[str] = None,
    notes: Optional[str] = None,
    submission_id: Optional[UUID] = None,
    verified: bool = False,
    user_id: Optional[UUID] = None,
    new_status: str = "found_safe",
) -> models.MissingPersonCaseUpdate:
    """Record that someone reported this person safe/found.

    An unverified report (the public path) is logged on the timeline and
    raises the case for review but does **not** change the case status. Only
    an authorised user verifying it closes the case — a wrong or malicious
    "they're fine" must not take a live case down.
    """
    if new_status not in {"found_safe", "found_deceased"}:
        raise ValueError("new_status must be found_safe or found_deceased")

    entry = record_case_update(
        db,
        case,
        update_type="safe_report",
        previous_status=case.status,
        new_status=new_status if verified else None,
        notes=notes,
        submission_id=submission_id,
        reported_by_name=reported_by_name,
        reported_by_contact=reported_by_contact,
        reported_by_relationship=reported_by_relationship,
        is_verified=verified,
        verified_by=user_id if verified else None,
        created_by=user_id,
    )

    if verified and case.status not in RESOLVED_STATUSES:
        update_case_status(db, case, new_status, user_id=user_id, notes=notes)
    elif not verified and case.priority != "critical":
        # Surface the case for a human to act on without closing it.
        case.priority = "high"
        db.commit()

    return entry


def verify_case_update(
    db: Session,
    case: models.MissingPersonCase,
    entry: models.MissingPersonCaseUpdate,
    *,
    user_id: UUID,
    accept: bool = True,
    notes: Optional[str] = None,
) -> models.MissingPersonCaseUpdate:
    """Confirm or reject a pending public safe report."""
    entry.is_verified = accept
    entry.verified_by = user_id
    entry.verified_at = utcnow()
    if notes:
        entry.notes = f"{entry.notes or ''}\n[review] {notes}".strip()
    db.commit()
    db.refresh(entry)

    if accept and entry.update_type == "safe_report" and case.status not in RESOLVED_STATUSES:
        update_case_status(
            db,
            case,
            entry.new_status or "found_safe",
            user_id=user_id,
            notes=notes or entry.notes,
        )
    return entry


# ─── Case statistics ────────────────────────────────────────────────────────


def get_case_stats(db: Session, organization_id: UUID) -> Dict[str, Any]:
    cases = db.query(models.MissingPersonCase).filter(
        models.MissingPersonCase.organization_id == organization_id
    )
    submissions = db.query(models.MissingPersonSubmission).filter(
        models.MissingPersonSubmission.organization_id == organization_id
    )
    return {
        "total_cases": cases.count(),
        "open_cases": cases.filter(models.MissingPersonCase.status == "open").count(),
        "found_safe": cases.filter(models.MissingPersonCase.status == "found_safe").count(),
        "critical_cases": cases.filter(
            models.MissingPersonCase.status == "open",
            models.MissingPersonCase.priority == "critical",
        ).count(),
        "total_submissions": submissions.count(),
        "untriaged_submissions": submissions.filter(
            models.MissingPersonSubmission.case_id.is_(None)
        ).count(),
        "pending_safe_reports": db.query(models.MissingPersonCaseUpdate)
        .filter(
            models.MissingPersonCaseUpdate.organization_id == organization_id,
            models.MissingPersonCaseUpdate.update_type == "safe_report",
            models.MissingPersonCaseUpdate.is_verified.is_(False),
        )
        .count(),
    }
