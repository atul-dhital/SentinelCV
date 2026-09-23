from pydantic import BaseModel, ConfigDict, EmailStr, Field, TypeAdapter, field_validator, model_validator
from typing import Optional, List, Dict, Any, Annotated
from datetime import datetime
from uuid import UUID
from pydantic.functional_serializers import PlainSerializer
from pydantic.functional_validators import BeforeValidator
from enum import Enum
import re


def _coerce_uuid(v: Any) -> UUID:
    """Accept both str and UUID, always return UUID object."""
    if isinstance(v, UUID):
        return v
    if isinstance(v, str):
        return UUID(v)
    raise ValueError(f"Cannot convert {type(v)} to UUID")


# A UUID type that handles both str (from SQLite) and UUID (from PostgreSQL)
# and always serializes to string in JSON responses.
FlexUUID = Annotated[
    UUID,
    BeforeValidator(_coerce_uuid),
    PlainSerializer(lambda v: str(v), return_type=str),
]


# ─── Organization Schemas ─────────────────────────────────────────────────────


class OrganizationBase(BaseModel):
    name: str


class OrganizationCreate(OrganizationBase):
    pass


class OrganizationUpdate(BaseModel):
    name: str | None = None
    face_confidence_threshold: float | None = None
    log_retention_days: int | None = None
    notification_email: bool | None = None
    notification_unidentified: bool | None = None
    notification_email_address: str | None = None
    settings: Dict[str, Any] | None = None


class Organization(OrganizationBase):
    id: FlexUUID
    face_confidence_threshold: float
    log_retention_days: int
    notification_email: bool
    notification_unidentified: bool
    notification_email_address: str | None = None
    settings: Dict[str, Any] | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class OrganizationStats(BaseModel):
    user_count: int
    visitor_count: int
    known_visitor_count: int
    total_logs: int
    identified_logs: int
    unidentified_logs: int
    embedding_count: int
    camera_count: int = 0


# ─── Shared Validators ───────────────────────────────────────────────────────


def _validate_password_strength(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[0-9]", v):
        raise ValueError("Password must contain at least one number")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-]", v):
        raise ValueError("Password must contain at least one special character")
    return v


# ─── User Schemas ─────────────────────────────────────────────────────────────


class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    role: str = "staff"


class UserCreate(UserBase):
    password: str
    organization_id: Optional[UUID] = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_password_strength(v)


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: str | None = None
    is_active: bool | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        return _validate_password_strength(v)


class User(UserBase):
    id: FlexUUID
    organization_id: FlexUUID
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserWithOrg(BaseModel):
    id: FlexUUID
    email: str
    full_name: str
    role: str
    organization_id: FlexUUID
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserSession(BaseModel):
    jti: Optional[str]
    ip_address: Optional[str]
    user_agent: Optional[str]
    created_at: Optional[datetime]
    last_used_at: Optional[datetime]
    expires_at: datetime
    is_current: bool = False

    model_config = ConfigDict(from_attributes=True)


# ─── Auth Schemas ─────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_login_email(cls, v: str) -> str:
        email = (v or "").strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise ValueError("Invalid email address")
        return email


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str
    password: str
    organization_name: str = Field(..., min_length=2, max_length=100)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_password_strength(v)


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: Optional[str] = None


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


class TokenData(BaseModel):
    user_id: str | None = None
    email: str | None = None


# ─── Visitor Schemas ──────────────────────────────────────────────────────────


# Reusable RFC-compliant email validator (without forcing fields to be EmailStr,
# which would make them required-non-null).
_EMAIL_ADAPTER = TypeAdapter(EmailStr)


class VisitorBase(BaseModel):
    model_config = {"populate_by_name": True}

    name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=254)
    phone: Optional[str] = Field(default=None, max_length=50)
    description: Optional[str] = Field(default=None, max_length=2000)
    notes: Optional[str] = Field(default=None, max_length=5000)
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, validation_alias="visitor_metadata"
    )
    is_known: bool = False
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def _validate_email_format(cls, v: Optional[str]) -> Optional[str]:
        # Email stays optional (detection-created visitors have none), but when
        # a value is supplied it must be a real address — not free text.
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            return None
        _EMAIL_ADAPTER.validate_python(stripped)
        return stripped


class VisitorCreate(VisitorBase):
    organization_id: Optional[FlexUUID] = None


class VisitorUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, validation_alias="visitor_metadata"
    )
    is_known: Optional[bool] = None
    is_active: Optional[bool] = None


class Visitor(VisitorBase):
    id: FlexUUID
    organization_id: FlexUUID
    created_at: datetime
    updated_at: datetime | None = None
    primary_face_image_url: Optional[str] = None
    face_count: int = 0

    model_config = ConfigDict(from_attributes=True)

class VisitorDetail(Visitor):
    """Visitor with face data included."""
    face_data: List["FaceData"] = []
    log_count: int = 0


# ─── Face Data Schemas ────────────────────────────────────────────────────────


class FaceAngle(str, Enum):
    FRONTAL = "frontal"
    ANGLE_45_LEFT = "45_left"
    ANGLE_45_RIGHT = "45_right"
    PROFILE = "profile"
    TOP = "top"


class FaceDataBase(BaseModel):
    image_url: Optional[str] = None
    quality_score: float = 0.0
    face_angle: Optional[FaceAngle] = None
    is_primary: bool = False


class FaceDataCreate(FaceDataBase):
    visitor_id: UUID
    embedding: List[float]


class FaceData(FaceDataBase):
    id: FlexUUID
    visitor_id: FlexUUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class FaceDataWithEmbedding(FaceData):
    embedding: List[float]


# ─── Camera Schemas ───────────────────────────────────────────────────────────


class CameraBase(BaseModel):
    name: str
    rtsp_url: Optional[str] = None
    location: Optional[str] = None


class CameraCreate(CameraBase):
    pass


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    rtsp_url: Optional[str] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None


class Camera(CameraBase):
    id: FlexUUID
    organization_id: FlexUUID
    is_active: bool
    status: str
    last_seen: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─── Edge Device Schemas ────────────────────────────────────────────────────


class EdgeDeviceBase(BaseModel):
    name: str
    device_type: str = "jetson"
    location: Optional[str] = None
    endpoint_url: Optional[str] = None
    ip_address: Optional[str] = None
    serial_number: Optional[str] = None
    hardware_info: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    model_version_id: Optional[FlexUUID] = None
    model_artifact_path: Optional[str] = None
    device_config: Optional[Dict[str, Any]] = None


class EdgeDeviceCreate(EdgeDeviceBase):
    pass


class EdgeDeviceUpdate(BaseModel):
    name: Optional[str] = None
    device_type: Optional[str] = None
    location: Optional[str] = None
    endpoint_url: Optional[str] = None
    ip_address: Optional[str] = None
    serial_number: Optional[str] = None
    hardware_info: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    model_version_id: Optional[FlexUUID] = None
    model_artifact_path: Optional[str] = None
    device_config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None
    status: Optional[str] = None


class EdgeDevice(EdgeDeviceBase):
    id: FlexUUID
    organization_id: FlexUUID
    status: str
    is_active: bool
    token_prefix: str
    last_seen: Optional[datetime] = None
    last_metrics: Dict[str, Any] = Field(default_factory=dict)
    last_sync_at: Optional[datetime] = None
    last_sync_count: int = 0
    last_sync_status: str = "never"
    last_export_at: Optional[datetime] = None
    last_export_status: Optional[str] = None
    last_export_path: Optional[str] = None
    last_export_details: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class EdgeDeviceTokenResponse(BaseModel):
    device: EdgeDevice
    device_token: str


class EdgeDeviceHeartbeatRequest(BaseModel):
    status: Optional[str] = None
    ip_address: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None
    model_version_id: Optional[FlexUUID] = None


class EdgeDeviceEmbeddingItem(BaseModel):
    visitor_id: FlexUUID
    visitor_name: Optional[str] = None
    visitor_known: bool
    face_data_id: FlexUUID
    embedding: List[float]
    image_url: Optional[str] = None
    quality_score: float = 0.0
    is_primary: bool = False
    created_at: datetime


class EdgeDeviceSyncRequest(BaseModel):
    since: Optional[datetime] = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=1, le=2000)


class EdgeDeviceSyncResponse(BaseModel):
    device_id: FlexUUID
    synced_at: datetime
    since: Optional[datetime] = None
    count: int
    next_offset: Optional[int] = None
    items: List[EdgeDeviceEmbeddingItem]


