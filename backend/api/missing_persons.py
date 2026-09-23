"""Missing Person API (MP) — report a case, send in evidence, report someone safe.

Three audiences share one case record:

* **Investigators / authorised staff** — authenticated CRUD over cases, the
  triage queue for submissions the router could not place, and verification of
  public "found safe" reports.
* **The public** — a reporting form, a tip form that accepts photos, CCTV
  clips and documents, and a safe/found report. Gated behind
  ``ENABLE_PUBLIC_MISSING_PERSON_INTAKE`` (default off) and rate limited per IP.
* **The mail provider** — an inbound-email webhook guarded by
  ``X-Internal-API-Key``, so emailed tips and their attachments land on the
  right case automatically.

Routing (which case a submission belongs to) lives in
`services/missing_person_service.py`; this module only handles transport,
auth, validation and audit.
"""

from __future__ import annotations

import hashlib
import csv
import io
import logging
import os
from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import EmailStr
from sqlalchemy.orm import Session

from core.security import get_current_user, verify_internal_key
from core.storage import storage
from db.base import get_db
from models import models
from schemas import missing_persons_schemas as mp_schemas
from services import missing_person_service as mp_service
from services import missing_person_email_service as mp_email
from services import user_service, visitor_service
from services.redis_service import get_redis_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/missing-persons", tags=["Missing Persons"])


def _flag(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}


# Public intake is off by default: it accepts unauthenticated writes and file
# uploads, so an operator has to turn it on deliberately per deployment.
def _public_intake_enabled() -> bool:
    return _flag("ENABLE_PUBLIC_MISSING_PERSON_INTAKE")


PUBLIC_RATE_LIMIT = int(os.getenv("MP_PUBLIC_RATE_LIMIT", "10"))
PUBLIC_RATE_WINDOW = int(os.getenv("MP_PUBLIC_RATE_WINDOW_SECONDS", "3600"))
MAX_FILES_PER_SUBMISSION = int(os.getenv("MP_MAX_FILES_PER_SUBMISSION", "10"))


# ─── Shared helpers ─────────────────────────────────────────────────────────


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is deactivated")
    if user.role not in {"admin", "staff"}:
        raise HTTPException(
            status_code=403,
            detail="Missing-person case management requires staff access",
        )
    return user


def _client_ip(request: Request) -> str:
    # Proxy headers are forgeable when the app is reached directly. Enable this
    # only where the reverse proxy strips inbound X-Forwarded-For headers.
    if _flag("TRUST_PROXY_HEADERS"):
        forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "unknown"


def _require_public_intake(
    request: Request, bucket: str, *, rate_limit: bool = True
) -> str:
    """Gate public routes; rate-limit unauthenticated writes. Returns client IP."""
    if not _public_intake_enabled():
        raise HTTPException(
            status_code=404,
            detail="Public missing-person intake is not enabled on this deployment",
        )
    ip = _client_ip(request)
    if rate_limit:
        result = get_redis_service().check_rate_limit(
            key=f"mp_public:{bucket}:{ip}",
            max_requests=PUBLIC_RATE_LIMIT,
            window_seconds=PUBLIC_RATE_WINDOW,
        )
        if not result.get("allowed", True):
            raise HTTPException(
                status_code=429,
                detail="Too many submissions from this address. Please try again later.",
            )
    return ip


