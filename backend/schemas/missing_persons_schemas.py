"""Pydantic schemas for the missing-person API (MP).

Kept in their own module rather than in `schemas/schemas.py` (which is already
2.8k lines) following the precedent set by `enhancements_schemas.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

class DisasterEventCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    event_type: str = Field(..., max_length=64)
    affected_areas: List[str] = Field(default_factory=list)
    starts_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ends_at: Optional[datetime] = None
    notes: Optional[str] = None


class DisasterEventResponse(DisasterEventCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: str
    created_at: Optional[datetime] = None


class LocatedPersonCreate(BaseModel):
    disaster_event_id: Optional[UUID] = None
    status: str = Field("identity_unknown")
    full_name: Optional[str] = Field(None, max_length=255)
    approximate_age: Optional[int] = Field(None, ge=0, le=130)
    gender: Optional[str] = Field(None, max_length=32)
    found_location: Optional[str] = Field(None, max_length=512)
    found_at: Optional[datetime] = None
    facility_name: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None


class PossibleMatchResponse(BaseModel):
    id: str
    located_person_id: str
    case_id: str
    case_reference: str
    full_name: str
    confidence: float
    match_reasons: List[str] = Field(default_factory=list)
    status: str
    created_at: Optional[datetime] = None


class LocatedPersonResponse(LocatedPersonCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    record_reference: str
    photo_url: Optional[str] = None
    created_at: Optional[datetime] = None
    possible_matches: List[PossibleMatchResponse] = Field(default_factory=list)


class PossibleMatchReview(BaseModel):
    accept: bool
    notes: Optional[str] = None
    confirmed_case_status: str = Field("located")


class MissingPersonBulkImportResult(BaseModel):
    imported: int
    failed: int
    errors: List[Dict[str, Any]] = Field(default_factory=list)


# ─── Cases ──────────────────────────────────────────────────────────────────


class MissingPersonCaseBase(BaseModel):
    """Identifying detail about the missing person."""

    full_name: str = Field(..., min_length=2, max_length=255)
    nickname: Optional[str] = Field(None, max_length=120)
    age: Optional[int] = Field(None, ge=0, le=130)
    date_of_birth: Optional[datetime] = None
    gender: Optional[str] = Field(None, max_length=32)

    height_cm: Optional[float] = Field(None, ge=20, le=280)
    weight_kg: Optional[float] = Field(None, ge=1, le=500)
    build: Optional[str] = Field(None, max_length=64)
    hair_color: Optional[str] = Field(None, max_length=64)
    eye_color: Optional[str] = Field(None, max_length=64)
    complexion: Optional[str] = Field(None, max_length=64)
    distinguishing_marks: Optional[str] = None
    clothing_description: Optional[str] = None
    medical_notes: Optional[str] = None
    languages_spoken: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None

    last_seen_location: Optional[str] = Field(None, max_length=512)
    last_seen_latitude: Optional[float] = Field(None, ge=-90, le=90)
    last_seen_longitude: Optional[float] = Field(None, ge=-180, le=180)
    last_seen_at: Optional[datetime] = None
    last_seen_wearing: Optional[str] = None


class MissingPersonCaseCreate(MissingPersonCaseBase):
    disaster_event_id: Optional[UUID] = None
    priority: str = "medium"
    is_public: bool = False
    external_reference: Optional[str] = Field(None, max_length=128)

    reporter_name: Optional[str] = Field(None, max_length=255)
    reporter_email: Optional[EmailStr] = None
    reporter_phone: Optional[str] = Field(None, max_length=64)
    reporter_relationship: Optional[str] = Field(None, max_length=120)
    reporter_consent_given: bool = False


class PublicMissingPersonReport(MissingPersonCaseBase):
    """A case raised from the public reporting form.

    The reporter's contact details and an explicit consent tick are mandatory
    here: an anonymous, unverifiable missing-person report with no way to
    reach the reporter is not actionable, and publishing someone's photo
    needs a lawful basis on record.
    """

    reporter_name: str = Field(..., min_length=2, max_length=255)
    reporter_email: EmailStr
    reporter_phone: Optional[str] = Field(None, max_length=64)
    reporter_relationship: str = Field(..., min_length=2, max_length=120)
    reporter_consent_given: bool = Field(
        ..., description="Reporter confirms they may share this person's details"
    )


class MissingPersonCaseUpdateRequest(BaseModel):
    disaster_event_id: Optional[UUID] = None
    full_name: Optional[str] = Field(None, min_length=2, max_length=255)
    nickname: Optional[str] = Field(None, max_length=120)
    age: Optional[int] = Field(None, ge=0, le=130)
    date_of_birth: Optional[datetime] = None
    gender: Optional[str] = Field(None, max_length=32)
    height_cm: Optional[float] = Field(None, ge=20, le=280)
    weight_kg: Optional[float] = Field(None, ge=1, le=500)
    build: Optional[str] = Field(None, max_length=64)
    hair_color: Optional[str] = Field(None, max_length=64)
    eye_color: Optional[str] = Field(None, max_length=64)
    complexion: Optional[str] = Field(None, max_length=64)
    distinguishing_marks: Optional[str] = None
    clothing_description: Optional[str] = None
    medical_notes: Optional[str] = None
    languages_spoken: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    last_seen_location: Optional[str] = Field(None, max_length=512)
    last_seen_latitude: Optional[float] = Field(None, ge=-90, le=90)
    last_seen_longitude: Optional[float] = Field(None, ge=-180, le=180)
    last_seen_at: Optional[datetime] = None
    last_seen_wearing: Optional[str] = None
    priority: Optional[str] = None
    is_public: Optional[bool] = None
    external_reference: Optional[str] = Field(None, max_length=128)
    reporter_name: Optional[str] = Field(None, max_length=255)
    reporter_email: Optional[EmailStr] = None
    reporter_phone: Optional[str] = Field(None, max_length=64)
    reporter_relationship: Optional[str] = Field(None, max_length=120)


class CaseStatusChange(BaseModel):
    status: str = Field(..., description="open | found_safe | found_deceased | closed | withdrawn")
    notes: Optional[str] = None


class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: Optional[str] = None
    submission_id: Optional[str] = None
    file_kind: str
    file_url: str
    original_filename: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    checksum_sha256: Optional[str] = None
    captured_at: Optional[datetime] = None
    capture_location: Optional[str] = None
    face_indexed: bool = False
    face_match_score: Optional[float] = None
    processing_notes: Optional[str] = None
    created_at: Optional[datetime] = None


class SubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: Optional[str] = None
    case_reference: Optional[str] = None
    source: str
    submission_type: str
    submitter_name: Optional[str] = None
    submitter_email: Optional[str] = None
    submitter_phone: Optional[str] = None
    submitter_relationship: Optional[str] = None
    is_anonymous: bool = False
    subject: Optional[str] = None
    message: Optional[str] = None
    sighting_location: Optional[str] = None
    sighting_latitude: Optional[float] = None
    sighting_longitude: Optional[float] = None
    sighting_at: Optional[datetime] = None
    email_from: Optional[str] = None
    match_method: str = "unmatched"
    match_confidence: float = 0.0
    match_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "new"
    review_notes: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    attachments: List[AttachmentResponse] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class CaseUpdateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_id: str
    submission_id: Optional[str] = None
    update_type: str
    previous_status: Optional[str] = None
    new_status: Optional[str] = None
    notes: Optional[str] = None
    reported_by_name: Optional[str] = None
    reported_by_contact: Optional[str] = None
    reported_by_relationship: Optional[str] = None
    is_verified: bool = False
    verified_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class MissingPersonCaseResponse(MissingPersonCaseBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    case_reference: str
    visitor_id: Optional[str] = None
    disaster_event_id: Optional[str] = None
    status: str
    priority: str
    is_public: bool = False
    external_reference: Optional[str] = None
    reporter_name: Optional[str] = None
    reporter_email: Optional[str] = None
    reporter_phone: Optional[str] = None
    reporter_relationship: Optional[str] = None
    reporter_consent_given: bool = False
    resolved_at: Optional[datetime] = None
    resolution_notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Counts so a list view does not need N follow-up requests.
    submission_count: int = 0
    attachment_count: int = 0
    reference_photo_count: int = 0
    pending_safe_reports: int = 0
    # How to send more information about this case.
    intake_email: Optional[str] = None
    tip_url: Optional[str] = None


class MissingPersonCaseDetail(MissingPersonCaseResponse):
    submissions: List[SubmissionResponse] = Field(default_factory=list)
    attachments: List[AttachmentResponse] = Field(default_factory=list)
    timeline: List[CaseUpdateResponse] = Field(default_factory=list)


class CaseListResponse(BaseModel):
    items: List[MissingPersonCaseResponse]
    total: int
    limit: int
    offset: int


class PublicCaseSummary(BaseModel):
    """The reduced view safe to show on a public appeal page.

    Deliberately omits reporter contact details, medical notes, and the
    internal case metadata.
    """

    model_config = ConfigDict(from_attributes=True)

    case_reference: str
    full_name: str
    nickname: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    height_cm: Optional[float] = None
    build: Optional[str] = None
    hair_color: Optional[str] = None
    eye_color: Optional[str] = None
    distinguishing_marks: Optional[str] = None
    clothing_description: Optional[str] = None
    last_seen_location: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    last_seen_wearing: Optional[str] = None
    description: Optional[str] = None
    status: str
    photo_urls: List[str] = Field(default_factory=list)


# ─── Submissions ────────────────────────────────────────────────────────────


class SubmissionCreate(BaseModel):
    """A tip/evidence submission posted as JSON (files go to the multipart route)."""

    case_id: Optional[UUID] = None
    case_reference: Optional[str] = Field(None, max_length=32)
    intake_token: Optional[str] = Field(None, max_length=64)
    person_name: Optional[str] = Field(
        None, max_length=255, description="Used to route the tip when no case reference is known"
    )

    submission_type: str = "information"
    submitter_name: Optional[str] = Field(None, max_length=255)
    submitter_email: Optional[EmailStr] = None
    submitter_phone: Optional[str] = Field(None, max_length=64)
    submitter_relationship: Optional[str] = Field(None, max_length=120)
    is_anonymous: bool = False

    subject: Optional[str] = Field(None, max_length=512)
    message: Optional[str] = None
    sighting_location: Optional[str] = Field(None, max_length=512)
    sighting_latitude: Optional[float] = Field(None, ge=-90, le=90)
    sighting_longitude: Optional[float] = Field(None, ge=-180, le=180)
    sighting_at: Optional[datetime] = None


class SubmissionReview(BaseModel):
    status: Optional[str] = Field(None, description="new | triage | reviewing | verified | rejected | duplicate")
    review_notes: Optional[str] = None


class SubmissionAssign(BaseModel):
    case_id: UUID
    notes: Optional[str] = None


class SubmissionListResponse(BaseModel):
    items: List[SubmissionResponse]
    total: int
    limit: int
    offset: int


class SubmissionAccepted(BaseModel):
    """What a submitter gets back — enough to follow up, nothing more."""

    submission_id: str
    case_reference: Optional[str] = None
    matched: bool
    match_method: str
    match_confidence: float
    attachments_received: int = 0
    duplicate_attachments: int = 0
    reply_to: Optional[str] = None
    message: str


# ─── Safe / found reports ───────────────────────────────────────────────────


class SafeReportRequest(BaseModel):
    """"I am safe" / "we found them" report.

    Either ``case_reference`` or ``intake_token`` identifies the case on the
    public route; the authenticated route takes the case id in the path.
    """

    case_reference: Optional[str] = Field(None, max_length=32)
    intake_token: Optional[str] = Field(None, max_length=64)
    reported_by_name: Optional[str] = Field(None, max_length=255)
    reported_by_contact: Optional[str] = Field(None, max_length=255)
    reported_by_relationship: Optional[str] = Field(None, max_length=120)
    outcome: str = Field("found_safe", description="found_safe | found_deceased")
    notes: Optional[str] = None


class SafeReportAccepted(BaseModel):
    case_reference: str
    update_id: str
    case_status: str
    verified: bool
    message: str


class SafeReportVerification(BaseModel):
    accept: bool = True
    notes: Optional[str] = None


# ─── Email intake ───────────────────────────────────────────────────────────


class EmailIntakeRequest(BaseModel):
    """Inbound email posted by the mail provider's webhook.

    Extra keys are allowed on purpose — every provider ships its own envelope
    fields, and `missing_person_email_service.parse_inbound_payload` reads
    whichever shape arrived.
    """

    model_config = ConfigDict(extra="allow")

    organization_id: Optional[UUID] = Field(
        None, description="Target tenant; falls back to MP_DEFAULT_ORG_ID when omitted"
    )


class EmailIntakeResult(BaseModel):
    submission_id: str
    case_reference: Optional[str] = None
    matched: bool
    match_method: str
    match_confidence: float
    attachments_stored: int = 0
    acknowledgement_sent: bool = False


# ─── Stats ──────────────────────────────────────────────────────────────────


class MissingPersonStats(BaseModel):
    total_cases: int
    open_cases: int
    found_safe: int
    critical_cases: int
    total_submissions: int
    untriaged_submissions: int
    pending_safe_reports: int