class EdgeDeviceEventCreate(BaseModel):
    event_type: str = "alert"
    severity: str = "info"
    title: str
    message: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class EdgeDeviceEventResponse(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    edge_device_id: FlexUUID
    event_type: str
    severity: str
    title: str
    message: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EdgeDeviceExportRequest(BaseModel):
    model_path: str
    input_shape: List[int] = Field(default_factory=lambda: [1, 3, 224, 224])
    output_path: Optional[str] = None
    model_name: Optional[str] = None
    opset_version: int = 13

# ─── Visitor Log Schemas ──────────────────────────────────────────────────────


class VisitorLogBase(BaseModel):
    face_image_path: Optional[str] = None
    video_snippet_path: Optional[str] = None
    confidence: float = 0.0
    status: str = "detected"
    identified: bool = False


class VisitorLogCreate(VisitorLogBase):
    organization_id: UUID
    visitor_id: Optional[UUID] = None
    camera_id: Optional[UUID] = None
    face_data_id: Optional[UUID] = None
    track_id: Optional[int] = None
    source_video: Optional[str] = None


class VisitorLog(VisitorLogBase):
    id: FlexUUID
    organization_id: FlexUUID
    visitor_id: Optional[FlexUUID] = None
    camera_id: Optional[FlexUUID] = None
    face_data_id: Optional[FlexUUID] = None
    timestamp: datetime
    track_id: Optional[int] = None
    source_video: Optional[str] = None
    visitor_name: Optional[str] = None
    visitor_image_url: Optional[str] = None
    visitor_known: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)

class VisitorLogDetail(VisitorLog):
    """Log entry with visitor info."""
    visitor: Optional[Visitor] = None
    camera: Optional[Camera] = None


class VisitorMediaUploadResult(BaseModel):
    visitor_id: UUID
    images_added: int = 0
    video_frames_added: int = 0
    video_url: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    message: str = "Media processed successfully"


# ─── Audit Log Schemas ────────────────────────────────────────────────────────


class AuditLogBase(BaseModel):
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class AuditLog(AuditLogBase):
    id: FlexUUID
    organization_id: FlexUUID
    user_id: Optional[FlexUUID] = None
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)

# ─── Search & Embedding Schemas ───────────────────────────────────────────────


class EmbeddingSearchRequest(BaseModel):
    organization_id: UUID
    embedding: List[float]
    threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    angle: Optional[str] = None

    @field_validator("embedding")
    @classmethod
    def validate_embedding(cls, v: List[float]) -> List[float]:
        if not v:
            raise ValueError("embedding must not be empty")
        if len(v) > 2048:
            raise ValueError("embedding exceeds maximum allowed dimensions (2048)")
        return v


class EmbeddingSearchResult(BaseModel):
    visitor: Optional[Visitor] = None
    confidence: float = 0.0
    matched: bool = False
    face_data_id: Optional[UUID] = None
    angle_scores: Optional[Dict[str, Any]] = None


# ─── Log Assignment / Review ──────────────────────────────────────────────────


class LogAssignRequest(BaseModel):
    visitor_id: UUID
    propagate_similar: bool = True
    similarity_threshold: float = Field(default=0.82, ge=0.0, le=1.0)
    lookback_days: int = Field(default=30, ge=1, le=365)
    max_candidates: int = Field(default=500, ge=50, le=5000)


class LogCreateVisitorRequest(BaseModel):
    """Create a new visitor from an unidentified log entry."""
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


# ─── Dashboard Stats ─────────────────────────────────────────────────────────


class DashboardStats(BaseModel):
    identified_count: int
    unidentified_count: int
    total_events: int
    total_visitors: int
    pending_review: int = 0
    cameras_online: int = 0


# ─── Video Processing ────────────────────────────────────────────────────────


class VideoProcessRequest(BaseModel):
    organization_id: UUID
    video_path: str


class VideoProcessStatus(BaseModel):
    status: str
    message: str
    task_id: Optional[str] = None


# ─── Pagination ──────────────────────────────────────────────────────────────


class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    limit: int
    pages: int
    # Cursor for the next page (ISO timestamp of the last item).
    # Present when cursor-based pagination is used; None otherwise.
    next_cursor: Optional[str] = None


# ─── Password Reset ──────────────────────────────────────────────────────────


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one number")
        return v


# ─── Video Processing Job ────────────────────────────────────────────────────


class VideoProcessingJobResponse(BaseModel):
    id: FlexUUID
    organization_id: Optional[FlexUUID] = None
    file_id: str
    file_path: str
    status: str
    message: Optional[str] = None
    people_detected: int = 0
    people_identified: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

# ─── Bulk Import ─────────────────────────────────────────────────────────────


class BulkImportError(BaseModel):
    row: int
    error: str


class BulkImportResult(BaseModel):
    total: int
    created: int
    face_enrolled: int = 0
    errors: List[BulkImportError]


# ─── Log Confirm ─────────────────────────────────────────────────────────────


class LogConfirmRequest(BaseModel):
    confirmed: bool = True
    visitor_id: Optional[UUID] = None


# ─── Camera Session Schemas ──────────────────────────────────────────────────


class StartSessionRequest(BaseModel):
    camera_id: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class CameraSessionResponse(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    user_id: FlexUUID
    camera_id: Optional[FlexUUID] = None
    status: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    total_frames: int = 0
    total_detections: int = 0
    total_identifications: int = 0
    settings: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)

class EndSessionResponse(BaseModel):
    id: FlexUUID
    status: str
    ended_at: datetime
    total_frames: int
    total_detections: int
    total_identifications: int

    model_config = ConfigDict(from_attributes=True)

class ProcessFrameRequest(BaseModel):
    session_id: str
    frame_data: str  # base64-encoded JPEG


class DetectionResult(BaseModel):
    bbox: Dict[str, Any]
    confidence: float
    identified: bool
    visitor_id: Optional[str] = None
    visitor_name: Optional[str] = None
    face_image_path: Optional[str] = None
    face_angle: Optional[str] = None


class PersonBox(BaseModel):
    bbox: Dict[str, Any]
    confidence: float = 0.0


class ProcessFrameResponse(BaseModel):
    detections: List[DetectionResult]
    persons: List[PersonBox] = []
    frame_number: int
    processing_time_ms: float
    ai_processing_time_ms: Optional[float] = None
    ai_roundtrip_time_ms: Optional[float] = None
    identification_time_ms: Optional[float] = None
    average_identification_time_ms: Optional[float] = None


class AnalyzedFrameResponse(BaseModel):
    frame_data: str  # base64-encoded JPEG
    width: int
    height: int
    detections: List[DetectionResult]


class DetectionLogResponse(BaseModel):
    id: FlexUUID
    session_id: FlexUUID
    visitor_id: Optional[FlexUUID] = None
    timestamp: datetime
    confidence: float
    bbox: Optional[Dict[str, Any]] = None
    face_image_path: Optional[str] = None
    identified: bool

    model_config = ConfigDict(from_attributes=True)

class ManualAssignRequest(BaseModel):
    detection_log_id: str
    visitor_id: str


# ─── S14: Training Data Schemas ──────────────────────────────────────────────


class ImageQualityResult(BaseModel):
    filename: str
    passed: bool
    width: int = 0
    height: int = 0
    issues: List[str] = []


class BatchUploadResult(BaseModel):
    total: int
    accepted: int
    rejected: int
    results: List[ImageQualityResult]


class TrainingStatsResponse(BaseModel):
    total_visitors: int
    visitors_with_faces: int
    visitors_without_faces: int
    total_face_images: int
    avg_images_per_visitor: float
    quality_distribution: Dict[str, int]  # high/medium/low counts


class AugmentationResult(BaseModel):
    original_count: int
    augmented_count: int
    total_count: int
    visitor_id: str


# ─── S15: Recommendation Schemas ─────────────────────────────────────────────


class Recommendation(BaseModel):
    type: str  # face_quality | low_accuracy | missing_visitor | threshold | threshold_tuning | best_practice | diversity | performance
    severity: str  # info | warning | critical
    title: str
    message: str
    entity_id: Optional[str] = None
    entity_type: Optional[str] = None
    entity_name: Optional[str] = None
    entity_image_url: Optional[str] = None
    action: Optional[str] = None


class RecommendationsResponse(BaseModel):
    recommendations: List[Recommendation]
    generated_at: datetime


# ─── S16: Accuracy Improvement Schemas ────────────────────────────────────────


class AdaptiveThresholdUpdate(BaseModel):
    custom_threshold: Optional[float] = None
    auto_learn: Optional[bool] = None