def _require_internal_key(
    x_internal_api_key: Optional[str] = Header(None, alias="X-Internal-API-Key"),
) -> None:
    if not verify_internal_key(x_internal_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing internal API key")


def _resolve_public_org(db: Session, explicit: Optional[UUID] = None) -> models.Organization:
    """Pick the tenant an unauthenticated submission belongs to.

    Order: explicit id → ``MP_DEFAULT_ORG_ID`` → the only organization on a
    single-tenant deployment. Multi-tenant deployments must configure the
    default, otherwise a public tip has no unambiguous home.
    """
    candidate = explicit or (os.getenv("MP_DEFAULT_ORG_ID") or "").strip() or None
    query = db.query(models.Organization).execution_options(skip_tenant_filter=True)

    if candidate:
        try:
            org = query.filter(models.Organization.id == str(candidate)).first()
        except Exception:
            org = None
        if org is None:
            raise HTTPException(status_code=400, detail="Unknown organization for public intake")
        return org

    orgs = query.limit(2).all()
    if len(orgs) == 1:
        return orgs[0]
    raise HTTPException(
        status_code=400,
        detail="MP_DEFAULT_ORG_ID must be configured for public intake on a multi-tenant deployment",
    )


async def _read_upload(file: UploadFile) -> bytes:
    """Read an upload with a hard size ceiling instead of trusting the client."""
    chunks: List[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > mp_service.MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"'{file.filename}' exceeds the "
                    f"{mp_service.MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB evidence limit"
                ),
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _attachment_out(a: models.MissingPersonAttachment) -> mp_schemas.AttachmentResponse:
    return mp_schemas.AttachmentResponse(
        id=str(a.id),
        case_id=str(a.case_id) if a.case_id else None,
        submission_id=str(a.submission_id) if a.submission_id else None,
        file_kind=a.file_kind,
        file_url=a.file_url,
        original_filename=a.original_filename,
        content_type=a.content_type,
        size_bytes=a.size_bytes,
        checksum_sha256=a.checksum_sha256,
        captured_at=a.captured_at,
        capture_location=a.capture_location,
        face_indexed=bool(a.face_indexed),
        face_match_score=a.face_match_score,
        processing_notes=a.processing_notes,
        created_at=a.created_at,
    )


def _submission_out(
    db: Session,
    s: models.MissingPersonSubmission,
    *,
    case_reference: Optional[str] = None,
    include_attachments: bool = True,
) -> mp_schemas.SubmissionResponse:
    attachments: List[mp_schemas.AttachmentResponse] = []
    if include_attachments:
        rows = (
            db.query(models.MissingPersonAttachment)
            .filter(models.MissingPersonAttachment.submission_id == s.id)
            .order_by(models.MissingPersonAttachment.created_at.asc())
            .limit(200)
            .all()
        )
        attachments = [_attachment_out(a) for a in rows]

    return mp_schemas.SubmissionResponse(
        id=str(s.id),
        case_id=str(s.case_id) if s.case_id else None,
        case_reference=case_reference,
        source=s.source,
        submission_type=s.submission_type,
        submitter_name=None if s.is_anonymous else s.submitter_name,
        submitter_email=None if s.is_anonymous else s.submitter_email,
        submitter_phone=None if s.is_anonymous else s.submitter_phone,
        submitter_relationship=s.submitter_relationship,
        is_anonymous=bool(s.is_anonymous),
        subject=s.subject,
        message=s.message,
        sighting_location=s.sighting_location,
        sighting_latitude=s.sighting_latitude,
        sighting_longitude=s.sighting_longitude,
        sighting_at=s.sighting_at,
        email_from=s.email_from,
        match_method=s.match_method,
        match_confidence=float(s.match_confidence or 0.0),
        match_candidates=list(s.match_candidates or []),
        status=s.status,
        review_notes=s.review_notes,
        reviewed_at=s.reviewed_at,
        attachments=attachments,
        created_at=s.created_at,
    )


def _update_out(u: models.MissingPersonCaseUpdate) -> mp_schemas.CaseUpdateResponse:
    return mp_schemas.CaseUpdateResponse(
        id=str(u.id),
        case_id=str(u.case_id),
        submission_id=str(u.submission_id) if u.submission_id else None,
        update_type=u.update_type,
        previous_status=u.previous_status,
        new_status=u.new_status,
        notes=u.notes,
        reported_by_name=u.reported_by_name,
        reported_by_contact=u.reported_by_contact,
        reported_by_relationship=u.reported_by_relationship,
        is_verified=bool(u.is_verified),
        verified_at=u.verified_at,
        created_at=u.created_at,
    )


def _case_counts(db: Session, case: models.MissingPersonCase) -> dict:
    attachments = db.query(models.MissingPersonAttachment).filter(
        models.MissingPersonAttachment.case_id == case.id
    )
    return {
        "submission_count": db.query(models.MissingPersonSubmission)
        .filter(models.MissingPersonSubmission.case_id == case.id)
        .count(),
        "attachment_count": attachments.count(),
        "reference_photo_count": attachments.filter(
            models.MissingPersonAttachment.file_kind == "reference_photo"
        ).count(),
        "pending_safe_reports": db.query(models.MissingPersonCaseUpdate)
        .filter(
            models.MissingPersonCaseUpdate.case_id == case.id,
            models.MissingPersonCaseUpdate.update_type == "safe_report",
            models.MissingPersonCaseUpdate.is_verified.is_(False),
        )
        .count(),
    }


def _case_out(db: Session, case: models.MissingPersonCase) -> mp_schemas.MissingPersonCaseResponse:
    return mp_schemas.MissingPersonCaseResponse(
        id=str(case.id),
        case_reference=case.case_reference,
        visitor_id=str(case.visitor_id) if case.visitor_id else None,
        disaster_event_id=str(case.disaster_event_id) if case.disaster_event_id else None,
        full_name=case.full_name,
        nickname=case.nickname,
        age=case.age,
        date_of_birth=case.date_of_birth,
        gender=case.gender,
        height_cm=case.height_cm,
        weight_kg=case.weight_kg,
        build=case.build,
        hair_color=case.hair_color,
        eye_color=case.eye_color,
        complexion=case.complexion,
        distinguishing_marks=case.distinguishing_marks,
        clothing_description=case.clothing_description,
        medical_notes=case.medical_notes,
        languages_spoken=case.languages_spoken,
        description=case.description,
        last_seen_location=case.last_seen_location,
        last_seen_latitude=case.last_seen_latitude,
        last_seen_longitude=case.last_seen_longitude,
        last_seen_at=case.last_seen_at,
        last_seen_wearing=case.last_seen_wearing,
        status=case.status,
        priority=case.priority,
        is_public=bool(case.is_public),
        external_reference=case.external_reference,
        reporter_name=case.reporter_name,
        reporter_email=case.reporter_email,
        reporter_phone=case.reporter_phone,
        reporter_relationship=case.reporter_relationship,
        reporter_consent_given=bool(case.reporter_consent_given),
        resolved_at=case.resolved_at,
        resolution_notes=case.resolution_notes,
        created_at=case.created_at,
        updated_at=case.updated_at,
        intake_email=mp_email.case_reply_address(case),
        tip_url=mp_email.case_tip_url(case),
        **_case_counts(db, case),
    )


def _require_case(db: Session, user: models.User, case_id: UUID) -> models.MissingPersonCase:
    case = mp_service.get_case(db, user.organization_id, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Missing person case not found")
    return case


async def _store_uploads(
    db: Session,
    organization_id,
    files: Optional[List[UploadFile]],
    *,
    case: Optional[models.MissingPersonCase] = None,
    submission: Optional[models.MissingPersonSubmission] = None,
    file_kind: Optional[str] = None,
    captured_at: Optional[datetime] = None,
    capture_location: Optional[str] = None,
    uploaded_by: Optional[UUID] = None,
) -> tuple[List[models.MissingPersonAttachment], int]:
    """Store each upload as an attachment. Returns (attachments, duplicates)."""
    stored: List[models.MissingPersonAttachment] = []
    duplicates = 0
    if not files:
        return stored, duplicates

    real_files = [f for f in files if f is not None and (f.filename or "").strip()]
    if len(real_files) > MAX_FILES_PER_SUBMISSION:
        raise HTTPException(
            status_code=400,
            detail=f"At most {MAX_FILES_PER_SUBMISSION} files per submission",
        )

    for upload in real_files:
        content = await _read_upload(upload)
        if not content:
            continue
        seen_before = (
            mp_service.find_duplicate_attachment(
                db, organization_id, hashlib.sha256(content).hexdigest()
            )
            is not None
        )
        try:
            attachment = mp_service.store_attachment(
                db,
                organization_id,
                content,
                filename=upload.filename,
                content_type=upload.content_type,
                file_kind=file_kind,
                case=case,
                submission=submission,
                captured_at=captured_at,
                capture_location=capture_location,
                uploaded_by=uploaded_by,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if seen_before:
            duplicates += 1
        stored.append(attachment)

    return stored, duplicates


def _local_image_paths(attachments: List[models.MissingPersonAttachment]) -> List[str]:
    """Local paths of photo attachments, for face-based routing."""
    paths: List[str] = []
    for attachment in attachments:
        if attachment.file_kind not in {"photo", "reference_photo"}:
            continue
        try:
            paths.append(str(storage.ensure_local_file(attachment.file_url)))
        except Exception:  # pragma: no cover - storage fetch failure
            logger.warning("Could not localise attachment %s for face routing", attachment.id)
    return paths


# ─── Stats & case listing (authenticated) ───────────────────────────────────


@router.get("/disaster-events", response_model=List[mp_schemas.DisasterEventResponse])
async def list_disaster_events(
    status: Optional[str] = Query(None),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    query = db.query(models.DisasterEvent).filter(
        models.DisasterEvent.organization_id == user.organization_id
    )
    if status:
        query = query.filter(models.DisasterEvent.status == status)
    return [
        mp_schemas.DisasterEventResponse(
            id=str(event.id),
            name=event.name,
            event_type=event.event_type,
            affected_areas=list(event.affected_areas or []),
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            status=event.status,
            notes=event.notes,
            created_at=event.created_at,
        )
        for event in query.order_by(models.DisasterEvent.starts_at.desc()).limit(200).all()
    ]


@router.post("/disaster-events", response_model=mp_schemas.DisasterEventResponse, status_code=201)
async def create_disaster_event(
    payload: mp_schemas.DisasterEventCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    event = models.DisasterEvent(
        organization_id=user.organization_id,
        created_by=user.id,
        name=payload.name.strip(),
        event_type=payload.event_type.strip().lower(),
        affected_areas=payload.affected_areas,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        notes=payload.notes,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "create", "disaster_event", str(event.id),
        details={"name": event.name, "event_type": event.event_type},
    )
    return mp_schemas.DisasterEventResponse(
        id=str(event.id), name=event.name, event_type=event.event_type,
        affected_areas=list(event.affected_areas or []), starts_at=event.starts_at,
        ends_at=event.ends_at, status=event.status, notes=event.notes,
        created_at=event.created_at,
    )


def _possible_match_out(
    match: models.MissingPersonPossibleMatch, case: models.MissingPersonCase
) -> mp_schemas.PossibleMatchResponse:
    return mp_schemas.PossibleMatchResponse(
        id=str(match.id), located_person_id=str(match.located_person_id),
        case_id=str(case.id), case_reference=case.case_reference, full_name=case.full_name,
        confidence=float(match.confidence), match_reasons=list(match.match_reasons or []),
        status=match.status, created_at=match.created_at,
    )


@router.post("/located-persons", response_model=mp_schemas.LocatedPersonResponse, status_code=201)
async def report_located_person(
    photo: UploadFile = File(...),
    disaster_event_id: Optional[UUID] = Form(None),
    status: str = Form("identity_unknown"),
    full_name: Optional[str] = Form(None),
    approximate_age: Optional[int] = Form(None),
    gender: Optional[str] = Form(None),
    found_location: Optional[str] = Form(None),
    found_at: Optional[datetime] = Form(None),
    facility_name: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Private staff intake. Upload never becomes public case media."""
    user = _get_user(db, current_user_id)
    if status not in {"found_safe", "injured", "hospitalized", "identity_unknown", "deceased"}:
        raise HTTPException(status_code=400, detail="Invalid located-person status")
    if disaster_event_id:
        event = db.query(models.DisasterEvent).filter(
            models.DisasterEvent.id == disaster_event_id,
            models.DisasterEvent.organization_id == user.organization_id,
        ).first()
        if event is None:
            raise HTTPException(status_code=404, detail="Disaster event not found")
    if not (photo.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Located-person matching requires an image")
    content = await _read_upload(photo)
    digest = hashlib.sha256(content).hexdigest()
    extension = os.path.splitext(photo.filename or "")[1].lower() or ".jpg"
    relative_path = f"located_persons/{user.organization_id}/{digest[:2]}/{digest}{extension}"
    storage.save_file(relative_path, content, content_type=photo.content_type)
    located = models.LocatedPerson(
        organization_id=user.organization_id,
        disaster_event_id=disaster_event_id,
        record_reference=f"LOC-{uuid4().hex[:10].upper()}",
        status=status,
        full_name=full_name,
        approximate_age=approximate_age,
        gender=gender,
        found_location=found_location,
        found_at=found_at,
        facility_name=facility_name,
        notes=notes,
        photo_url=relative_path,
        photo_content_type=photo.content_type,
        submitted_by=user.id,
    )
    db.add(located)
    db.commit()
    db.refresh(located)

    case, confidence = mp_service.find_case_by_face(
        db, user.organization_id, [str(storage.ensure_local_file(relative_path))]
    )
    suggestions = []
    if case is not None:
        if disaster_event_id and case.disaster_event_id and case.disaster_event_id != disaster_event_id:
            case = None
        if case is not None:
            match = models.MissingPersonPossibleMatch(
                organization_id=user.organization_id, located_person_id=located.id,
                case_id=case.id, confidence=confidence,
                match_reasons=["face_similarity"],
            )
            db.add(match)
            db.commit()
            db.refresh(match)
            suggestions.append(_possible_match_out(match, case))
    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "report", "located_person", str(located.id),
        details={"status": status, "possible_matches": len(suggestions)},
    )
    return mp_schemas.LocatedPersonResponse(
        id=str(located.id), record_reference=located.record_reference,
        disaster_event_id=located.disaster_event_id, status=located.status,
        full_name=located.full_name, approximate_age=located.approximate_age,
        gender=located.gender, found_location=located.found_location, found_at=located.found_at,
        facility_name=located.facility_name, notes=located.notes, photo_url=None,
        created_at=located.created_at, possible_matches=suggestions,
    )


@router.post("/possible-matches/{match_id}/review", response_model=mp_schemas.PossibleMatchResponse)
async def review_possible_match(
    match_id: UUID,
    payload: mp_schemas.PossibleMatchReview,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Human confirmation is required before any case is identified or closed."""
    user = _get_user(db, current_user_id)
    match = db.query(models.MissingPersonPossibleMatch).filter(
        models.MissingPersonPossibleMatch.id == match_id,
        models.MissingPersonPossibleMatch.organization_id == user.organization_id,
    ).first()
    if match is None or match.status != "pending":
        raise HTTPException(status_code=404, detail="Pending possible match not found")
    case = _require_case(db, user, match.case_id)
    match.status = "confirmed" if payload.accept else "rejected"
    match.reviewer_notes = payload.notes
    match.reviewed_by = user.id
    match.reviewed_at = mp_service.utcnow()
    if payload.accept:
        if payload.confirmed_case_status not in mp_service.CASE_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid confirmed case status")
        mp_service.update_case_status(
            db, case, payload.confirmed_case_status, user_id=user.id, notes=payload.notes
        )
    db.commit()
    db.refresh(match)
    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "review", "missing_person_possible_match", str(match.id),
        details={"accepted": payload.accept, "case_id": str(case.id)},
    )
    return _possible_match_out(match, case)


@router.post("/bulk-import", response_model=mp_schemas.MissingPersonBulkImportResult)
async def bulk_import_missing_person_cases(
    file: UploadFile = File(...),
    disaster_event_id: Optional[UUID] = Form(None),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Import staff-supplied missing-person records from a UTF-8 CSV file.

    Expected columns: full_name (required), age, gender, last_seen_location,
    last_seen_at, clothing_description, distinguishing_marks, priority,
    reporter_name, reporter_email, reporter_phone, reporter_relationship.
    CSV imports intentionally do not ingest image URLs; reference photos must
    use the authenticated upload route so external URLs never become SSRF input.
    """
    user = _get_user(db, current_user_id)
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a CSV file")
    content = await _read_upload(file)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV import is limited to 5MB")
    if disaster_event_id:
        event = db.query(models.DisasterEvent).filter(
            models.DisasterEvent.id == disaster_event_id,
            models.DisasterEvent.organization_id == user.organization_id,
        ).first()
        if event is None:
            raise HTTPException(status_code=404, detail="Disaster event not found")
    try:
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid CSV: {exc}")
    if not rows:
        raise HTTPException(status_code=400, detail="CSV contains no data rows")
    if len(rows) > 2_000:
        raise HTTPException(status_code=400, detail="CSV import is limited to 2,000 rows")

    imported, errors = 0, []
    for row_number, row in enumerate(rows, start=2):
        full_name = (row.get("full_name") or row.get("name") or "").strip()
        if len(full_name) < 2:
            errors.append({"row": row_number, "error": "full_name is required"})
            continue
        try:
            age_text = (row.get("age") or "").strip()
            age = int(age_text) if age_text else None
            seen_text = (row.get("last_seen_at") or "").strip()
            last_seen_at = datetime.fromisoformat(seen_text.replace("Z", "+00:00")) if seen_text else None
            priority = (row.get("priority") or "medium").strip().lower()
            status = (row.get("status") or "pending_verification").strip().lower()
            case = mp_service.create_case(
                db,
                user.organization_id,
                full_name=full_name,
                created_by=user.id,
                disaster_event_id=disaster_event_id,
                age=age,
                gender=(row.get("gender") or "").strip() or None,
                nickname=(row.get("nickname") or "").strip() or None,
                last_seen_location=(row.get("last_seen_location") or "").strip() or None,
                last_seen_at=last_seen_at,
                clothing_description=(row.get("clothing_description") or "").strip() or None,
                distinguishing_marks=(row.get("distinguishing_marks") or "").strip() or None,
                reporter_name=(row.get("reporter_name") or "").strip() or None,
                reporter_email=(row.get("reporter_email") or "").strip() or None,
                reporter_phone=(row.get("reporter_phone") or "").strip() or None,
                reporter_relationship=(row.get("reporter_relationship") or "").strip() or None,
                priority=priority,
                status=status,
            )
            imported += 1
            visitor_service.create_audit_log(
                db, user.organization_id, user.id, "import", "missing_person_case", str(case.id),
                details={"row": row_number, "source": file.filename},
            )
        except (TypeError, ValueError) as exc:
            errors.append({"row": row_number, "error": str(exc)})
    return mp_schemas.MissingPersonBulkImportResult(
        imported=imported, failed=len(errors), errors=errors[:100]
    )


@router.get("/stats", response_model=mp_schemas.MissingPersonStats)
async def get_stats(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    return mp_schemas.MissingPersonStats(**mp_service.get_case_stats(db, user.organization_id))


@router.get("/", response_model=mp_schemas.CaseListResponse)
async def list_cases(
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Search name, nickname, reference or location"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    cases, total = mp_service.list_cases(
        db,
        user.organization_id,
        status=status,
        priority=priority,
        query=q,
        limit=limit,
        offset=offset,
    )
    return mp_schemas.CaseListResponse(
        items=[_case_out(db, c) for c in cases],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/", response_model=mp_schemas.MissingPersonCaseResponse, status_code=201)
async def create_case(
    payload: mp_schemas.MissingPersonCaseCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    data = payload.model_dump(exclude_unset=True)
    full_name = data.pop("full_name")
    if data.get("reporter_email"):
        data["reporter_email"] = str(data["reporter_email"])
    if data.get("is_public") and not data.get("reporter_consent_given"):
        raise HTTPException(
            status_code=400,
            detail="Reporter consent is required before publishing a case",
        )
    try:
        case = mp_service.create_case(
            db, user.organization_id, full_name=full_name, created_by=user.id, **data
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "create",
        "missing_person_case",
        str(case.id),
        details={"case_reference": case.case_reference, "full_name": case.full_name},
    )
    return _case_out(db, case)


# ─── Triage queue (declared before /{case_id} so the literal path wins) ─────


@router.get("/submissions", response_model=mp_schemas.SubmissionListResponse)
async def list_all_submissions(
    status: Optional[str] = Query(None),
    submission_type: Optional[str] = Query(None),
    unrouted_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    rows, total = mp_service.list_submissions(
        db,
        user.organization_id,
        status=status,
        submission_type=submission_type,
        unrouted_only=unrouted_only,
        limit=limit,
        offset=offset,
    )
    return mp_schemas.SubmissionListResponse(
        items=[_submission_out(db, s) for s in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/submissions/triage", response_model=mp_schemas.SubmissionListResponse)
async def list_triage_queue(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submissions the router could not confidently place on a case.

    Nothing is discarded when auto-routing fails — it lands here with the
    candidate cases the router considered, for a human to assign.
    """
    user = _get_user(db, current_user_id)
    rows, total = mp_service.list_submissions(
        db, user.organization_id, unrouted_only=True, limit=limit, offset=offset
    )
    return mp_schemas.SubmissionListResponse(
        items=[_submission_out(db, s) for s in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/submissions/{submission_id}", response_model=mp_schemas.SubmissionResponse)
async def get_submission(
    submission_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    submission = mp_service.get_submission(db, user.organization_id, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    case_ref = None
    if submission.case_id:
        case = mp_service.get_case(db, user.organization_id, submission.case_id)
        case_ref = case.case_reference if case else None
    return _submission_out(db, submission, case_reference=case_ref)


@router.patch("/submissions/{submission_id}", response_model=mp_schemas.SubmissionResponse)
async def review_submission(
    submission_id: UUID,
    payload: mp_schemas.SubmissionReview,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    submission = mp_service.get_submission(db, user.organization_id, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")

    if payload.status is not None:
        if payload.status not in mp_service.SUBMISSION_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"status must be one of {sorted(mp_service.SUBMISSION_STATUSES)}",
            )
        submission.status = payload.status
    if payload.review_notes is not None:
        submission.review_notes = payload.review_notes
    submission.reviewed_by = user.id
    submission.reviewed_at = mp_service.utcnow()
    db.commit()
    db.refresh(submission)

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "review",
        "missing_person_submission",
        str(submission.id),
        details={"status": submission.status},
    )
    return _submission_out(db, submission)


@router.post("/submissions/{submission_id}/assign", response_model=mp_schemas.SubmissionResponse)
async def assign_submission(
    submission_id: UUID,
    payload: mp_schemas.SubmissionAssign,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Manually attach a triaged submission (and its files) to a case."""
    user = _get_user(db, current_user_id)
    submission = mp_service.get_submission(db, user.organization_id, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    case = _require_case(db, user, payload.case_id)

    try:
        submission = mp_service.link_submission_to_case(
            db, submission, case, user_id=user.id, method="manual", notes=payload.notes
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "assign",
        "missing_person_submission",
        str(submission.id),
        details={"case_id": str(case.id), "case_reference": case.case_reference},
    )
    return _submission_out(db, submission, case_reference=case.case_reference)


@router.post("/updates/{update_id}/verify", response_model=mp_schemas.CaseUpdateResponse)
async def verify_update(
    update_id: UUID,
    payload: mp_schemas.SafeReportVerification,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Confirm or reject a public safe/found report.

    Accepting one is what actually closes the case — an unverified public
    report never changes case status on its own.
    """
    user = _get_user(db, current_user_id)
    entry = (
        db.query(models.MissingPersonCaseUpdate)
        .filter(
            models.MissingPersonCaseUpdate.id == update_id,
            models.MissingPersonCaseUpdate.organization_id == user.organization_id,
        )
        .first()
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Case update not found")
    case = _require_case(db, user, entry.case_id)

    entry = mp_service.verify_case_update(
        db, case, entry, user_id=user.id, accept=payload.accept, notes=payload.notes
    )
    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "verify",
        "missing_person_case_update",
        str(entry.id),
        details={"accepted": payload.accept, "case_reference": case.case_reference},
    )
    return _update_out(entry)


# ─── Public routes (declared before /{case_id}) ─────────────────────────────


@router.get("/public/cases", response_model=List[mp_schemas.PublicCaseSummary])
async def list_public_cases(
    request: Request,
    organization_id: Optional[UUID] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Open cases the organization has chosen to appeal publicly."""
    _require_public_intake(request, "browse", rate_limit=False)
    org = _resolve_public_org(db, organization_id)
    cases, _total = mp_service.list_cases(
        db, org.id, status="open", public_only=True, limit=limit
    )
    return [_public_case_summary(db, c) for c in cases]


def _public_case_summary(
    db: Session, case: models.MissingPersonCase
) -> mp_schemas.PublicCaseSummary:
    photos = [
        f"/api/v1/missing-persons/public/media/{a.id}"
        for a in mp_service.list_case_attachments(db, case, file_kind="reference_photo", limit=5)
    ]
    return mp_schemas.PublicCaseSummary(
        case_reference=case.case_reference,
        full_name=case.full_name,
        nickname=case.nickname,
        age=case.age,
        gender=case.gender,
        height_cm=case.height_cm,
        build=case.build,
        hair_color=case.hair_color,
        eye_color=case.eye_color,
        distinguishing_marks=case.distinguishing_marks,
        clothing_description=case.clothing_description,
        last_seen_location=case.last_seen_location,
        last_seen_at=case.last_seen_at,
        last_seen_wearing=case.last_seen_wearing,
        description=case.description,
        status=case.status,
        photo_urls=photos,
    )


@router.get("/public/media/{attachment_id}")
async def get_public_reference_photo(
    attachment_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """Serve only reference photos explicitly approved for a public case."""
    _require_public_intake(request, "media", rate_limit=False)
    attachment = (
        db.query(models.MissingPersonAttachment)
        .join(
            models.MissingPersonCase,
            models.MissingPersonAttachment.case_id == models.MissingPersonCase.id,
        )
        .filter(
            models.MissingPersonAttachment.id == attachment_id,
            models.MissingPersonAttachment.file_kind == "reference_photo",
            models.MissingPersonCase.is_public.is_(True),
            models.MissingPersonCase.status == "open",
        )
        .first()
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="Public photo not found")
    try:
        local_path = storage.ensure_local_file(attachment.file_url)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Public photo not found")
    except RuntimeError:
        logger.exception("Failed to hydrate public missing-person photo %s", attachment.id)
        raise HTTPException(status_code=502, detail="Asset storage is unavailable")
    return FileResponse(local_path, media_type=attachment.content_type or "image/jpeg")


@router.get("/public/cases/{case_reference}", response_model=mp_schemas.PublicCaseSummary)
async def get_public_case(
    case_reference: str,
    request: Request,
    organization_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
):
    _require_public_intake(request, "browse", rate_limit=False)
    org = _resolve_public_org(db, organization_id)
    case = mp_service.get_case_by_reference(db, org.id, case_reference)
    if case is None or not case.is_public:
        raise HTTPException(status_code=404, detail="Case not found")
    return _public_case_summary(db, case)


@router.post(
    "/public/report",
    response_model=mp_schemas.SubmissionAccepted,
    status_code=201,
)
async def public_report_missing_person(
    request: Request,
    full_name: str = Form(..., min_length=2, max_length=255),
    reporter_name: str = Form(..., min_length=2, max_length=255),
    reporter_email: EmailStr = Form(...),
    reporter_relationship: str = Form(..., min_length=2, max_length=120),
    reporter_consent_given: bool = Form(...),
    reporter_phone: Optional[str] = Form(None),
    nickname: Optional[str] = Form(None),
    age: Optional[int] = Form(None),
    gender: Optional[str] = Form(None),
    height_cm: Optional[float] = Form(None),
    weight_kg: Optional[float] = Form(None),
    build: Optional[str] = Form(None),
    hair_color: Optional[str] = Form(None),
    eye_color: Optional[str] = Form(None),
    complexion: Optional[str] = Form(None),
    distinguishing_marks: Optional[str] = Form(None),
    clothing_description: Optional[str] = Form(None),
    medical_notes: Optional[str] = Form(None),
    languages_spoken: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    last_seen_location: Optional[str] = Form(None),
    last_seen_at: Optional[datetime] = Form(None),
    last_seen_wearing: Optional[str] = Form(None),
    organization_id: Optional[UUID] = Form(None),
    files: Optional[List[UploadFile]] = File(None),
    db: Session = Depends(get_db),
):
    """Public form: report a missing person, with photos/documents attached.

    The case is created as non-public and medium priority — an authorised user
    reviews it before it is appealed publicly. Photos supplied here are stored
    but **not** face-indexed automatically: enrolling a biometric template is a
    staff action, deliberately kept off the unauthenticated path.
    """
    _require_public_intake(request, "report")
    if not reporter_consent_given:
        raise HTTPException(
            status_code=400,
            detail="Reporter consent is required to hold and share this person's details",
        )
    org = _resolve_public_org(db, organization_id)

    try:
        case = mp_service.create_case(
            db,
            org.id,
            full_name=full_name,
            nickname=nickname,
            age=age,
            gender=gender,
            height_cm=height_cm,
            weight_kg=weight_kg,
            build=build,
            hair_color=hair_color,
            eye_color=eye_color,
            complexion=complexion,
            distinguishing_marks=distinguishing_marks,
            clothing_description=clothing_description,
            medical_notes=medical_notes,
            languages_spoken=languages_spoken,
            description=description,
            last_seen_location=last_seen_location,
            last_seen_at=last_seen_at,
            last_seen_wearing=last_seen_wearing,
            reporter_name=reporter_name,
            reporter_email=str(reporter_email),
            reporter_phone=reporter_phone,
            reporter_relationship=reporter_relationship,
            reporter_consent_given=True,
            is_public=False,
            status="open",
            priority="medium",
            case_metadata={"intake": "public_form", "source_ip": _client_ip(request)},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    match = mp_service.CaseMatch(case=case, method="explicit_id", confidence=1.0)
    submission = mp_service.create_submission(
        db,
        org.id,
        match=match,
        source="public_form",
        submission_type="information",
        submitter_name=reporter_name,
        submitter_email=reporter_email,
        submitter_phone=reporter_phone,
        submitter_relationship=reporter_relationship,
        subject=f"Initial report for {full_name}",
        message=description,
        ip_address=_client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:512] or None,
    )
    attachments, duplicates = await _store_uploads(
        db, org.id, files, case=case, submission=submission
    )

    mp_email.send_submission_acknowledgement(
        case, submission, attachment_count=len(attachments)
    )
    return mp_schemas.SubmissionAccepted(
        submission_id=str(submission.id),
        case_reference=case.case_reference,
        matched=True,
        match_method="explicit_id",
        match_confidence=1.0,
        attachments_received=len(attachments),
        duplicate_attachments=duplicates,
        reply_to=mp_email.case_reply_address(case),
        message=(
            f"Report received and filed as {case.case_reference}. "
            "Quote this reference in any further information you send."
        ),
    )


@router.post("/public/tips", response_model=mp_schemas.SubmissionAccepted, status_code=201)
async def public_submit_tip(
    request: Request,
    message: Optional[str] = Form(None),
    case_reference: Optional[str] = Form(None),
    intake_token: Optional[str] = Form(None),
    person_name: Optional[str] = Form(None),
    submission_type: str = Form("sighting"),
    submitter_name: Optional[str] = Form(None),
    submitter_email: Optional[str] = Form(None),
    submitter_phone: Optional[str] = Form(None),
    submitter_relationship: Optional[str] = Form(None),
    is_anonymous: bool = Form(False),
    sighting_location: Optional[str] = Form(None),
    sighting_latitude: Optional[float] = Form(None),
    sighting_longitude: Optional[float] = Form(None),
    sighting_at: Optional[datetime] = Form(None),
    capture_location: Optional[str] = Form(None),
    organization_id: Optional[UUID] = Form(None),
    files: Optional[List[UploadFile]] = File(None),
    db: Session = Depends(get_db),
):
    """Public form: send information about a missing person, with files.

    Accepts photos, CCTV/camera footage and documents. The submission is
    routed to a case by reference, intake token, face match on an attached
    photo, or name — and lands in the triage queue if none of those is
    confident enough.
    """
    _require_public_intake(request, "tip")
    if submission_type not in mp_service.SUBMISSION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"submission_type must be one of {sorted(mp_service.SUBMISSION_TYPES)}",
        )

    # An intake token identifies the case *and* its tenant, so honour it
    # before falling back to the deployment default.
    org: Optional[models.Organization] = None
    token_case = mp_service.get_case_by_intake_token(db, intake_token) if intake_token else None
    if token_case is not None:
        org = (
            db.query(models.Organization)
            .execution_options(skip_tenant_filter=True)
            .filter(models.Organization.id == token_case.organization_id)
            .first()
        )
    if org is None:
        org = _resolve_public_org(db, organization_id)

    if not message and not files:
        raise HTTPException(status_code=400, detail="Provide a message or at least one file")

    # Files are stored before routing so a photo can drive the face match.
    staged, duplicates = await _store_uploads(
        db, org.id, files, capture_location=capture_location
    )
    match = mp_service.route_submission(
        db,
        org.id,
        case_reference=case_reference,
        intake_token=intake_token,
        subject=None,
        message=message,
        person_name=person_name,
        image_paths=_local_image_paths(staged),
    )

    submission = mp_service.create_submission(
        db,
        org.id,
        match=match,
        source="public_form",
        submission_type=submission_type,
        submitter_name=None if is_anonymous else submitter_name,
        submitter_email=None if is_anonymous else submitter_email,
        submitter_phone=None if is_anonymous else submitter_phone,
        submitter_relationship=submitter_relationship,
        is_anonymous=is_anonymous,
        message=message,
        sighting_location=sighting_location,
        sighting_latitude=sighting_latitude,
        sighting_longitude=sighting_longitude,
        sighting_at=sighting_at,
        ip_address=_client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:512] or None,
    )

    # Bind the staged files to the submission (and case, if routed).
    for attachment in staged:
        attachment.submission_id = submission.id
        attachment.case_id = match.case.id if match.matched else None
    if staged:
        db.commit()

    if not is_anonymous and submitter_email:
        submission.submitter_email = submitter_email
        mp_email.send_submission_acknowledgement(
            match.case, submission, attachment_count=len(staged)
        )

    return mp_schemas.SubmissionAccepted(
        submission_id=str(submission.id),
        case_reference=match.case.case_reference if match.matched else None,
        matched=match.matched,
        match_method=match.method,
        match_confidence=match.confidence,
        attachments_received=len(staged),
        duplicate_attachments=duplicates,
        reply_to=mp_email.case_reply_address(match.case) if match.matched else None,
        message=(
            f"Thank you. Your information was filed under {match.case.case_reference}."
            if match.matched
            else "Thank you. Your information was received and is queued for review."
        ),
    )


@router.post("/public/safe-report", response_model=mp_schemas.SafeReportAccepted, status_code=201)
async def public_safe_report(
    payload: mp_schemas.SafeReportRequest,
    request: Request,
    organization_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
):
    """Public route: report that a missing person is safe / has been found.

    This records the report and raises the case for review; it does **not**
    close the case. An authorised user verifies it via
    ``POST /missing-persons/updates/{update_id}/verify``, which is what
    prevents a hoax or a mistaken identification from closing a live case.
    """
    _require_public_intake(request, "safe_report")

    case: Optional[models.MissingPersonCase] = None
    if payload.intake_token:
        case = mp_service.get_case_by_intake_token(db, payload.intake_token)
    if case is None and payload.case_reference:
        org = _resolve_public_org(db, organization_id)
        case = mp_service.get_case_by_reference(db, org.id, payload.case_reference)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if payload.outcome not in {"found_safe", "found_deceased"}:
        raise HTTPException(status_code=400, detail="outcome must be found_safe or found_deceased")

    submission = mp_service.create_submission(
        db,
        case.organization_id,
        match=mp_service.CaseMatch(case=case, method="intake_token" if payload.intake_token else "case_reference", confidence=1.0),
        source="public_form",
        submission_type="safe_report",
        submitter_name=payload.reported_by_name,
        submitter_relationship=payload.reported_by_relationship,
        message=payload.notes,
        ip_address=_client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:512] or None,
    )
    entry = mp_service.record_safe_report(
        db,
        case,
        reported_by_name=payload.reported_by_name,
        reported_by_contact=payload.reported_by_contact,
        reported_by_relationship=payload.reported_by_relationship,
        notes=payload.notes,
        submission_id=submission.id,
        verified=False,
        new_status=payload.outcome,
    )
    return mp_schemas.SafeReportAccepted(
        case_reference=case.case_reference,
        update_id=str(entry.id),
        case_status=case.status,
        verified=False,
        message=(
            "Thank you. Your report has been recorded and flagged for urgent review. "
            "The case stays open until it is confirmed."
        ),
    )


# ─── Inbound email intake (internal service key) ────────────────────────────


@router.post(
    "/intake/email",
    response_model=mp_schemas.EmailIntakeResult,
    status_code=201,
    dependencies=[Depends(_require_internal_key)],
)
async def intake_email(
    payload: mp_schemas.EmailIntakeRequest,
    db: Session = Depends(get_db),
):
    """Ingest an inbound email and route it to the right case.

    Requires ``X-Internal-API-Key`` — the caller is the mail provider's
    webhook or an IMAP poller, not a browser. Attachments are stored as
    evidence and the sender gets an acknowledgement naming the case their
    information landed on.
    """
    raw = payload.model_dump()
    org_id = raw.pop("organization_id", None)
    parsed = mp_email.parse_inbound_payload(raw)

    # The intake token in the recipient address also identifies the tenant.
    token = mp_service.extract_intake_token(parsed.get("to_address"))
    token_case = mp_service.get_case_by_intake_token(db, token) if token else None
    if token_case is not None:
        org = (
            db.query(models.Organization)
            .execution_options(skip_tenant_filter=True)
            .filter(models.Organization.id == token_case.organization_id)
            .first()
        )
        if org is None:
            raise HTTPException(status_code=400, detail="Unknown organization for intake token")
    else:
        org = _resolve_public_org(db, org_id)

    # Store attachments first so photos can drive the face match.
    staged: List[models.MissingPersonAttachment] = []
    for item in parsed.get("attachments", [])[:MAX_FILES_PER_SUBMISSION]:
        try:
            staged.append(
                mp_service.store_attachment(
                    db,
                    org.id,
                    item["content"],
                    filename=item.get("filename"),
                    content_type=item.get("content_type"),
                )
            )
        except ValueError as exc:
            logger.warning("Rejected emailed attachment: %s", exc)

    match = mp_service.route_submission(
        db,
        org.id,
        intake_token=token,
        subject=parsed.get("subject"),
        message=parsed.get("body"),
        email_to=parsed.get("to_address"),
        email_in_reply_to=parsed.get("in_reply_to"),
        email_references=parsed.get("references"),
        person_name=None,
        image_paths=_local_image_paths(staged),
    )

    submission = mp_service.create_submission(
        db,
        org.id,
        match=match,
        source="email",
        submission_type="information",
        submitter_name=parsed.get("from_name"),
        submitter_email=parsed.get("from_address"),
        subject=parsed.get("subject"),
        message=parsed.get("body"),
        email_message_id=parsed.get("message_id"),
        email_in_reply_to=parsed.get("in_reply_to"),
        email_from=parsed.get("from_address"),
        email_to=parsed.get("to_address"),
    )

    for attachment in staged:
        attachment.submission_id = submission.id
        attachment.case_id = match.case.id if match.matched else None
    if staged:
        db.commit()

    acknowledged = mp_email.send_submission_acknowledgement(
        match.case, submission, attachment_count=len(staged)
    )
    return mp_schemas.EmailIntakeResult(
        submission_id=str(submission.id),
        case_reference=match.case.case_reference if match.matched else None,
        matched=match.matched,
        match_method=match.method,
        match_confidence=match.confidence,
        attachments_stored=len(staged),
        acknowledgement_sent=acknowledged,
    )


# ─── Single-case routes (parameterised — declared last) ─────────────────────


@router.get("/{case_id}", response_model=mp_schemas.MissingPersonCaseDetail)
async def get_case_detail(
    case_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Everything held on one case: details, submissions, evidence, timeline."""
    user = _get_user(db, current_user_id)
    case = _require_case(db, user, case_id)

    submissions, _total = mp_service.list_submissions(
        db, user.organization_id, case_id=case.id, limit=200
    )
    attachments = mp_service.list_case_attachments(db, case)
    timeline = mp_service.get_case_timeline(db, case)

    base = _case_out(db, case)
    return mp_schemas.MissingPersonCaseDetail(
        **base.model_dump(),
        submissions=[
            _submission_out(db, s, case_reference=case.case_reference) for s in submissions
        ],
        attachments=[_attachment_out(a) for a in attachments],
        timeline=[_update_out(u) for u in timeline],
    )


@router.patch("/{case_id}", response_model=mp_schemas.MissingPersonCaseResponse)
async def update_case(
    case_id: UUID,
    payload: mp_schemas.MissingPersonCaseUpdateRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    case = _require_case(db, user, case_id)

    data = payload.model_dump(exclude_unset=True)
    if "priority" in data and data["priority"] not in mp_service.CASE_PRIORITIES:
        raise HTTPException(
            status_code=400,
            detail=f"priority must be one of {sorted(mp_service.CASE_PRIORITIES)}",
        )
    if data.get("reporter_email"):
        data["reporter_email"] = str(data["reporter_email"])
    if data.get("is_public") and not (data.get("reporter_consent_given") or case.reporter_consent_given):
        raise HTTPException(
            status_code=400,
            detail="Reporter consent is required before publishing a case",
        )
    for key, value in data.items():
        setattr(case, key, value)
    db.commit()
    db.refresh(case)

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "update",
        "missing_person_case",
        str(case.id),
        details={"fields": sorted(data.keys())},
    )
    return _case_out(db, case)


@router.post("/{case_id}/status", response_model=mp_schemas.MissingPersonCaseResponse)
async def change_case_status(
    case_id: UUID,
    payload: mp_schemas.CaseStatusChange,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Move a case's status — including confirming the person is found safe."""
    user = _get_user(db, current_user_id)
    case = _require_case(db, user, case_id)
    previous = case.status

    try:
        case = mp_service.update_case_status(
            db, case, payload.status, user_id=user.id, notes=payload.notes
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "status_change",
        "missing_person_case",
        str(case.id),
        details={"from": previous, "to": case.status},
    )
    if case.reporter_email:
        background_tasks.add_task(
            mp_email.send_case_status_notification, case, previous_status=previous
        )
    return _case_out(db, case)


@router.get("/{case_id}/timeline", response_model=List[mp_schemas.CaseUpdateResponse])
async def get_timeline(
    case_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    case = _require_case(db, user, case_id)
    return [_update_out(u) for u in mp_service.get_case_timeline(db, case)]


@router.get("/{case_id}/attachments", response_model=List[mp_schemas.AttachmentResponse])
async def list_attachments(
    case_id: UUID,
    file_kind: Optional[str] = Query(None),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    case = _require_case(db, user, case_id)
    rows = mp_service.list_case_attachments(db, case, file_kind=file_kind)
    return [_attachment_out(a) for a in rows]


@router.post(
    "/{case_id}/evidence",
    response_model=List[mp_schemas.AttachmentResponse],
    status_code=201,
)
async def upload_case_evidence(
    case_id: UUID,
    files: List[UploadFile] = File(...),
    file_kind: Optional[str] = Form(None, description="photo | cctv_footage | video | document | audio | other"),
    capture_location: Optional[str] = Form(None),
    captured_at: Optional[datetime] = Form(None),
    camera_id: Optional[UUID] = Form(None),
    notes: Optional[str] = Form(None),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Attach evidence directly to a case — photos, CCTV clips, documents."""
    user = _get_user(db, current_user_id)
    case = _require_case(db, user, case_id)

    if file_kind and file_kind not in mp_service.ATTACHMENT_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"file_kind must be one of {sorted(mp_service.ATTACHMENT_KINDS)}",
        )
    if camera_id is not None:
        camera = (
            db.query(models.Camera)
            .filter(
                models.Camera.id == camera_id,
                models.Camera.organization_id == user.organization_id,
            )
            .first()
        )
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")

    attachments, _duplicates = await _store_uploads(
        db,
        user.organization_id,
        files,
        case=case,
        file_kind=file_kind,
        captured_at=captured_at,
        capture_location=capture_location,
        uploaded_by=user.id,
    )
    if camera_id is not None:
        for attachment in attachments:
            attachment.camera_id = camera_id
        db.commit()

    mp_service.record_case_update(
        db,
        case,
        update_type="evidence_added",
        notes=notes or f"{len(attachments)} file(s) added to the case",
        created_by=user.id,
        is_verified=True,
        verified_by=user.id,
    )
    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "upload_evidence",
        "missing_person_case",
        str(case.id),
        details={"files": len(attachments)},
    )
    return [_attachment_out(a) for a in attachments]


@router.post(
    "/{case_id}/reference-photos",
    response_model=List[mp_schemas.AttachmentResponse],
    status_code=201,
)
async def upload_reference_photos(
    case_id: UUID,
    files: List[UploadFile] = File(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload reference photos of the missing person and enrol their faces.

    Enrolment creates (or reuses) a Visitor record for the case, so the live
    recognition path can raise a sighting. A photo the AI service cannot
    embed is still stored, with the reason recorded on the attachment.
    """
    user = _get_user(db, current_user_id)
    case = _require_case(db, user, case_id)

    attachments, _duplicates = await _store_uploads(
        db,
        user.organization_id,
        files,
        case=case,
        file_kind="photo",
        uploaded_by=user.id,
    )

    indexed = 0
    for attachment in attachments:
        ok, error = mp_service.index_reference_photo(db, case, attachment)
        if ok:
            indexed += 1
        else:
            logger.info("Reference photo %s not indexed: %s", attachment.id, error)

    mp_service.record_case_update(
        db,
        case,
        update_type="evidence_added",
        notes=f"{len(attachments)} reference photo(s) uploaded, {indexed} face-indexed",
        created_by=user.id,
        is_verified=True,
        verified_by=user.id,
    )
    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "enroll_reference_photo",
        "missing_person_case",
        str(case.id),
        details={"uploaded": len(attachments), "indexed": indexed},
    )
    db.refresh(case)
    return [_attachment_out(a) for a in attachments]


@router.get("/{case_id}/sightings")
async def list_case_sightings(
    case_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Camera detections matched to this case's enrolled reference faces."""
    user = _get_user(db, current_user_id)
    case = _require_case(db, user, case_id)
    logs = mp_service.get_case_sightings(db, case, limit=limit)
    return [
        {
            "log_id": str(log.id),
            "camera_id": str(log.camera_id) if log.camera_id else None,
            "confidence": log.confidence,
            "timestamp": log.timestamp,
            "image_url": log.image_url,
        }
        for log in logs
    ]


@router.post(
    "/{case_id}/submissions",
    response_model=mp_schemas.SubmissionAccepted,
    status_code=201,
)
async def create_case_submission(
    case_id: UUID,
    request: Request,
    message: Optional[str] = Form(None),
    submission_type: str = Form("information"),
    submitter_name: Optional[str] = Form(None),
    submitter_email: Optional[str] = Form(None),
    submitter_phone: Optional[str] = Form(None),
    submitter_relationship: Optional[str] = Form(None),
    sighting_location: Optional[str] = Form(None),
    sighting_latitude: Optional[float] = Form(None),
    sighting_longitude: Optional[float] = Form(None),
    sighting_at: Optional[datetime] = Form(None),
    files: Optional[List[UploadFile]] = File(None),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Staff-side equivalent of the public tip form — logs a phone call,
    a walk-in report, or evidence handed over by another agency."""
    user = _get_user(db, current_user_id)
    case = _require_case(db, user, case_id)
    if submission_type not in mp_service.SUBMISSION_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"submission_type must be one of {sorted(mp_service.SUBMISSION_TYPES)}",
        )

    submission = mp_service.create_submission(
        db,
        user.organization_id,
        match=mp_service.CaseMatch(case=case, method="explicit_id", confidence=1.0),
        source="internal",
        submission_type=submission_type,
        submitter_name=submitter_name,
        submitter_email=submitter_email,
        submitter_phone=submitter_phone,
        submitter_relationship=submitter_relationship,
        message=message,
        sighting_location=sighting_location,
        sighting_latitude=sighting_latitude,
        sighting_longitude=sighting_longitude,
        sighting_at=sighting_at,
        ip_address=_client_ip(request),
    )
    attachments, duplicates = await _store_uploads(
        db,
        user.organization_id,
        files,
        case=case,
        submission=submission,
        uploaded_by=user.id,
    )
    return mp_schemas.SubmissionAccepted(
        submission_id=str(submission.id),
        case_reference=case.case_reference,
        matched=True,
        match_method="explicit_id",
        match_confidence=1.0,
        attachments_received=len(attachments),
        duplicate_attachments=duplicates,
        reply_to=mp_email.case_reply_address(case),
        message=f"Submission recorded against {case.case_reference}",
    )


@router.post(
    "/{case_id}/safe-report",
    response_model=mp_schemas.SafeReportAccepted,
    status_code=201,
)
async def staff_safe_report(
    case_id: UUID,
    payload: mp_schemas.SafeReportRequest,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Authorised confirmation that the person has been found.

    Unlike the public route this is trusted: it verifies the report and moves
    the case status in one step.
    """
    user = _get_user(db, current_user_id)
    case = _require_case(db, user, case_id)
    if payload.outcome not in {"found_safe", "found_deceased"}:
        raise HTTPException(status_code=400, detail="outcome must be found_safe or found_deceased")

    previous = case.status
    entry = mp_service.record_safe_report(
        db,
        case,
        reported_by_name=payload.reported_by_name,
        reported_by_contact=payload.reported_by_contact,
        reported_by_relationship=payload.reported_by_relationship,
        notes=payload.notes,
        verified=True,
        user_id=user.id,
        new_status=payload.outcome,
    )
    db.refresh(case)

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "safe_report",
        "missing_person_case",
        str(case.id),
        details={"outcome": payload.outcome, "from": previous},
    )
    if case.reporter_email:
        background_tasks.add_task(
            mp_email.send_case_status_notification, case, previous_status=previous
        )
    return mp_schemas.SafeReportAccepted(
        case_reference=case.case_reference,
        update_id=str(entry.id),
        case_status=case.status,
        verified=True,
        message=f"Case {case.case_reference} marked {case.status.replace('_', ' ')}",
    )