class LivenessConfig(BaseModel):
    """S29: Liveness Detection Configuration"""
    enabled: bool = True
    min_face_size: int = 80
    blink_detection: bool = False
    texture_analysis: bool = True
    # Detection methods
    texture_enabled: bool = True
    motion_enabled: bool = True
    deep_learning_enabled: bool = True
    # Thresholds
    overall_confidence_threshold: float = 0.7
    texture_score_threshold: float = 0.5
    motion_score_threshold: float = 0.5
    deep_learning_threshold: float = 0.6
    # Video requirements
    video_required: bool = True
    min_video_frames: int = 30  # ~1 second @ 30fps
    min_motion_frames: int = 10
    # Challenge-response
    challenge_enabled: bool = False
    challenge_types: List[str] = ["blink"]  # blink, head_turn, smile
    # Spoofing attack detection
    detect_print_attacks: bool = True
    detect_replay_attacks: bool = True
    detect_mask_attacks: bool = True
    # Advanced
    ensemble_method: str = "average"  # average, weighted, voting
    # Quality checks
    min_illumination_score: float = 0.3
    max_blur_score: float = 0.7
    max_noise_level: float = 0.5


class LivenessScoreResponse(BaseModel):
    """Response for a single liveness detection result"""
    id: str
    visitor_log_id: str
    is_live: bool
    overall_score: float
    rejection_reason: Optional[str] = None
    # Method scores
    texture_score: Optional[float] = None
    motion_score: Optional[float] = None
    deep_learning_score: Optional[float] = None
    # Video tracking
    video_duration_frames: Optional[int] = None
    has_sufficient_motion: Optional[bool] = None
    blink_count: Optional[int] = None
    # Spoofing indicators
    attack_indicators: Dict[str, float] = {}
    # Quality metrics
    face_size: Optional[int] = None
    illumination_score: Optional[float] = None
    blur_score: Optional[float] = None
    noise_level: Optional[float] = None
    # Challenge-response
    challenge_type: Optional[str] = None
    challenge_passed: Optional[bool] = None
    challenge_attempts: int = 0
    # Metadata
    method_used: str
    model_version: Optional[str] = None
    processing_time_ms: Optional[float] = None
    created_at: datetime


class LivenessScoreCreateRequest(BaseModel):
    """Request to create a liveness detection result"""
    visitor_log_id: str
    is_live: bool
    overall_score: float
    rejection_reason: Optional[str] = None
    texture_score: Optional[float] = None
    motion_score: Optional[float] = None
    deep_learning_score: Optional[float] = None
    video_duration_frames: Optional[int] = None
    has_sufficient_motion: Optional[bool] = None
    blink_count: Optional[int] = None
    attack_indicators: Dict[str, float] = {}
    face_size: Optional[int] = None
    illumination_score: Optional[float] = None
    blur_score: Optional[float] = None
    noise_level: Optional[float] = None
    challenge_type: Optional[str] = None
    challenge_passed: Optional[bool] = None
    challenge_attempts: int = 0
    method_used: str
    model_version: Optional[str] = None
    processing_time_ms: Optional[float] = None


class LivenessDetectionResult(BaseModel):
    """Result of liveness detection for a detection event"""
    is_live: bool
    score: float
    method: str  # texture, motion, deep_learning, ensemble
    details: Dict[str, Any] = {}
    quality_metrics: Dict[str, Any] = {}
    attack_detected: bool = False
    attack_type: Optional[str] = None


class LivenessDetectionRequest(BaseModel):
    """Request to perform liveness detection on a frame/video"""
    visitor_log_id: str
    video_path: Optional[str] = None  # Path to video file
    frame_data: Optional[str] = None  # Base64 encoded frame (if single frame)
    methods: List[str] = ["texture", "motion", "deep_learning"]  # Which methods to use
    require_challenge: bool = False
    challenge_type: Optional[str] = None


class LivenessStatistics(BaseModel):
    """Statistics about liveness detection results"""
    total_detections: int
    live_count: int
    spoof_count: int
    live_percentage: float
    average_liveness_score: float
    most_common_rejection_reason: Optional[str] = None
    attack_detection_rate: float
    average_processing_time_ms: float
    method_distribution: Dict[str, int] = {}


class LivenessReportItem(BaseModel):
    """Single item in liveness detection report"""
    timestamp: datetime
    visitor_name: Optional[str]
    is_live: bool
    score: float
    method: str
    rejection_reason: Optional[str] = None
    attack_detected: bool = False


class LivenessDetectionReport(BaseModel):
    """Comprehensive liveness detection report"""
    organization_id: str
    period_start: datetime
    period_end: datetime
    statistics: LivenessStatistics
    detections: List[LivenessReportItem]
    summary: str


class AccuracyStatsResponse(BaseModel):
    overall_accuracy: float
    total_identifications: int
    correct_identifications: int
    false_positives: int
    avg_confidence: float
    visitors_with_custom_threshold: int
    auto_learn_enabled_count: int


# ─── S17: Data Quality Schemas ────────────────────────────────────────────────


class DataQualityConfig(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    duplicate_similarity_threshold: float
    blur_threshold: float
    landmark_error_threshold: float
    min_image_quality_score: float
    demographic_balance_targets: Dict[str, Any]
    enable_duplicate_detection: bool
    enable_noise_detection: bool
    enable_demographic_analysis: bool
    auto_remediation_enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class DataQualityConfigUpdate(BaseModel):
    duplicate_similarity_threshold: float | None = None
    blur_threshold: float | None = None
    landmark_error_threshold: float | None = None
    min_image_quality_score: float | None = None
    demographic_balance_targets: Dict[str, Any] | None = None
    enable_duplicate_detection: bool | None = None
    enable_noise_detection: bool | None = None
    enable_demographic_analysis: bool | None = None
    auto_remediation_enabled: bool | None = None
    min_face_size_pixels: int | None = None
    min_brightness: float | None = None
    max_brightness: float | None = None


class MediaValidationResult(BaseModel):
    """US-FUT-022: Strict media validation results for uploads."""
    valid: bool
    issues: List[str] = Field(default_factory=list)
    blur_score: Optional[float] = None
    brightness: Optional[float] = None
    contrast: Optional[float] = None
    face_size_pixels: Optional[int] = None
    is_corrupt: bool = False
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None


class MediaValidationConfig(BaseModel):
    """US-FUT-022: Configuration for media validation during upload."""
    strict_mode: bool = True
    min_face_size_pixels: int = 100
    min_blur_threshold: float = 50.0
    min_brightness: float = 40.0
    max_brightness: float = 220.0
    min_contrast: float = 20.0
    check_corruption: bool = True
    check_duplicates: bool = True
    duplicate_hash_algorithm: str = "phash"


class DuplicateGroup(BaseModel):
    visitor_ids: List[str]
    visitor_names: List[str]
    similarity: float


class StaleDataItem(BaseModel):
    visitor_id: str
    visitor_name: Optional[str]
    last_detected: Optional[datetime]
    face_count: int
    days_stale: int


class QualityFinding(BaseModel):
    id: FlexUUID
    audit_job_id: FlexUUID
    finding_type: str
    severity: str
    image_id: str | None = None
    related_image_ids: List[str] = []
    confidence_score: float = 0.0
    details: Dict[str, Any] | None = None
    recommendation: str | None = None
    auto_remediation_applied: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class DataQualityAuditJob(BaseModel):
    id: FlexUUID
    config_id: FlexUUID
    organization_id: FlexUUID
    dataset_name: str
    dataset_source: str
    total_images: int
    status: str
    progress_percentage: float
    started_at: datetime | None = None
    completed_at: datetime | None = None
    uniqueness_score: float | None = None
    quality_score: float | None = None
    balance_score: float | None = None
    overall_health_score: float | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class DataQualityAuditJobDetailed(DataQualityAuditJob):
    findings: List[QualityFinding] = []
    report_data: Dict[str, Any] | None = None


class DataQualityReport(BaseModel):
    uniqueness_score: float
    quality_score: float
    balance_score: float
    overall_health_score: float
    duplicate_count: int
    low_quality_count: int
    total_issues: int
    last_audited_at: datetime | None = None


class QualityTrendItem(BaseModel):
    id: FlexUUID
    month_year: str
    average_uniqueness_score: float | None = None
    average_quality_score: float | None = None
    average_balance_score: float | None = None
    average_overall_health: float | None = None
    improvement_rate: float | None = None

    model_config = ConfigDict(from_attributes=True)

# ─── S17b: Synthetic Data Schemas ─────────────────────────────────────────────


class SyntheticDataConfig(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    gan_model: str
    output_resolution: int
    num_samples_per_batch: int
    diversity_threshold: float
    total_samples_target: int
    quality_threshold_fid: float
    quality_threshold_lpips: float
    quality_threshold_detection_confidence: float
    demographic_constraints: Dict[str, Any]
    enabled: bool
    auto_augment_training_data: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SyntheticDataConfigUpdate(BaseModel):
    gan_model: str | None = None
    output_resolution: int | None = None
    num_samples_per_batch: int | None = None
    diversity_threshold: float | None = None
    total_samples_target: int | None = None
    quality_threshold_fid: float | None = None
    quality_threshold_lpips: float | None = None
    demographic_constraints: Dict[str, Any] | None = None
    enabled: bool | None = None


class SynthesisJob(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    status: str
    total_target: int
    samples_generated: int
    samples_validated: int
    samples_rejected: int
    avg_fid: float | None = None
    avg_lpips: float | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

class GeneratedImage(BaseModel):
    id: FlexUUID
    job_id: FlexUUID
    file_path: str
    fid_score: float | None = None
    lpips_score: float | None = None
    demographic_attributes: Dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class QualityMetricsSynthetic(BaseModel):
    id: FlexUUID
    job_id: FlexUUID
    measurement_timestamp: datetime
    total_samples: int
    valid_samples: int
    acceptance_rate: float | None = None
    avg_fid: float | None = None
    avg_lpips: float | None = None
    demographic_distribution: Dict[str, Any]

    model_config = ConfigDict(from_attributes=True)

# ─── S21: Temporal Augmentation Schemas ───────────────────────────────────────


class TemporalAugmentationConfig(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    target_expressions: Dict[str, float]
    frames_per_transition: int
    fps: int
    interpolation_method: str
    min_expression_confidence: float
    optical_flow_smoothness_threshold: float
    output_resolution: str
    output_format: str
    compress_output: bool
    enabled: bool
    auto_augment: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TemporalAugmentationConfigUpdate(BaseModel):
    target_expressions: Dict[str, float] | None = None
    frames_per_transition: int | None = None
    fps: int | None = None
    interpolation_method: str | None = None
    min_expression_confidence: float | None = None
    optical_flow_smoothness_threshold: float | None = None
    output_resolution: str | None = None
    output_format: str | None = None
    compress_output: bool | None = None
    enabled: bool | None = None
    auto_augment: bool | None = None


class AugmentationJob(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    config_id: FlexUUID
    input_video_path: str | None = None
    input_face_id: str | None = None
    status: str
    error_message: str | None = None
    total_frames: int
    processed_frames: int
    generated_sequences: int
    avg_expression_confidence: float | None = None
    avg_optical_flow: float | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class GeneratedSequence(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    job_id: FlexUUID
    config_id: FlexUUID
    video_path: str
    file_size: int | None = None
    duration_seconds: float | None = None
    frame_count: int | None = None
    fps: int | None = None
    source_expression: str | None = None
    target_expression: str | None = None
    transition_type: str | None = None
    expression_confidence_target: float | None = None
    optical_flow_smoothness: float | None = None
    used_in_training: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ExpressionMetrics(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    job_id: FlexUUID
    measurement_timestamp: datetime
    expression_distribution: Dict[str, int]
    transition_distribution: Dict[str, int]
    avg_confidence: float | None = None
    acceptance_rate: float | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ─── S18: Analytics Schemas ──────────────────────────────────────────────────


class AccuracyDashboard(BaseModel):
    overall_accuracy: float
    daily_accuracy: List[Dict[str, Any]]  # [{date, accuracy, count}]
    confidence_distribution: Dict[str, int]  # {"0.6-0.7": 10, "0.7-0.8": 20, ...}
    top_misidentified: List[Dict[str, Any]]


class VisitorPatternAnalysis(BaseModel):
    peak_hours: List[Dict[str, Any]]  # [{hour, count}]
    daily_trends: List[Dict[str, Any]]  # [{date, total, identified, unidentified}]
    frequent_visitors: List[Dict[str, Any]]  # [{visitor_id, name, count}]
    avg_daily_visitors: float


class SystemHealthMetrics(BaseModel):
    ai_service_status: str
    avg_processing_time_ms: float
    total_processed_today: int
    error_rate: float
    storage_used_mb: float
    database_size_mb: float
    recognition_backend: Optional[str] = None
    recognition_degraded: Optional[bool] = None


class EmotionAnalyticsTimelinePoint(BaseModel):
    date: str
    total_events: int
    dominant_emotion: str
    avg_valence: float
    avg_arousal: float


class EmotionAnalyticsSummary(BaseModel):
    lookback_days: int
    since: str
    total_events: int
    dominant_emotion: str
    avg_valence: float
    avg_arousal: float
    emotion_distribution: Dict[str, float]
    emotion_counts: Dict[str, int]
    timeline: List[EmotionAnalyticsTimelinePoint]
    generated_at: str


class VisitorFlowTotals(BaseModel):
    total_events: int
    unique_visitors: int
    identified_events: int
    identified_rate: float


class VisitorFlowHourlyPoint(BaseModel):
    hour: str
    visitor_events: int


class VisitorFlowCameraDensityItem(BaseModel):
    camera_id: str
    camera_name: str
    events: int
    share: float


class VisitorFlowPeakCamera(BaseModel):
    camera_id: Optional[str]
    camera_name: Optional[str]
    events: int


class VisitorFlowDwellTime(BaseModel):
    median_seconds: float
    average_seconds: float
    sample_count: int


class VisitorFlowHeatmap(BaseModel):
    grid_size: List[int]
    raw_grid: List[List[int]]
    normalized_grid: List[List[float]]
    peak_cell_events: int


class VisitorFlowAnalytics(BaseModel):
    lookback_hours: int
    since: str
    totals: VisitorFlowTotals
    hourly_timeline: List[VisitorFlowHourlyPoint]
    camera_density: List[VisitorFlowCameraDensityItem]
    peak_camera: VisitorFlowPeakCamera
    dwell_time: VisitorFlowDwellTime
    heatmap: VisitorFlowHeatmap
    generated_at: str


class ReportRequest(BaseModel):
    report_type: str = "comprehensive"  # comprehensive | accuracy | visitors | activity
    format: str = "json"  # json | csv | pdf
    period: str = "weekly"  # daily | weekly | monthly
    date_from: Optional[str] = None
    date_to: Optional[str] = None


# ─── S19: Webhook & API Key Schemas ──────────────────────────────────────────


class WebhookCreate(BaseModel):
    url: str
    secret: Optional[str] = None
    events: List[str] = []
    is_active: bool = True


class WebhookUpdate(BaseModel):
    url: Optional[str] = None
    secret: Optional[str] = None
    events: Optional[List[str]] = None
    is_active: Optional[bool] = None


class WebhookResponse(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    url: str
    events: List[str]
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class WebhookLogResponse(BaseModel):
    id: FlexUUID
    webhook_id: FlexUUID
    event: str
    payload: Dict[str, Any]
    response_status: Optional[int]
    success: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ApiKeyCreate(BaseModel):
    name: str
    permissions: List[str] = ["read"]
    expires_at: Optional[datetime] = None


class ApiKeyResponse(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    name: str
    key_prefix: str
    permissions: List[str]
    is_active: bool
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ApiKeyCreatedResponse(ApiKeyResponse):
    """Returned only on creation — includes full key."""
    full_key: str


# ─── S20: Compliance Schemas ─────────────────────────────────────────────────


class EncryptionVerification(BaseModel):
    encryption_enabled: bool
    total_embeddings: int
    encrypted_count: int
    unencrypted_count: int
    verification_status: str  # passed | warning | failed


class RetentionPolicyCreate(BaseModel):
    entity_type: str
    retention_days: int
    auto_delete: bool = False
    action: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_action_to_auto_delete(cls, values):
        """Accept frontend's {action: 'auto_delete'} and map to auto_delete=True."""
        if isinstance(values, dict) and "action" in values:
            action = values.get("action")
            if action == "auto_delete":
                values.setdefault("auto_delete", True)
        return values


class RetentionPolicyResponse(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    entity_type: str
    retention_days: int
    auto_delete: bool
    last_cleanup_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class RetentionCleanupResult(BaseModel):
    entity_type: str
    records_deleted: int
    cutoff_date: datetime


class GdprExportResponse(BaseModel):
    visitor_id: str
    data: Dict[str, Any]
    exported_at: datetime


class GdprDeleteResponse(BaseModel):
    visitor_id: str
    records_deleted: Dict[str, int]
    deleted_at: datetime


# ─── S21: Camera Group Schemas ───────────────────────────────────────────────


class CameraGroupCreate(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = None


class CameraGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None


class CameraGroupResponse(BaseModel):
    id: FlexUUID
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    camera_count: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class CameraHealthResponse(BaseModel):
    camera_id: FlexUUID
    camera_name: str
    status: str
    uptime_percent: float = 0.0
    last_active: Optional[datetime] = None
    frame_rate: Optional[float] = None
    error_count: int = 0


# ─── S22: Notification Schemas ───────────────────────────────────────────────


class NotificationCreate(BaseModel):
    organization_id: UUID
    user_id: Optional[UUID] = None
    title: str
    message: Optional[str] = None
    notification_type: str = "info"
    link: Optional[str] = None


class NotificationResponse(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    user_id: Optional[FlexUUID]
    title: str
    message: Optional[str]
    notification_type: str
    is_read: bool
    link: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class NotificationPreferences(BaseModel):
    browser_push: bool = True
    email_alerts: bool = True
    unidentified_alerts: bool = True
    system_alerts: bool = True


# ─── S26: Future Enhancement Schemas ─────────────────────────────────────────


class FutureEnhancementCreate(BaseModel):
    story_id: str
    category: str
    title: str
    description: Optional[str] = None
    status: str = "planned"
    priority: str = "medium"
    config: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, Any]] = None
    roadmap_phase: Optional[str] = None
    enabled: bool = False


class FutureEnhancementUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, Any]] = None
    roadmap_phase: Optional[str] = None
    enabled: Optional[bool] = None


class FutureEnhancementResponse(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    story_id: str
    category: str
    title: str
    description: Optional[str] = None
    status: str
    priority: str
    config: Optional[Dict[str, Any]] = None
    metrics: Optional[Dict[str, Any]] = None
    roadmap_phase: Optional[str] = None
    enabled: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class RateLimitRuleCreate(BaseModel):
    endpoint_pattern: str = "*"
    max_requests: int = 1000
    window_seconds: int = 3600
    is_active: bool = True
    burst_limit: Optional[int] = None
    burst_window_seconds: Optional[int] = None
    cooldown_seconds: int = 0
    priority: int = 0
    description: Optional[str] = None


class RateLimitRuleUpdate(BaseModel):
    endpoint_pattern: Optional[str] = None
    max_requests: Optional[int] = None
    window_seconds: Optional[int] = None
    is_active: Optional[bool] = None
    burst_limit: Optional[int] = None
    burst_window_seconds: Optional[int] = None
    burst_current_count: Optional[int] = None
    burst_window_start: Optional[datetime] = None
    cooldown_seconds: Optional[int] = None
    priority: Optional[int] = None
    description: Optional[str] = None


class RateLimitRuleResponse(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    endpoint_pattern: str
    max_requests: int
    window_seconds: int
    current_count: int
    window_start: Optional[datetime] = None
    is_active: bool
    burst_limit: Optional[int] = None
    burst_window_seconds: Optional[int] = None
    burst_current_count: int = 0
    burst_window_start: Optional[datetime] = None
    cooldown_seconds: int = 0
    priority: int = 0
    description: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class CarbonMetricsCreate(BaseModel):
    period_start: datetime
    period_end: datetime
    gpu_hours: float = 0.0
    cpu_hours: float = 0.0
    estimated_kwh: float = 0.0
    estimated_co2_kg: float = 0.0
    training_runs: int = 0
    inference_count: int = 0
    optimization_notes: Optional[str] = None


class CarbonMetricsResponse(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    period_start: datetime
    period_end: datetime
    gpu_hours: float
    cpu_hours: float
    estimated_kwh: float
    estimated_co2_kg: float
    training_runs: int
    inference_count: int
    optimization_notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class CarbonMetricsSummary(BaseModel):
    total_gpu_hours: float
    total_cpu_hours: float
    total_kwh: float
    total_co2_kg: float
    total_training_runs: int
    total_inference_count: int
    efficiency_score: float  # 0-100
    monthly_trend: List[Dict[str, Any]]


class RoadmapPhase(BaseModel):
    phase: str  # short_term | medium_term | long_term
    title: str
    description: str
    enhancements: List[FutureEnhancementResponse]
    progress_percent: float


class RoadmapResponse(BaseModel):
    phases: List[RoadmapPhase]
    total_enhancements: int
    enabled_count: int
    completion_percent: float


class BiasAuditResult(BaseModel):
    overall_fairness_score: float
    demographic_parity: Dict[str, Any]
    equal_opportunity: Dict[str, Any]
    recommendations: List[str]
    audited_at: datetime


class BiasAuditRecordResponse(BaseModel):
    """US-FUT-012: Persisted bias audit record response."""
    id: FlexUUID
    organization_id: FlexUUID
    overall_fairness_score: float
    demographic_parity_status: str
    equal_opportunity_status: str
    identification_rate: float
    parity_gap: float
    gender_distribution: Dict[str, int]
    age_group_distribution: Dict[str, int]
    recommendations: List[str]
    audit_details: Dict[str, Any]
    total_visitors: int
    total_logs: int
    audited_by: Optional[FlexUUID] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BiasAuditHistoryResponse(BaseModel):
    """US-FUT-012: List of bias audit records with pagination."""
    items: List[BiasAuditRecordResponse]
    total: int
    page: int
    limit: int
    pages: int


# ─── US-FUT-028: Consent Management Schemas ──────────────────────────────────


class ConsentRecordCreate(BaseModel):
    subject_type: str  # visitor | user
    subject_id: Optional[FlexUUID] = None
    user_id: Optional[FlexUUID] = None
    consent_type: str  # data_processing | marketing | biometrics | third_party_sharing
    consent_version: str = "1.0"
    consent_source: str = "web"
    expires_at: Optional[datetime] = None
    retention_days: int = 365
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    notes: Optional[str] = None


class ConsentRecordUpdate(BaseModel):
    status: Optional[str] = None  # granted | revoked | expired | pending
    expires_at: Optional[datetime] = None
    retention_days: Optional[int] = None
    notes: Optional[str] = None


class ConsentRecordResponse(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    subject_type: str
    subject_id: Optional[FlexUUID] = None
    user_id: Optional[FlexUUID] = None
    consent_type: str
    consent_version: str
    consent_source: str
    status: str
    granted_at: Optional[datetime] = None
    granted_by: Optional[FlexUUID] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[FlexUUID] = None
    expires_at: Optional[datetime] = None
    retention_days: int
    ip_address: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ConsentListResponse(BaseModel):
    items: List[ConsentRecordResponse]
    total: int
    page: int
    limit: int
    pages: int


class ExplainabilityResult(BaseModel):
    model_name: str
    feature_importance: Dict[str, float]
    decision_factors: List[Dict[str, Any]]
    confidence_breakdown: Dict[str, Any]
    explanation_method: str  # grad_cam | lime | shap


# ─── S27: Extended Future Enhancement Schemas ────────────────────────────────


class AugmentationTechniqueConfig(BaseModel):
    technique: str  # cutmix | mixup | adversarial | random_erasing | geometric | color_jitter
    enabled: bool = False
    params: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class AugmentationConfigRequest(BaseModel):
    techniques: List[AugmentationTechniqueConfig]
    quality_checks_enabled: bool = True
    auto_balance_demographics: bool = False


class AugmentationConfigResponse(BaseModel):
    techniques: List[AugmentationTechniqueConfig]
    quality_checks_enabled: bool
    auto_balance_demographics: bool
    data_quality_actions: List[str]


class ModelArchitectureConfig(BaseModel):
    vit_enabled: bool = False
    vit_variant: Optional[str] = None  # vit_base | vit_large | deit_small | deit_base
    hybrid_cnn_transformer: bool = False
    cnn_backbone: str = "resnet100"
    ensemble_enabled: bool = False
    ensemble_methods: Optional[List[str]] = None  # bagging | boosting | stacking


class ModelArchitectureResponse(BaseModel):
    current_architecture: str
    vit_config: Dict[str, Any]
    hybrid_config: Dict[str, Any]
    ensemble_config: Dict[str, Any]
    available_backbones: List[str]
    available_vit_variants: List[str]
    available_ensemble_methods: List[str]


class TrainingStrategyConfig(BaseModel):
    self_supervised_enabled: bool = False
    self_supervised_method: Optional[str] = None  # simclr | moco | mae | jigsaw
    continual_learning_enabled: bool = False
    prevent_catastrophic_forgetting: bool = True
    hyperparameter_optimization: Optional[str] = None  # bayesian | grid | random | automl


class TrainingStrategyResponse(BaseModel):
    self_supervised: Dict[str, Any]
    continual_learning: Dict[str, Any]
    hyperparameter_optimization: Dict[str, Any]
    available_ssl_methods: List[str]
    available_hpo_methods: List[str]


class RobustnessConfig(BaseModel):
    adversarial_training: bool = False
    input_preprocessing: bool = False  # JPEG compression, bit depth reduction
    adversarial_detection: bool = False
    partial_face_recognition: bool = False
    multi_angle_storage: bool = False
    occlusion_confidence_adjustment: bool = False


class RobustnessConfigResponse(BaseModel):
    adversarial_defense: Dict[str, Any]
    occlusion_handling: Dict[str, Any]
    defense_techniques: List[str]


class MultiAngleRecognitionConfig(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    enabled: bool
    primary_angle_tolerance: int
    secondary_angle_tolerance: int
    min_confidence_threshold: float
    angle_variants: List[str]
    weighting_strategy: str
    min_frames_required: int
    angle_timeout_ms: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class MultiAngleRecognitionConfigUpdate(BaseModel):
    enabled: bool | None = None
    primary_angle_tolerance: int | None = None
    secondary_angle_tolerance: int | None = None
    min_confidence_threshold: float | None = None
    angle_variants: List[str] | None = None
    weighting_strategy: str | None = None
    min_frames_required: int | None = None
    angle_timeout_ms: int | None = None


class AccuracyBoostConfig(BaseModel):
    multi_angle_enabled: bool = False
    supported_angles: Optional[List[str]] = None  # frontal | profile_left | profile_right | 45_degree | top_down
    consensus_voting_enabled: bool = False
    consensus_threshold: float = 0.7
    top_k_scores: int = 3
    temporal_enhancement_enabled: bool = False
    recency_weight: float = 0.6


class AccuracyBoostResponse(BaseModel):
    multi_angle: Dict[str, Any]
    consensus_voting: Dict[str, Any]
    temporal_enhancement: Dict[str, Any]
    available_angles: List[str]
    multi_angle_config: MultiAngleRecognitionConfig | None = None


class PerformanceConfig(BaseModel):
    batch_processing: bool = False
    tensorrt_enabled: bool = False
    mixed_precision: bool = False
    pipeline_parallelization: bool = False
    target_frame_processing_ms: int = 50
    target_face_detection_ms: int = 20
    target_embedding_generation_ms: int = 30
    target_vector_search_ms: int = 10


class PerformanceConfigResponse(BaseModel):
    current_latency: Dict[str, Any]
    target_latency: Dict[str, Any]
    gpu_optimizations: Dict[str, Any]
    optimization_techniques: List[str]


class PriorityMatrixItem(BaseModel):
    enhancement: str
    impact: str  # high | medium | low
    effort: str  # low | medium | high | very_high
    roi: str  # very_high | high | medium | low
    priority_tier: str  # high | medium | low
    category: Optional[str] = None


class PriorityMatrixResponse(BaseModel):
    high_priority: List[PriorityMatrixItem]
    medium_priority: List[PriorityMatrixItem]
    low_priority: List[PriorityMatrixItem]
    total_items: int


class MetricTarget(BaseModel):
    metric: str
    current: str
    target: str
    method: Optional[str] = None


class MetricsTargetsResponse(BaseModel):
    accuracy_metrics: List[MetricTarget]
    system_metrics: List[MetricTarget]
    business_metrics: List[MetricTarget]


class CurrentCapability(BaseModel):
    feature: str
    technology: str
    status: str


class CurrentLimitation(BaseModel):
    description: str
    severity: str  # high | medium | low


class CurrentPhaseItem(BaseModel):
    name: str
    component: str
    status: str


class CurrentPhaseSummary(BaseModel):
    phase: str
    title: str
    focus: str
    status: str
    implemented_count: int = 0
    planned_count: int = 0
    items: List[CurrentPhaseItem]


class CurrentCapabilitiesResponse(BaseModel):
    implemented_features: List[CurrentCapability]
    current_limitations: List[CurrentLimitation]
    phase_summary: List[CurrentPhaseSummary]
    system_version: str


class BlueprintGapItem(BaseModel):
    area: str
    status: str  # partial | missing | planned
    impact: str  # high | medium | low
    notes: str


class BlueprintLayer(BaseModel):
    name: str
    capabilities: List[str]


class BlueprintModelRecommendation(BaseModel):
    task: str
    primary: str
    alternatives: List[str] = []
    rationale: str


class BlueprintPhase(BaseModel):
    phase: str
    timeline: str
    goals: List[str]
    deliverables: List[str]


class NextGenBlueprintResponse(BaseModel):
    platform_status: str
    gaps: List[BlueprintGapItem]
    target_architecture: List[BlueprintLayer]
    model_recommendations: List[BlueprintModelRecommendation]
    serving_stack: List[str]
    mlops_stack: List[str]
    security_baseline: List[str]
    inference_latency_targets_ms: Dict[str, int]
    phased_rollout: List[BlueprintPhase]


class StreamHealthItem(BaseModel):
    camera_id: FlexUUID
    camera_name: str
    status: str
    is_active: bool
    has_rtsp: bool
    last_seen: Optional[datetime] = None
    seconds_since_last_seen: Optional[int] = None
    is_stale: bool
    health_source: str = "database"
    probe_attempted: bool = False
    probe_connected: Optional[bool] = None
    probe_latency_ms: Optional[int] = None
    probe_width: Optional[int] = None
    probe_height: Optional[int] = None
    probe_fps: Optional[float] = None
    probe_error: Optional[str] = None
    recovery_hint: str


class CrossCameraReidRequest(BaseModel):
    camera_id: Optional[FlexUUID] = None
    visitor_id: Optional[FlexUUID] = None
    lookback_minutes: int = Field(default=120, ge=5, le=1440)
    limit: int = Field(default=20, ge=1, le=100)
    min_camera_count: int = Field(default=2, ge=1, le=10)
    min_sightings: int = Field(default=1, ge=1, le=500)
    min_avg_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    min_reid_score: float = Field(default=0.0, ge=0.0, le=1.0)


class CrossCameraTransition(BaseModel):
    from_camera_id: FlexUUID
    to_camera_id: FlexUUID
    count: int
    avg_transition_seconds: Optional[float] = None


class CrossCameraReidMatch(BaseModel):
    visitor_id: FlexUUID
    visitor_name: Optional[str] = None
    camera_ids: List[FlexUUID]
    sightings: int
    average_confidence: float
    first_seen: datetime
    last_seen: datetime
    transition_count: int = 0
    reid_score: float = 0.0
    pose_quality_score: float = 0.0
    pose_samples: int = 0
    angle_distribution: Dict[str, int] = Field(default_factory=dict)
    posture_distribution: Dict[str, int] = Field(default_factory=dict)
    top_transitions: List[CrossCameraTransition] = Field(default_factory=list)


class CrossCameraReidResponse(BaseModel):
    query_camera_id: Optional[FlexUUID] = None
    lookback_minutes: int
    evaluated_logs: int = 0
    candidate_visitors: int = 0
    generated_at: Optional[datetime] = None
    matches: List[CrossCameraReidMatch]


class CrossCameraMovementSyncRequest(CrossCameraReidRequest):
    overwrite_existing: bool = False


class CrossCameraMovementSummaryItem(BaseModel):
    id: FlexUUID
    visitor_id: FlexUUID
    visitor_name: Optional[str] = None
    from_camera_id: FlexUUID
    from_camera_name: Optional[str] = None
    to_camera_id: FlexUUID
    to_camera_name: Optional[str] = None
    first_seen: datetime
    last_seen: datetime
    transition_count: int
    sightings: int
    average_confidence: float
    avg_transition_seconds: Optional[float] = None
    reid_score: float = 0.0
    source: str
    details: Dict[str, Any] = Field(default_factory=dict)
    updated_at: Optional[datetime] = None


class CrossCameraMovementSyncResponse(BaseModel):
    lookback_minutes: int
    synced_matches: int
    upserted_movements: int
    generated_at: Optional[datetime] = None
    items: List[CrossCameraMovementSummaryItem] = Field(default_factory=list)


class CrossCameraMovementListResponse(BaseModel):
    total: int
    items: List[CrossCameraMovementSummaryItem] = Field(default_factory=list)


class NLAnalyticsQueryRequest(BaseModel):
    query: str
    lookback_hours: int = Field(default=24, ge=1, le=168)


class NLAnalyticsQueryResponse(BaseModel):
    query: str
    interpreted_intent: str
    summary: str
    result: Dict[str, Any]


class VisionInferenceRequest(BaseModel):
    camera_id: Optional[FlexUUID] = None
    rtsp_url: Optional[str] = None
    frame_data: Optional[str] = None
    image_path: Optional[str] = None


class PoseEstimateResponse(BaseModel):
    source: str
    camera_id: Optional[FlexUUID] = None
    status: str
    available: bool
    model: str
    posture: str = "unknown"
    keypoint_count: int = 0
    average_visibility: float = 0.0
    processing_time_ms: float = 0.0
    message: Optional[str] = None
    snapshot_thumbnail: Optional[str] = None
    analytics_event_id: Optional[FlexUUID] = None


class ActionInferRequest(VisionInferenceRequest):
    track_id: Optional[str] = None


class ActionInferResponse(BaseModel):
    source: str
    camera_id: Optional[FlexUUID] = None
    status: str
    available: bool
    model: str
    action: str = "unknown"
    gesture: str = "none"
    confidence: float = 0.0
    posture: str = "unknown"
    keypoint_count: int = 0
    processing_time_ms: float = 0.0
    message: Optional[str] = None
    flags: Dict[str, Any] = Field(default_factory=dict)
    snapshot_thumbnail: Optional[str] = None
    analytics_event_id: Optional[FlexUUID] = None


class VisionAnalyticsHistoryItem(BaseModel):
    id: FlexUUID
    event_type: str
    source: str
    camera_id: Optional[FlexUUID] = None
    camera_name: Optional[str] = None
    model: Optional[str] = None
    status: str
    summary: Optional[str] = None
    posture: Optional[str] = None
    action: Optional[str] = None
    gesture: Optional[str] = None
    confidence: Optional[float] = None
    snapshot_url: Optional[str] = None
    created_at: datetime


class VisionAnalyticsHistoryResponse(BaseModel):
    event_type: Optional[str] = None
    lookback_hours: int
    total: int
    items: List[VisionAnalyticsHistoryItem] = Field(default_factory=list)


class BehaviorAnalyzeRequest(ActionInferRequest):
    visitor_id: Optional[FlexUUID] = None
    visitor_log_id: Optional[FlexUUID] = None
    source: Optional[str] = None


class BehaviorEventItem(BaseModel):
    id: FlexUUID
    event_type: str
    source: str
    visitor_id: Optional[FlexUUID] = None
    visitor_name: Optional[str] = None
    visitor_log_id: Optional[FlexUUID] = None
    camera_id: Optional[FlexUUID] = None
    camera_name: Optional[str] = None
    posture: Optional[str] = None
    action: Optional[str] = None
    gesture: Optional[str] = None
    confidence: float = 0.0
    anomaly_score: float = 0.0
    anomaly_label: str = "normal_behavior"
    severity: str = "info"
    reviewed: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class BehaviorEventListResponse(BaseModel):
    total: int
    anomaly_count: int = 0
    critical_count: int = 0
    items: List[BehaviorEventItem] = Field(default_factory=list)


class BehaviorEventUpdateRequest(BaseModel):
    reviewed: bool = True
    notes: Optional[str] = None


class ContinuousLearningSignalItem(BaseModel):
    id: FlexUUID
    signal_type: str
    priority: str
    status: str
    confidence: Optional[float] = None
    source: str
    visitor_id: Optional[FlexUUID] = None
    visitor_name: Optional[str] = None
    visitor_log_id: Optional[FlexUUID] = None
    behavior_event_id: Optional[FlexUUID] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ContinuousLearningSignalListResponse(BaseModel):
    total: int
    open_count: int = 0
    queued_count: int = 0
    items: List[ContinuousLearningSignalItem] = Field(default_factory=list)


class ContinuousLearningSignalUpdateRequest(BaseModel):
    status: str
    resolution: Optional[str] = None
    notes: Optional[str] = None


class ContinuousLearningSignalPromoteRequest(BaseModel):
    visitor_id: Optional[FlexUUID] = None
    is_positive: bool = True
    source: str = "continuous_learning_signal"
    confidence: Optional[float] = None
    face_image_path: Optional[str] = None


class ContinuousLearningQueueRequest(BaseModel):
    signal_ids: Optional[List[FlexUUID]] = None
    max_samples: int = Field(default=25, ge=1, le=200)
    min_priority: str = Field(default="medium")
    strategy: str = Field(default="anomaly_first")


class ContinuousLearningQueueResponse(BaseModel):
    job_id: FlexUUID
    queued_signal_count: int
    selected_signal_ids: List[FlexUUID] = Field(default_factory=list)
    strategy: str
    training_recommended: bool


class ContinuousLearningSignalPromoteResponse(BaseModel):
    signal: ContinuousLearningSignalItem
    sample_id: Optional[FlexUUID] = None


class BehaviorAnalysisResponse(BaseModel):
    pose_estimate: PoseEstimateResponse
    action_inference: ActionInferResponse
    event: BehaviorEventItem
    signal_created: bool = False
    learning_signal: Optional[ContinuousLearningSignalItem] = None
    anomaly_reasons: List[str] = Field(default_factory=list)


class RuntimeModelComponent(BaseModel):
    component: str
    display_name: str
    current_model: str
    current_artifact: Optional[str] = None
    target_model: Optional[str] = None
    target_artifact: Optional[str] = None
    framework: str
    runtime: str
    status: str
    notes: Optional[str] = None


class RuntimeModelRegistryResponse(BaseModel):
    version: str
    source: str
    last_updated_at: Optional[datetime] = None
    data_dir: Optional[str] = None
    components: List[RuntimeModelComponent]


class RuntimeModelRegistryUpdate(BaseModel):
    version: Optional[str] = None
    components: List[RuntimeModelComponent]


class BenchmarkGateMetric(BaseModel):
    name: str
    status: str
    current_value: Optional[float] = None
    target_value: Optional[float] = None
    unit: str
    detail: str


class BenchmarkTrendPoint(BaseModel):
    run_at: datetime
    sample_size: int
    status: str
    baseline_accuracy: Optional[float] = None
    multi_angle_accuracy: Optional[float] = None
    avg_latency_ms: Optional[float] = None
    production_ready: bool = False
    latency_target_met: bool = False


class BenchmarkSummaryResponse(BaseModel):
    status: str
    sample_size: int = 0
    run_at: Optional[datetime] = None
    baseline_accuracy: Optional[float] = None
    multi_angle_accuracy: Optional[float] = None
    multi_angle_boost_pct: Optional[float] = None
    mean_reciprocal_rank: Optional[float] = None
    avg_latency_ms: Optional[float] = None
    latency_target_met: bool = False
    production_ready: bool = False
    target_baseline_accuracy: float = 95.0
    target_latency_ms: float = 150.0
    accuracy_gap_pct: Optional[float] = None
    latency_budget_remaining_ms: Optional[float] = None
    recommendation: Optional[str] = None
    results_path: Optional[str] = None


class MLflowModelVersionSummary(BaseModel):
    component: str
    registered_model: str
    version: str
    stage: str
    run_id: Optional[str] = None
    artifact_uri: Optional[str] = None
    metrics: Dict[str, float] = Field(default_factory=dict)
    tags: Dict[str, str] = Field(default_factory=dict)
    last_transitioned_at: Optional[datetime] = None


class ModelPromotionRecord(BaseModel):
    promotion_id: str
    component: str
    previous_model: Optional[str] = None
    previous_artifact: Optional[str] = None
    candidate_model: str
    candidate_artifact: Optional[str] = None
    requested_by: FlexUUID
    requested_at: datetime
    benchmark_status: str
    benchmark_production_ready: bool = False
    benchmark_sample_size: int = 0
    reason: Optional[str] = None
    applied: bool = False
    applied_at: Optional[datetime] = None
    notes: Optional[str] = None


class MLflowRegistryResponse(BaseModel):
    status: str
    tracking_uri: str
    mlflow_available: bool
    last_updated_at: Optional[datetime] = None
    models: List[MLflowModelVersionSummary] = Field(default_factory=list)
    promotions: List[ModelPromotionRecord] = Field(default_factory=list)


class MLflowPromotionHealthSummary(BaseModel):
    total_promotions: int
    applied_promotions: int
    blocked_promotions: int
    last_promotion_at: Optional[datetime] = None


class ModelPromotionRequest(BaseModel):
    component: str
    candidate_model: str
    candidate_artifact: Optional[str] = None
    reason: Optional[str] = None
    benchmark_sample_size: int = Field(default=30, ge=10, le=200)
    require_production_ready: bool = True


class ModelPromotionResponse(BaseModel):
    status: str
    message: str
    promotion: ModelPromotionRecord
    runtime_registry: RuntimeModelRegistryResponse
    benchmark_summary: BenchmarkSummaryResponse
    gate_metrics: List[BenchmarkGateMetric] = Field(default_factory=list)
    history: List[BenchmarkTrendPoint] = Field(default_factory=list)


# ─── S29: Alert Configuration Schemas ────────────────────────────────────────


class AlertRuleBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: bool = True
    priority: str = "medium"  # low | medium | high | critical
    trigger_type: str  # known | unknown | liveness_fail | anomaly
    min_confidence: Optional[float] = None
    max_confidence: Optional[float] = None
    include_visitor_ids: List[str] = Field(default_factory=list)
    include_camera_ids: List[str] = Field(default_factory=list)
    time_range_start: Optional[str] = None  # HH:MM
    time_range_end: Optional[str] = None    # HH:MM
    days_of_week: List[int] = Field(default_factory=list)  # 0-6, empty = all days
    action: str = "email"  # email | webhook | both | notify | silence
    webhook_id: Optional[str] = None
    notification_template: Optional[str] = None
    max_alerts_per_hour: Optional[int] = None


class AlertRuleCreate(AlertRuleBase):
    pass


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    priority: Optional[str] = None
    trigger_type: Optional[str] = None
    min_confidence: Optional[float] = None
    max_confidence: Optional[float] = None
    include_visitor_ids: Optional[List[str]] = None
    include_camera_ids: Optional[List[str]] = None
    time_range_start: Optional[str] = None
    time_range_end: Optional[str] = None
    days_of_week: Optional[List[int]] = None
    action: Optional[str] = None
    webhook_id: Optional[str] = None
    notification_template: Optional[str] = None
    max_alerts_per_hour: Optional[int] = None


class AlertRuleResponse(AlertRuleBase):
    id: FlexUUID
    organization_id: FlexUUID
    alert_config_id: FlexUUID
    order: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class AlertConfigBase(BaseModel):
    alerts_enabled: bool = True
    email_alerts_enabled: bool = True
    webhook_alerts_enabled: bool = True
    min_confidence_threshold: float = 0.5
    alert_duplicate_window_seconds: int = 300
    enabled_alert_types: List[str] = Field(default_factory=list)  # known, unknown, liveness_failed, anomaly
    default_action: str = "email"  # email | webhook | both


class AlertConfigCreate(AlertConfigBase):
    pass


class AlertConfigUpdate(BaseModel):
    alerts_enabled: Optional[bool] = None
    email_alerts_enabled: Optional[bool] = None
    webhook_alerts_enabled: Optional[bool] = None
    min_confidence_threshold: Optional[float] = None
    alert_duplicate_window_seconds: Optional[int] = None
    enabled_alert_types: Optional[List[str]] = None
    default_action: Optional[str] = None


class AlertConfigResponse(AlertConfigBase):
    id: FlexUUID
    organization_id: FlexUUID
    rules: List[AlertRuleResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RoadmapTask(BaseModel):
    task: str
    description: str
    effort: str


class RoadmapPhaseDetail(BaseModel):
    phase: str
    title: str
    description: str
    timeline: str
    tasks: List[RoadmapTask]
    enhancements: List[FutureEnhancementResponse]
    progress_percent: float


class RoadmapDetailResponse(BaseModel):
    phases: List[RoadmapPhaseDetail]
    total_enhancements: int
    enabled_count: int
    completion_percent: float


# ─── Phase 3: SSO Provider Schemas (US-ENT-010) ───────────────────────────────


class SSOProviderBase(BaseModel):
    provider_type: str  # 'saml', 'oauth2', 'openid'
    provider_name: str
    entity_id: Optional[str] = None
    sso_url: Optional[str] = None
    certificate: Optional[str] = None
    attribute_mappings: Dict[str, str] = {}
    active: bool = False


class SSOProviderCreate(SSOProviderBase):
    pass


class SSOProviderUpdate(BaseModel):
    provider_name: Optional[str] = None
    entity_id: Optional[str] = None
    sso_url: Optional[str] = None
    certificate: Optional[str] = None
    attribute_mappings: Optional[Dict[str, str]] = None
    active: Optional[bool] = None


class SSOProviderResponse(SSOProviderBase):
    id: FlexUUID
    organization_id: FlexUUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SSOSessionResponse(BaseModel):
    id: FlexUUID
    user_id: FlexUUID
    provider_id: FlexUUID
    token: str
    created_at: datetime
    expires_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ─── Phase 3: LDAP Configuration Schemas ────────────────────────────────────


class LdapConfigBase(BaseModel):
    ldap_server: str
    ldap_port: int = Field(default=389, ge=1, le=65535)
    use_ssl: bool = False
    bind_dn: Optional[str] = None
    bind_password: Optional[str] = None
    user_search_base: str
    group_search_base: Optional[str] = None
    user_attribute: str = "uid"
    group_attribute: str = "cn"
    active: bool = False


class LdapConfigCreate(LdapConfigBase):
    pass


class LdapConfigUpdate(BaseModel):
    ldap_server: Optional[str] = None
    ldap_port: Optional[int] = Field(default=None, ge=1, le=65535)
    use_ssl: Optional[bool] = None
    bind_dn: Optional[str] = None
    bind_password: Optional[str] = None
    user_search_base: Optional[str] = None
    group_search_base: Optional[str] = None
    user_attribute: Optional[str] = None
    group_attribute: Optional[str] = None
    active: Optional[bool] = None


class LdapConfigResponse(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    ldap_server: str
    ldap_port: int
    use_ssl: bool
    bind_dn: Optional[str] = None
    user_search_base: str
    group_search_base: Optional[str] = None
    user_attribute: str
    group_attribute: str
    active: bool
    has_bind_password: bool = False
    last_sync_at: Optional[datetime] = None
    last_sync_status: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class LdapConnectionTestResponse(BaseModel):
    status: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)


class LdapSyncLogResponse(BaseModel):
    id: FlexUUID
    organization_id: FlexUUID
    ldap_config_id: FlexUUID
    users_synced: int
    groups_synced: int
    users_disabled: int
    status: str
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LdapSyncLogListResponse(BaseModel):
    total: int
    items: List[LdapSyncLogResponse]


class LdapSyncResponse(BaseModel):
    status: str
    message: str
    users_synced: int
    groups_synced: int
    users_disabled: int
    log_id: FlexUUID


# ─── Phase 3: GDPR Compliance Schemas (US-SEC-015) ───────────────────────────


class GDPRRequestBase(BaseModel):
    request_type: str  # 'data_export', 'data_deletion', 'consent_withdrawal'
    notes: Optional[str] = None


class GDPRRequestCreate(GDPRRequestBase):
    pass


class GDPRRequestResponse(GDPRRequestBase):
    id: FlexUUID
    visitor_id: FlexUUID
    status: str  # 'pending', 'processing', 'completed'
    request_date: datetime
    completion_date: Optional[datetime] = None
    response_file_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class VisitorConsentBase(BaseModel):
    consent_type: str  # 'face_recognition', 'tracking', 'analytics'
    consent_given: bool


class VisitorConsentCreate(VisitorConsentBase):
    pass


class VisitorConsentResponse(VisitorConsentBase):
    id: FlexUUID
    visitor_id: FlexUUID
    consent_date: datetime
    consent_withdrawn_date: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DataRetentionPolicyBase(BaseModel):
    data_type: str  # 'face_images', 'face_embeddings', 'logs'
    retention_days: int
    auto_delete_enabled: bool = True


class DataRetentionPolicyCreate(DataRetentionPolicyBase):
    pass


class DataRetentionPolicyResponse(DataRetentionPolicyBase):
    id: FlexUUID
    organization_id: FlexUUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ─── User Tracking Analytics (UTA) Schemas ───────────────────────────────────


class UserSessionBase(BaseModel):
    visitor_id: Optional[FlexUUID] = None
    session_start: datetime
    session_end: Optional[datetime] = None
    current_position: Dict[str, Any] = Field(default_factory=dict)
    path: List[Dict[str, Any]] = Field(default_factory=list)
    status: str = "active"
    last_updated: datetime


class UserSessionCreate(UserSessionBase):
    organization_id: FlexUUID


class UserSessionResponse(UserSessionBase):
    id: FlexUUID
    organization_id: FlexUUID

    model_config = ConfigDict(from_attributes=True)


class AnalyticsPredictionBase(BaseModel):
    prediction_type: str
    date_range: Dict[str, str]
    predicted_value: float
    confidence: Optional[float] = None
    model_used: Optional[str] = None
    actual_value: Optional[float] = None
    created_at: datetime


class AnalyticsPredictionCreate(AnalyticsPredictionBase):
    organization_id: FlexUUID


class AnalyticsPredictionResponse(AnalyticsPredictionBase):
    id: FlexUUID
    organization_id: FlexUUID

    model_config = ConfigDict(from_attributes=True)


class RealtimeTrackingResponse(BaseModel):
    active_sessions: List[UserSessionResponse] = Field(default_factory=list)
    total_active: int = 0
    generated_at: str


