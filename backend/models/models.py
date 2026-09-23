from sqlalchemy import (
    Column, String, Boolean, DateTime, ForeignKey, Float, Text, Integer, JSON,
    event, Enum,
)
from sqlalchemy.orm import relationship, synonym
from sqlalchemy.types import TypeDecorator
import uuid
import json as _json
import datetime
from db.base import Base, IS_SQLITE


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)

# ─── Conditional imports for PostgreSQL vs SQLite ────────────────────────────


class JSONText(TypeDecorator):
    """Stores Python dicts/lists as JSON strings in a Text column (for SQLite)."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return _json.dumps(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return _json.loads(value)
        return value


class StringUUID(TypeDecorator):
    """Stores Python uuid.UUID objects as String(36) in SQLite."""
    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        return value  # keep as string


if IS_SQLITE:

    def _uuid_column(*args, primary_key=False, **kwargs):
        """UUID stored as String(36) in SQLite."""
        return Column(
            StringUUID,
            *args,
            primary_key=primary_key,
            default=lambda: str(uuid.uuid4()),
            **kwargs,
        )

    def _fk_uuid_column(fk, **kwargs):
        """Foreign key UUID stored as String(36) in SQLite."""
        return Column(StringUUID, ForeignKey(fk), **kwargs)

    def _jsonb_column(**kwargs):
        """JSONB stored as JSONText (auto-serialized JSON string) in SQLite."""
        return Column(JSONText, **kwargs)

    # No vector support in SQLite — store as JSONText (auto-serialized JSON string)
    def _vector_column(dim):
        return Column(JSONText, nullable=True)

else:
    from sqlalchemy.dialects.postgresql import UUID, JSONB
    from pgvector.sqlalchemy import Vector

    def _uuid_column(*args, primary_key=False, **kwargs):
        return Column(
            UUID(as_uuid=True),
            *args,
            primary_key=primary_key,
            default=uuid.uuid4,
            **kwargs,
        )

    def _fk_uuid_column(fk, **kwargs):
        return Column(UUID(as_uuid=True), ForeignKey(fk), **kwargs)

    def _jsonb_column(**kwargs):
        return Column(JSONB, **kwargs)

    def _vector_column(dim):
        return Column(Vector(dim))


# ─── Models ──────────────────────────────────────────────────────────────────


class Organization(Base):
    __tablename__ = "organizations"

    id = _uuid_column(primary_key=True)
    name = Column(String, nullable=False)
    # api_key removed — was generated but never read for authentication.
    # Replaced by the ApiKey model which uses hashed keys. Migration 023 drops it.
    face_confidence_threshold = Column(Float, default=0.6)
    log_retention_days = Column(Integer, default=90)
    notification_email = Column(Boolean, default=True)
    notification_unidentified = Column(Boolean, default=True)
    # Dedicated email address for alert notifications (optional).
    # Falls back to admin user emails when null.
    notification_email_address = Column(String, nullable=True)
    settings = _jsonb_column(default=dict)
    created_at = Column(DateTime, default=utcnow)

    users = relationship("User", back_populates="organization", lazy="raise")
    visitors = relationship("Visitor", back_populates="organization", lazy="raise")
    logs = relationship("VisitorLog", back_populates="organization", lazy="raise")
    cameras = relationship("Camera", back_populates="organization", lazy="raise")
    edge_devices = relationship("EdgeDevice", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    edge_device_events = relationship("EdgeDeviceEvent", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    audit_logs = relationship("AuditLog", back_populates="organization", lazy="raise")
    camera_sessions = relationship("CameraSession", back_populates="organization", lazy="raise")
    webhooks = relationship("Webhook", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    api_keys = relationship("ApiKey", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    notifications = relationship("Notification", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    camera_groups = relationship("CameraGroup", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    retention_policies = relationship("DataRetentionPolicy", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    future_enhancements = relationship("FutureEnhancement", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    rate_limit_rules = relationship("RateLimitRule", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    carbon_metrics = relationship("CarbonMetrics", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    bias_audit_records = relationship("BiasAuditRecord", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    consent_records = relationship("ConsentRecord", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    liveness_scores = relationship("LivenessScore", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    training_jobs = relationship("TrainingJob", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    hpo_jobs = relationship("HPOJob", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    ensembles = relationship("Ensemble", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    active_learning_jobs = relationship("ActiveLearningJob", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    behavior_events = relationship("BehaviorEvent", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    movement_summaries = relationship("CrossCameraMovementSummary", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    continuous_learning_signals = relationship("ContinuousLearningSignal", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    alert_config = relationship("AlertConfig", back_populates="organization", cascade="all, delete-orphan", uselist=False, lazy="raise")
    data_quality_configs = relationship("DataQualityConfig", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    synthetic_data_configs = relationship("SyntheticDataConfig", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    temporal_augmentation_configs = relationship("TemporalAugmentationConfig", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    multi_angle_configs = relationship("MultiAngleRecognitionConfig", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    model_versions = relationship("ModelVersion", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    multimodal_fusion_configs = relationship("MultimodalFusionConfig", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    ab_test_experiments = relationship("ABTestExperiment", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    vision_analytics_events = relationship("VisionAnalyticsEvent", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    sso_providers = relationship("SSOProvider", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    ldap_configs = relationship("LdapConfig", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    ldap_sync_logs = relationship("LdapSyncLog", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    user_sessions = relationship("UserSession", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    analytics_predictions = relationship("AnalyticsPrediction", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    liveness_challenges = relationship("LivenessChallenge", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    refresh_token_sessions = relationship("RefreshTokenSession", back_populates="organization", cascade="all, delete-orphan", lazy="raise")
    video_processing_jobs = relationship("VideoProcessingJob", back_populates="organization", cascade="all, delete-orphan", lazy="raise")


class MultiAngleRecognitionConfig(Base):
    """Configuration for multi-angle face recognition (US-FUT-020)."""
    __tablename__ = "multi_angle_configs"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)

    enabled = Column(Boolean, default=True)
    primary_angle_tolerance = Column(Integer, default=30)
    secondary_angle_tolerance = Column(Integer, default=60)
    min_confidence_threshold = Column(Float, default=0.85)

    # Angle variants enabled (frontal, 45_left, 45_right, profile)
    angle_variants = _jsonb_column(default=lambda: ["frontal", "45_left", "45_right"])
    weighting_strategy = Column(String, default="confidence_weighted")  # confidence_weighted, majority_voting

    min_frames_required = Column(Integer, default=3)
    angle_timeout_ms = Column(Integer, default=5000)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="multi_angle_configs")


class User(Base):
    __tablename__ = "users"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="staff")  # admin, staff
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="users")
    audit_logs = relationship("AuditLog", back_populates="user")
    camera_sessions = relationship("CameraSession", back_populates="started_by_user")
    notifications = relationship("Notification", back_populates="user")
    refresh_token_sessions = relationship("RefreshTokenSession", back_populates="user", cascade="all, delete-orphan")
    training_jobs_started = relationship("TrainingJob", back_populates="user", foreign_keys="TrainingJob.started_by")
    hpo_jobs_started = relationship("HPOJob", back_populates="user", foreign_keys="HPOJob.started_by")
    ensembles_created = relationship("Ensemble", back_populates="user", foreign_keys="Ensemble.created_by")
    active_learning_jobs_created = relationship("ActiveLearningJob", back_populates="user", foreign_keys="ActiveLearningJob.created_by")
    bias_audits_performed = relationship("BiasAuditRecord", back_populates="user", foreign_keys="BiasAuditRecord.audited_by")


class Visitor(Base):
    __tablename__ = "visitors"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    visitor_metadata = _jsonb_column(default=dict)
    is_known = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
    )
    last_detected_at = Column(DateTime, nullable=True)
    detection_count = Column(Integer, default=0)
    # S16: Adaptive threshold per visitor
    custom_threshold = Column(Float, nullable=True)
    # S16: Continuous learning toggle
    auto_learn = Column(Boolean, default=False)

    organization = relationship("Organization", back_populates="visitors")
    face_data = relationship(
        "FaceData", back_populates="visitor", cascade="all, delete-orphan"
    )
    logs = relationship("VisitorLog", back_populates="visitor")
    detection_logs = relationship("DetectionLog", back_populates="visitor")
    behavior_events = relationship("BehaviorEvent", back_populates="visitor")
    movement_summaries = relationship("CrossCameraMovementSummary", back_populates="visitor")
    learning_signals = relationship("ContinuousLearningSignal", back_populates="visitor")
    three_d_face_data = relationship("ThreeDFaceData", back_populates="visitor", cascade="all, delete-orphan")
    multimodal_embeddings = relationship("MultimodalEmbedding", back_populates="visitor", cascade="all, delete-orphan")
    audio_features = relationship("AudioFeature", back_populates="visitor", cascade="all, delete-orphan")
    text_bio_features = relationship("TextBioFeature", back_populates="visitor", cascade="all, delete-orphan")


class FaceData(Base):
    __tablename__ = "face_data"

    id = _uuid_column(primary_key=True)
    visitor_id = _fk_uuid_column("visitors.id")
    embedding = _vector_column(512)  # ArcFace 512-dim (Text in SQLite)
    embedding_key_version = Column(String(16), nullable=True)
    image_url = Column(String, nullable=True)
    quality_score = Column(Float, default=0.0)
    face_angle = Column(String, nullable=True)
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    visitor = relationship("Visitor", back_populates="face_data")


class Camera(Base):
    __tablename__ = "cameras"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    name = Column(String, nullable=False)
    rtsp_url = Column(String, nullable=True)
    location = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    status = Column(String, default="offline")  # online | offline | error
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    # S21: Camera grouping
    group_id = _fk_uuid_column("camera_groups.id", nullable=True)
    # S21: Health monitoring
    frame_rate = Column(Float, nullable=True)
    health_status = Column(String, default="unknown")  # healthy | degraded | critical | unknown

    organization = relationship("Organization", back_populates="cameras")
    logs = relationship("VisitorLog", back_populates="camera")
    group = relationship("CameraGroup", back_populates="cameras")
    vision_analytics_events = relationship("VisionAnalyticsEvent", back_populates="camera")
    behavior_events = relationship("BehaviorEvent", back_populates="camera")


class EdgeDevice(Base):
    __tablename__ = "edge_devices"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")

    name = Column(String, nullable=False)
    device_type = Column(String, default="jetson")
    status = Column(String, default="offline")  # online | offline | error
    is_active = Column(Boolean, default=True)

    location = Column(String, nullable=True)
    endpoint_url = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    serial_number = Column(String, nullable=True)

    hardware_info = _jsonb_column(default=dict)
    tags = _jsonb_column(default=list)
    model_version_id = _fk_uuid_column("model_versions.id", nullable=True)
    model_artifact_path = Column(String, nullable=True)
    model_config = _jsonb_column(default=dict)

    last_seen = Column(DateTime, nullable=True)
    last_metrics = _jsonb_column(default=dict)
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_count = Column(Integer, default=0)
    last_sync_status = Column(String, default="never")  # never | success | error
    last_export_at = Column(DateTime, nullable=True)
    last_export_status = Column(String, nullable=True)
    last_export_path = Column(String, nullable=True)
    last_export_details = _jsonb_column(default=dict)

    token_hash = Column(String, unique=True, nullable=False)
    token_prefix = Column(String, nullable=False)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="edge_devices")
    model_version = relationship("ModelVersion")
    events = relationship("EdgeDeviceEvent", back_populates="edge_device", cascade="all, delete-orphan")


class EdgeDeviceEvent(Base):
    __tablename__ = "edge_device_events"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    edge_device_id = _fk_uuid_column("edge_devices.id")

    event_type = Column(String, default="alert")
    severity = Column(String, default="info")  # info | low | medium | high | critical
    title = Column(String, nullable=False)
    message = Column(Text, nullable=True)
    payload = _jsonb_column(default=dict)
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="edge_device_events")
    edge_device = relationship("EdgeDevice", back_populates="events")


class VisitorLog(Base):
    __tablename__ = "visitor_logs"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    visitor_id = _fk_uuid_column("visitors.id", nullable=True)
    camera_id = _fk_uuid_column("cameras.id", nullable=True)
    face_data_id = _fk_uuid_column("face_data.id", nullable=True)
    timestamp = Column(DateTime, default=utcnow)
    video_snippet_path = Column(String, nullable=True)
    face_image_path = Column(String, nullable=True)
    confidence = Column(Float, default=0.0)
    identified = Column(Boolean, default=False)
    status = Column(String, default="detected")
    # detected | identified | unidentified | reviewed
    track_id = Column(Integer, nullable=True)
    source_video = Column(String, nullable=True)

    organization = relationship("Organization", back_populates="logs")
    visitor = relationship("Visitor", back_populates="logs")
    camera = relationship("Camera", back_populates="logs")
    face_data = relationship("FaceData")
    behavior_events = relationship("BehaviorEvent", back_populates="visitor_log")
    learning_signals = relationship("ContinuousLearningSignal", back_populates="visitor_log")


class VisionAnalyticsEvent(Base):
    __tablename__ = "vision_analytics_events"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    camera_id = _fk_uuid_column("cameras.id", nullable=True)
    event_type = Column(String, nullable=False)  # pose_estimate | action_infer
    source = Column(String, nullable=False)
    model = Column(String, nullable=True)
    status = Column(String, default="unknown")
    summary = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    posture = Column(String, nullable=True)
    action = Column(String, nullable=True)
    gesture = Column(String, nullable=True)
    snapshot_path = Column(String, nullable=True)
    payload = _jsonb_column(default=dict)
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="vision_analytics_events")
    camera = relationship("Camera", back_populates="vision_analytics_events")


class BehaviorEvent(Base):
    __tablename__ = "behavior_events"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    visitor_id = _fk_uuid_column("visitors.id", nullable=True)
    visitor_log_id = _fk_uuid_column("visitor_logs.id", nullable=True)
    camera_id = _fk_uuid_column("cameras.id", nullable=True)
    event_type = Column(String, default="behavior")  # behavior | anomaly | movement
    source = Column(String, default="vision_snapshot")  # vision_snapshot | replay | rule_engine
    posture = Column(String, nullable=True)
    action = Column(String, nullable=True)
    gesture = Column(String, nullable=True)
    confidence = Column(Float, default=0.0)
    anomaly_score = Column(Float, default=0.0)
    anomaly_label = Column(String, default="normal_behavior")
    severity = Column(String, default="info")  # info | low | medium | high | critical
    details = _jsonb_column(default=dict)
    reviewed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="behavior_events")
    visitor = relationship("Visitor", back_populates="behavior_events")
    visitor_log = relationship("VisitorLog", back_populates="behavior_events")
    camera = relationship("Camera", back_populates="behavior_events")


class CrossCameraMovementSummary(Base):
    __tablename__ = "cross_camera_movement_summaries"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    visitor_id = _fk_uuid_column("visitors.id", nullable=False)
    from_camera_id = _fk_uuid_column("cameras.id", nullable=False)
    to_camera_id = _fk_uuid_column("cameras.id", nullable=False)
    first_seen = Column(DateTime, nullable=False)
    last_seen = Column(DateTime, nullable=False)
    transition_count = Column(Integer, default=0)
    sightings = Column(Integer, default=0)
    average_confidence = Column(Float, default=0.0)
    avg_transition_seconds = Column(Float, nullable=True)
    reid_score = Column(Float, default=0.0)
    source = Column(String, default="reid_sync")
    details = _jsonb_column(default=dict)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="movement_summaries")
    visitor = relationship("Visitor", back_populates="movement_summaries")


class ContinuousLearningSignal(Base):
    __tablename__ = "continuous_learning_signals"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    visitor_id = _fk_uuid_column("visitors.id", nullable=True)
    visitor_log_id = _fk_uuid_column("visitor_logs.id", nullable=True)
    behavior_event_id = _fk_uuid_column("behavior_events.id", nullable=True)
    signal_type = Column(String, default="anomaly")  # anomaly | low_confidence | unidentified | feedback
    priority = Column(String, default="medium")  # low | medium | high | critical
    status = Column(String, default="open")  # open | queued | reviewed | resolved
    confidence = Column(Float, nullable=True)
    source = Column(String, default="behavior_pipeline")
    details = _jsonb_column(default=dict)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="continuous_learning_signals")
    visitor = relationship("Visitor", back_populates="learning_signals")
    visitor_log = relationship("VisitorLog", back_populates="learning_signals")
    behavior_event = relationship("BehaviorEvent")


class LivenessScore(Base):
    """S29: Liveness Detection & Anti-Spoofing (US-FUT-042)
    
    Stores liveness detection results for each detection event.
    Tracks scores from multiple detection methods: texture-based (LBP),
    motion-based (optical flow, eye blink), and deep learning-based.
    """
    __tablename__ = "liveness_scores"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    visitor_log_id = _fk_uuid_column("visitor_logs.id")
    
    # Overall liveness decision
    is_live = Column(Boolean, nullable=False)  # True = real face, False = spoof/attack
    overall_score = Column(Float, nullable=False)  # 0.0-1.0, confidence in liveness
    rejection_reason = Column(String, nullable=True)  # "low_texture" | "no_motion" | "attack_detected" | None
    
    # Detection method scores (0.0-1.0)
    texture_score = Column(Float, nullable=True)  # LBP-based texture analysis
    motion_score = Column(Float, nullable=True)   # Optical flow + eye blink detection
    deep_learning_score = Column(Float, nullable=True)  # CNN-based liveness classifier
    
    # Video requirement tracking
    video_required = Column(Boolean, default=True)
    video_duration_frames = Column(Integer, nullable=True)  # Frames in video snippet
    has_sufficient_motion = Column(Boolean, nullable=True)
    blink_count = Column(Integer, nullable=True)
    
    # Spoofing attack indicators
    attack_indicators = _jsonb_column(default=dict)  # e.g. {"print_attack": 0.8, "replay_attack": 0.1}
    
    # Quality metrics
    face_size = Column(Integer, nullable=True)  # Pixels
    illumination_score = Column(Float, nullable=True)  # 0.0-1.0
    blur_score = Column(Float, nullable=True)  # 0.0-1.0 (higher = more blur)
    noise_level = Column(Float, nullable=True)  # 0.0-1.0
    
    # Challenge-response (optional for advanced liveness)
    challenge_type = Column(String, nullable=True)  # "blink" | "head_turn" | "smile" | None
    challenge_passed = Column(Boolean, nullable=True)
    challenge_attempts = Column(Integer, default=0)
    
    # Metadata
    method_used = Column(String, nullable=False)  # "texture" | "motion" | "deep_learning" | "ensemble"
    model_version = Column(String, nullable=True)  # e.g. "liveness_v1.0"
    processing_time_ms = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="liveness_scores")
    visitor_log = relationship("VisitorLog")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    user_id = _fk_uuid_column("users.id", nullable=True)
    action = Column(String, nullable=False)  # create, update, delete, login, etc.
    entity_type = Column(String, nullable=True)  # visitor, camera, user, log, etc.
    entity_id = Column(String, nullable=True)  # ID of affected entity
    details = _jsonb_column(default=dict)
    # S20: Enhanced audit trail with before/after values
    before_values = _jsonb_column(nullable=True)
    after_values = _jsonb_column(nullable=True)
    timestamp = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="audit_logs")
    user = relationship("User", back_populates="audit_logs")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = _uuid_column(primary_key=True)
    user_id = _fk_uuid_column("users.id")
    token = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    user = relationship("User")


class RefreshTokenSession(Base):
    __tablename__ = "refresh_token_sessions"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)
    user_id = _fk_uuid_column("users.id")
    token_hash = Column(String, unique=True, index=True, nullable=False)
    token_jti = Column(String, index=True, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoke_reason = Column(String, nullable=True)
    replaced_by_token_hash = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="refresh_token_sessions")
    user = relationship("User", back_populates="refresh_token_sessions")


class VideoProcessingJob(Base):
    __tablename__ = "video_processing_jobs"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    file_id = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    status = Column(String, default="queued")  # queued | processing | completed | error
    message = Column(Text, nullable=True)
    people_detected = Column(Integer, default=0)
    people_identified = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
    )

    organization = relationship("Organization", back_populates="video_processing_jobs")


# ─── Live Camera Models ─────────────────────────────────────────────────────


class CameraSession(Base):
    __tablename__ = "camera_sessions"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    user_id = _fk_uuid_column("users.id")
    camera_id = _fk_uuid_column("cameras.id", nullable=True)
    status = Column(String, default="active")  # active | ended | error
    started_at = Column(DateTime, default=utcnow)
    ended_at = Column(DateTime, nullable=True)
    total_frames = Column(Integer, default=0)
    total_detections = Column(Integer, default=0)
    total_identifications = Column(Integer, default=0)
    settings = _jsonb_column(default=dict)

    organization = relationship("Organization", back_populates="camera_sessions")
    started_by_user = relationship("User", back_populates="camera_sessions")
    camera = relationship("Camera")
    detection_logs = relationship(
        "DetectionLog", back_populates="session", cascade="all, delete-orphan"
    )
    alerts = relationship(
        "VisitorAlert", back_populates="session", cascade="all, delete-orphan"
    )


class DetectionLog(Base):
    __tablename__ = "detection_logs"

    id = _uuid_column(primary_key=True)
    session_id = _fk_uuid_column("camera_sessions.id")
    visitor_id = _fk_uuid_column("visitors.id", nullable=True)
    timestamp = Column(DateTime, default=utcnow)
    confidence = Column(Float, default=0.0)
    bbox = _jsonb_column(default=dict)  # {x1, y1, x2, y2}
    face_image_path = Column(String, nullable=True)
    identified = Column(Boolean, default=False)
    embedding_snapshot = _vector_column(512)

    session = relationship("CameraSession", back_populates="detection_logs")
    visitor = relationship("Visitor", back_populates="detection_logs")


class VisitorAlert(Base):
    __tablename__ = "visitor_alerts"

    id = _uuid_column(primary_key=True)
    session_id = _fk_uuid_column("camera_sessions.id")
    visitor_id = _fk_uuid_column("visitors.id", nullable=True)
    alert_type = Column(String, default="detected")  # detected | known | unknown
    message = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=utcnow)
    acknowledged = Column(Boolean, default=False)

    session = relationship("CameraSession", back_populates="alerts")
    visitor = relationship("Visitor")


class Watchlist(Base):
    """G2: flag specific visitors (VIP / banned / person-of-interest) so the
    recognition path raises a typed ``watchlist`` alert when they are seen."""
    __tablename__ = "watchlists"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    visitor_id = _fk_uuid_column("visitors.id")
    category = Column(String(32), default="poi")     # vip | banned | poi
    severity = Column(String(16), default="medium")  # low | medium | high | critical
    reason = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_by = _fk_uuid_column("users.id", nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    visitor = relationship("Visitor")


# ─── S19: Webhooks & API Keys ───────────────────────────────────────────────


class Webhook(Base):
    __tablename__ = "webhooks"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    url = Column(String, nullable=False)
    secret = Column(String, nullable=True)
    events = _jsonb_column(default=list)  # ["visitor.detected", "visitor.identified", ...]
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="webhooks")
    logs = relationship("WebhookLog", back_populates="webhook", cascade="all, delete-orphan")


class WebhookLog(Base):
    __tablename__ = "webhook_logs"

    id = _uuid_column(primary_key=True)
    webhook_id = _fk_uuid_column("webhooks.id")
    event = Column(String, nullable=False)
    payload = _jsonb_column(default=dict)
    response_status = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    success = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    webhook = relationship("Webhook", back_populates="logs")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    name = Column(String, nullable=False)
    key_hash = Column(String, nullable=False, unique=True)
    key_prefix = Column(String, nullable=False)  # First 8 chars for display
    permissions = _jsonb_column(default=list)  # ["read", "write", "admin"]
    is_active = Column(Boolean, default=True)
    last_used_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="api_keys")


# ─── S22: Notifications ─────────────────────────────────────────────────────


class Notification(Base):
    __tablename__ = "notifications"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    user_id = _fk_uuid_column("users.id", nullable=True)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=True)
    notification_type = Column(String, default="info")  # info | warning | alert | success
    is_read = Column(Boolean, default=False)
    link = Column(String, nullable=True)  # Optional deep link
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="notifications")
    user = relationship("User", back_populates="notifications")


# ─── S21: Camera Groups ─────────────────────────────────────────────────────


class CameraGroup(Base):
    __tablename__ = "camera_groups"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    color = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="camera_groups")
    cameras = relationship("Camera", back_populates="group")


# ─── S20: Data Retention Policy ──────────────────────────────────────────────


# ─── S26: Future Enhancements ────────────────────────────────────────────────


class FutureEnhancement(Base):
    __tablename__ = "future_enhancements"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    story_id = Column(String, nullable=False)  # US-FUT-001 … US-FUT-018
    category = Column(String, nullable=False)   # multimodal, edge, model_arch, ...
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, default="planned")  # planned | research | prototype | testing | deployed | disabled
    priority = Column(String, default="medium")  # low | medium | high | critical
    config = _jsonb_column(default=dict)         # feature-specific configuration
    metrics = _jsonb_column(default=dict)        # tracked KPIs / experiment results
    roadmap_phase = Column(String, nullable=True)  # short_term | medium_term | long_term
    enabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="future_enhancements")


class RateLimitRule(Base):
    __tablename__ = "rate_limit_rules"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    endpoint_pattern = Column(String, nullable=False, default="*")  # e.g. "/api/v1/*" or "*"
    max_requests = Column(Integer, nullable=False, default=1000)
    window_seconds = Column(Integer, nullable=False, default=3600)  # 1 hour default
    current_count = Column(Integer, default=0)
    window_start = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    
    # US-FUT-017: Burst and organization-level policy extensions
    burst_limit = Column(Integer, nullable=True)  # Max requests allowed in burst window
    burst_window_seconds = Column(Integer, nullable=True)  # Short window for burst (e.g., 60s)
    burst_current_count = Column(Integer, default=0)
    burst_window_start = Column(DateTime, nullable=True)
    cooldown_seconds = Column(Integer, default=0)  # Cooldown after burst limit exceeded
    priority = Column(Integer, default=0)  # Higher = more specific rule takes precedence
    description = Column(String, nullable=True)
    
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="rate_limit_rules")


class CarbonMetrics(Base):
    __tablename__ = "carbon_metrics"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    gpu_hours = Column(Float, default=0.0)
    cpu_hours = Column(Float, default=0.0)
    estimated_kwh = Column(Float, default=0.0)
    estimated_co2_kg = Column(Float, default=0.0)
    training_runs = Column(Integer, default=0)
    inference_count = Column(Integer, default=0)
    optimization_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="carbon_metrics")


# ─── US-FUT-012: Bias Audit History ───────────────────────────────────────────


class BiasAuditRecord(Base):
    """US-FUT-012: Persisted bias audit records for historical tracking."""
    __tablename__ = "bias_audit_records"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    
    # Audit results
    overall_fairness_score = Column(Float, default=0.0)
    demographic_parity_status = Column(String, default="unknown")  # optimal, acceptable, imbalanced
    equal_opportunity_status = Column(String, default="unknown")  # excellent, acceptable
    identification_rate = Column(Float, default=0.0)
    parity_gap = Column(Float, default=0.0)
    
    # Demographic distributions (JSON)
    gender_distribution = _jsonb_column(default=dict)
    age_group_distribution = _jsonb_column(default=dict)
    
    # Detailed results
    recommendations = _jsonb_column(default=list)
    audit_details = _jsonb_column(default=dict)
    
    # Metadata
    total_visitors = Column(Integer, default=0)
    total_logs = Column(Integer, default=0)
    audited_by = _fk_uuid_column("users.id", nullable=True)
    
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="bias_audit_records")
    user = relationship("User", back_populates="bias_audits_performed", foreign_keys=[audited_by])


# ─── US-FUT-028: Consent Management & GDPR ────────────────────────────────────


class ConsentRecord(Base):
    """US-FUT-028: First-class consent lifecycle tracking for GDPR compliance."""
    __tablename__ = "consent_records"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    
    # Subject (visitor or user)
    subject_type = Column(String, nullable=False)  # visitor | user
    subject_id = _fk_uuid_column("visitors.id", nullable=True)
    user_id = _fk_uuid_column("users.id", nullable=True)
    
    # Consent details
    consent_type = Column(String, nullable=False)  # data_processing | marketing | biometrics | third_party_sharing
    consent_version = Column(String, default="1.0")
    consent_source = Column(String, default="web")  # web | api | paper | verbal
    
    # Lifecycle
    status = Column(String, default="granted")  # granted | revoked | expired | pending
    granted_at = Column(DateTime, nullable=True)
    granted_by = _fk_uuid_column("users.id", nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = _fk_uuid_column("users.id", nullable=True)
    expires_at = Column(DateTime, nullable=True)
    
    # Retention
    retention_days = Column(Integer, default=365)
    
    # Audit
    ip_address = Column(String, nullable=True)
    user_agent = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="consent_records")
    visitor = relationship("Visitor")
    user_granted_by = relationship("User", foreign_keys=[granted_by])
    user_revoked_by = relationship("User", foreign_keys=[revoked_by])


# ─── Visitor Log Immutability ────────────────────────────────────────────────
# Prevent DELETE on visitor_logs at the ORM level.
# The manual review flow (assign_log_to_visitor) is allowed to UPDATE
# visitor_id, status, and identified fields only.
#
# For production with PostgreSQL, also create a trigger:
#   CREATE OR REPLACE FUNCTION prevent_visitor_log_delete()
#   RETURNS TRIGGER AS $$
#   BEGIN
#     RAISE EXCEPTION 'DELETE on visitor_logs is not allowed';
#   END;
#   $$ LANGUAGE plpgsql;
#
#   CREATE TRIGGER no_delete_visitor_logs
#   BEFORE DELETE ON visitor_logs
#   FOR EACH ROW EXECUTE FUNCTION prevent_visitor_log_delete();


class TrainingJob(Base):
    """Tracks model training jobs"""
    __tablename__ = "training_jobs"
    
    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    status = Column(String(50), default="pending")  # pending, started, completed, failed
    config = Column(JSONText, default={})
    accuracy = Column(Float, nullable=True)
    precision = Column(Float, nullable=True)
    recall = Column(Float, nullable=True)
    f1_score = Column(Float, nullable=True)
    metrics_history = Column(JSONText, default=[])
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    started_by = _fk_uuid_column("users.id")
    
    organization = relationship("Organization", back_populates="training_jobs")
    user = relationship("User", back_populates="training_jobs_started", foreign_keys=[started_by])


class HPOJob(Base):
    """Hyperparameter optimization jobs"""
    __tablename__ = "hpo_jobs"
    
    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    status = Column(String(50), default="pending")  # pending, running, completed, failed
    n_trials = Column(Integer, default=100)
    best_params = Column(JSONText, nullable=True)
    best_value = Column(Float, nullable=True)
    trial_results = Column(JSONText, default=[])
    created_at = Column(DateTime, default=utcnow)
    completed_at = Column(DateTime, nullable=True)
    started_by = _fk_uuid_column("users.id")
    
    organization = relationship("Organization", back_populates="hpo_jobs")
    user = relationship("User", back_populates="hpo_jobs_started", foreign_keys=[started_by])


class Ensemble(Base):
    """Model ensembles combining multiple trained models"""
    __tablename__ = "ensembles"
    
    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    name = Column(String(255), nullable=True)
    model_ids = Column(JSONText, default=[])  # List of model IDs
    weights = Column(JSONText, default=[])    # Weights for each model
    accuracy = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    created_by = _fk_uuid_column("users.id")
    
    organization = relationship("Organization", back_populates="ensembles")
    user = relationship("User", back_populates="ensembles_created", foreign_keys=[created_by])


class ActiveLearningJob(Base):
    """Tracks active learning sample selection jobs"""
    __tablename__ = "active_learning_jobs"
    
    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    strategy = Column(String(50), default="uncertainty")  # uncertainty, diversity, margin
    status = Column(String(50), default="pending")
    n_samples = Column(Integer, default=10)
    selected_samples = Column(JSONText, default=[])
    created_at = Column(DateTime, default=utcnow)
    created_by = _fk_uuid_column("users.id")
    
    organization = relationship("Organization", back_populates="active_learning_jobs")
    user = relationship("User", back_populates="active_learning_jobs_created", foreign_keys=[created_by])


# ─── S29: Alert Configuration ───────────────────────────────────────────────


class LivenessChallenge(Base):
    """Tracks interactive liveness challenge sessions.

    A challenge is started via POST /liveness/challenge/start and
    verified via POST /liveness/challenge/verify.  The row persists
    the expected challenge type, links back to the visitor-log, and
    records the verification outcome once the video is analysed.
    """
    __tablename__ = "liveness_challenges"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    visitor_log_id = _fk_uuid_column("visitor_logs.id")

    challenge_type = Column(String, nullable=False, default="blink")  # blink | head_turn | smile
    status = Column(String, default="pending")  # pending | verified | failed | expired
    instruction = Column(String, nullable=True)  # Human-readable instruction shown to user
    timeout_seconds = Column(Integer, default=30)

    # Verification results (populated by /challenge/verify)
    verified = Column(Boolean, nullable=True)
    confidence = Column(Float, nullable=True)
    details = _jsonb_column(default=dict)
    attempts = Column(Integer, default=0)

    created_at = Column(DateTime, default=utcnow)
    verified_at = Column(DateTime, nullable=True)

    organization = relationship("Organization", back_populates="liveness_challenges")
    visitor_log = relationship("VisitorLog")


class AlertConfig(Base):
    """Organization-wide alert configuration settings.
    
    Defines global alert preferences:
    - Enabled alert types
    - Default action (notify, webhook, etc)
    - Global thresholds
    """
    __tablename__ = "alert_configs"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", unique=True)
    
    # Global alert enablement
    alerts_enabled = Column(Boolean, default=True)
    email_alerts_enabled = Column(Boolean, default=True)
    webhook_alerts_enabled = Column(Boolean, default=True)
    
    # Global thresholds
    min_confidence_threshold = Column(Float, default=0.5)  # Min confidence to trigger alert
    alert_duplicate_window_seconds = Column(Integer, default=300)  # Suppress duplicates within 5min
    
    # Alert types and actions
    enabled_alert_types = _jsonb_column(default=list)  # ["known", "unknown", "liveness_failed", "anomaly"]
    default_action = Column(String, default="email")  # email | webhook | both
    
    # Metadata
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="alert_config")
    rules = relationship("AlertRule", back_populates="config", cascade="all, delete-orphan")


class AlertRule(Base):
    """Configurable alert rules for different detection scenarios.
    
    Examples:
    - Alert on any known visitor detection
    - Alert on unidentified visitor with confidence > 0.7
    - Alert on liveness failures
    - VIP visitor alerts (FUTURE-025)
    - Alert on anomalous behavior (FUTURE-020)
    """
    __tablename__ = "alert_rules"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    alert_config_id = _fk_uuid_column("alert_configs.id")
    
    # Rule metadata
    name = Column(String, nullable=False)  # e.g., "High confidence unidentified"
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    priority = Column(String, default="medium")  # low | medium | high | critical
    order = Column(Integer, default=0)  # Execution order
    
    # Rule conditions
    trigger_type = Column(String, nullable=False)  # "known" | "unknown" | "liveness_fail" | "anomaly"
    min_confidence = Column(Float, nullable=True)  # Alert only if confidence >= this
    max_confidence = Column(Float, nullable=True)  # Alert only if confidence <= this
    include_visitor_ids = _jsonb_column(default=list)  # Empty = all visitors
    include_camera_ids = _jsonb_column(default=list)  # Empty = all cameras
    
    # Advanced conditions (future)
    time_range_start = Column(String, nullable=True)  # HH:MM format for business hours
    time_range_end = Column(String, nullable=True)
    days_of_week = _jsonb_column(default=list)  # [0-6] or empty for all days
    
    # Alert action
    action = Column(String, default="email")  # email | webhook | both | notify | silence
    webhook_id = _fk_uuid_column("webhooks.id", nullable=True)  # Which webhook to call
    notification_template = Column(String, nullable=True)  # Custom message template
    
    # Rate limiting
    max_alerts_per_hour = Column(Integer, nullable=True)  # Suppress if exceeded
    
    # Metadata
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    config = relationship("AlertConfig", back_populates="rules")
    webhook = relationship("Webhook")


# ─── Visitor Log Immutability ────────────────────────────────────────────────
# Prevent DELETE on visitor_logs at the ORM level.
# The manual review flow (assign_log_to_visitor) is allowed to UPDATE
# visitor_id, status, and identified fields only.
#
# For production with PostgreSQL, also create a trigger:
#   CREATE OR REPLACE FUNCTION prevent_visitor_log_delete()
#   RETURNS TRIGGER AS $$
#   BEGIN
#     RAISE EXCEPTION 'DELETE on visitor_logs is not allowed';
#   END;
#   $$ LANGUAGE plpgsql;
#
#   CREATE TRIGGER no_delete_visitor_logs
#   BEFORE DELETE ON visitor_logs
#   FOR EACH ROW EXECUTE FUNCTION prevent_visitor_log_delete();


@event.listens_for(VisitorLog, "before_delete")
def _prevent_visitor_log_delete(mapper, connection, target):
    """Prevent deletion of visitor log entries to maintain audit trail."""
    raise RuntimeError(
        "Visitor logs are immutable and cannot be deleted. "
        "This ensures a complete audit trail of all detection events."
    )


# ─── Continual Learning Models ────────────────────────────────────────────────

class LearningSample(Base):
    __tablename__ = "learning_samples"
    
    id = _uuid_column(primary_key=True)
    visitor_id = _fk_uuid_column("visitors.id", nullable=False)
    face_image_path = Column(Text, nullable=False)
    embedding = _jsonb_column(nullable=False)
    is_positive = Column(Boolean, default=True)
    source = Column(String(50), default="manual_review")
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime, default=utcnow)
    
    visitor = relationship("Visitor")


class RecognitionFeedback(Base):
    __tablename__ = "recognition_feedback"
    
    id = _uuid_column(primary_key=True)
    log_id = _fk_uuid_column("visitor_logs.id", nullable=False)
    predicted_visitor_id = _fk_uuid_column("visitors.id", nullable=True)
    actual_visitor_id = _fk_uuid_column("visitors.id", nullable=True)
    is_correct = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    
    log = relationship("VisitorLog", foreign_keys=[log_id])
    predicted_visitor = relationship("Visitor", foreign_keys=[predicted_visitor_id])
    actual_visitor = relationship("Visitor", foreign_keys=[actual_visitor_id])

# ─── User Tracking Analytics (UTA) Models ────────────────────────────────────


class UserSession(Base):
    """Tracks real-time user sessions for live tracking and analytics."""
    __tablename__ = "user_sessions"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    visitor_id = _fk_uuid_column("visitors.id", nullable=True)
    session_start = Column(DateTime, default=utcnow)
    session_end = Column(DateTime, nullable=True)
    current_position = _jsonb_column(default=dict)  # e.g., {"camera_id": "...", "x": 0.5, "y": 0.3}
    path = _jsonb_column(default=list)  # List of positions over time
    status = Column(String, default="active")  # active | ended | paused
    last_updated = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization")
    visitor = relationship("Visitor")


class AnalyticsPrediction(Base):
    """Stores predictive analytics results for forecasting."""
    __tablename__ = "analytics_predictions"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    prediction_type = Column(String, nullable=False)  # e.g., "visitor_volume", "anomaly_rate"
    date_range = _jsonb_column(default=dict)  # {"start": "2023-01-01", "end": "2023-01-07"}
    predicted_value = Column(Float, nullable=False)
    confidence = Column(Float, nullable=True)  # 0.0-1.0
    model_used = Column(String, nullable=True)  # e.g., "prophet", "arima"
    actual_value = Column(Float, nullable=True)  # For validation after the period
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization")


# ─── S17: Data Quality & Synthetic Data ──────────────────────────────────────


class DataQualityConfig(Base):
    """Configuration for data quality auditing parameters (US-FUT-022)."""
    __tablename__ = "data_quality_configs"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)

    # Quality thresholds
    duplicate_similarity_threshold = Column(Float, default=0.95)
    blur_threshold = Column(Float, default=100.0)  # Laplacian variance
    landmark_error_threshold = Column(Float, default=10.0)
    min_image_quality_score = Column(Float, default=60.0)

    # Demographic balance targets
    demographic_balance_targets = _jsonb_column(default=lambda: {
        "age_distribution": {"18-25": 15, "25-35": 20, "35-45": 20, "45-55": 20, "55+": 25},
        "gender_distribution": {"male": 50, "female": 50},
        "ethnicity_distribution": {"Asian": 20, "African": 20, "Caucasian": 30, "Indian": 20, "Other": 10}
    })

    # Audit settings
    enable_duplicate_detection = Column(Boolean, default=True)
    enable_noise_detection = Column(Boolean, default=True)
    enable_demographic_analysis = Column(Boolean, default=True)
    auto_remediation_enabled = Column(Boolean, default=False)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="data_quality_configs")
    audit_jobs = relationship("DataQualityAuditJob", back_populates="config")


class DataQualityAuditJob(Base):
    """Tracks quality audit jobs and their results (US-FUT-022)."""
    __tablename__ = "data_quality_audit_jobs"

    id = _uuid_column(primary_key=True)
    config_id = _fk_uuid_column("data_quality_configs.id", nullable=False)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)

    # Job metadata
    dataset_name = Column(String(255), nullable=False)
    dataset_source = Column(String(50), default="training")  # training, validation, test
    total_images = Column(Integer, default=0)

    # Job status
    status = Column(String(20), default="pending")  # pending, running, completed, failed
    progress_percentage = Column(Float, default=0.0)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Results
    uniqueness_score = Column(Float, nullable=True)
    quality_score = Column(Float, nullable=True)
    balance_score = Column(Float, nullable=True)
    overall_health_score = Column(Float, nullable=True)

    # Quality findings
    duplicate_count = Column(Integer, default=0)
    duplicate_percentage = Column(Float, default=0.0)
    low_quality_count = Column(Integer, default=0)
    low_quality_percentage = Column(Float, default=0.0)
    imbalanced_demographics = Column(Boolean, default=False)

    # Detailed report
    report_data = _jsonb_column(nullable=True)

    created_at = Column(DateTime, default=utcnow)
    organization = relationship("Organization")
    config = relationship("DataQualityConfig", back_populates="audit_jobs")
    findings = relationship("QualityFinding", back_populates="audit_job")


class QualityFinding(Base):
    """Individual quality findings from audit jobs (US-FUT-022)."""
    __tablename__ = "quality_findings"

    id = _uuid_column(primary_key=True)
    audit_job_id = _fk_uuid_column("data_quality_audit_jobs.id", nullable=False)

    finding_type = Column(String(50), nullable=False)  # duplicate, noise, imbalance
    severity = Column(String(20), default="medium")  # low, medium, high, critical
    image_id = Column(String(36), nullable=True)
    related_image_ids = _jsonb_column(default=list)

    confidence_score = Column(Float, default=0.0)
    details = _jsonb_column(nullable=True)

    recommendation = Column(Text, nullable=True)
    auto_remediation_applied = Column(Boolean, default=False)

    created_at = Column(DateTime, default=utcnow)
    audit_job = relationship("DataQualityAuditJob", back_populates="findings")


class DemographicAnalysis(Base):
    """Stores demographic composition analysis (US-FUT-022)."""
    __tablename__ = "demographic_analyses"

    id = _uuid_column(primary_key=True)
    audit_job_id = _fk_uuid_column("data_quality_audit_jobs.id", nullable=False)

    # Distributions (JSON for flexibility)
    age_distribution = _jsonb_column(default=dict)
    gender_distribution = _jsonb_column(default=dict)
    ethnicity_distribution = _jsonb_column(default=dict)

    # Balance metrics
    diversity_index = Column(Float, default=0.0)
    max_demographic_skew = Column(Float, default=0.0)
    imbalance_flags = _jsonb_column(default=list)

    created_at = Column(DateTime, default=utcnow)


class QualityTrendAnalysis(Base):
    """Tracks quality metrics over time (US-FUT-022)."""
    __tablename__ = "quality_trend_analyses"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)

    month_year = Column(String(7))  # YYYY-MM format
    average_uniqueness_score = Column(Float, nullable=True)
    average_quality_score = Column(Float, nullable=True)
    average_balance_score = Column(Float, nullable=True)
    average_overall_health = Column(Float, nullable=True)

    improvement_rate = Column(Float, nullable=True)
    regression_rate = Column(Float, nullable=True)

    created_at = Column(DateTime, default=utcnow)


class SyntheticDataConfig(Base):
    """Configuration for synthetic data generation (US-FUT-019)."""
    __tablename__ = "synthetic_data_configs"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)

    gan_model = Column(String, default="stylegan3")
    output_resolution = Column(Integer, default=512)
    num_samples_per_batch = Column(Integer, default=32)
    diversity_threshold = Column(Float, default=0.7)
    total_samples_target = Column(Integer, default=1000)

    quality_threshold_fid = Column(Float, default=10.0)
    quality_threshold_lpips = Column(Float, default=0.15)
    quality_threshold_detection_confidence = Column(Float, default=0.95)

    demographic_constraints = _jsonb_column(default=dict)
    enabled = Column(Boolean, default=False)
    auto_augment_training_data = Column(Boolean, default=False)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="synthetic_data_configs")
    jobs = relationship("SynthesisJob", back_populates="config")
    images = relationship("GeneratedImage", back_populates="config")


class SynthesisJob(Base):
    """Tracks synthetic data generation jobs (US-FUT-019)."""
    __tablename__ = "synthesis_jobs"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)
    config_id = _fk_uuid_column("synthetic_data_configs.id", nullable=False)

    status = Column(String, default="pending")  # pending, processing, completed, failed, cancelled
    error_message = Column(String, nullable=True)

    total_target = Column(Integer, default=0)
    samples_generated = Column(Integer, default=0)
    samples_validated = Column(Integer, default=0)
    samples_rejected = Column(Integer, default=0)

    avg_fid = Column(Float, nullable=True)
    avg_lpips = Column(Float, nullable=True)
    avg_detection_confidence = Column(Float, nullable=True)

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    config = relationship("SyntheticDataConfig", back_populates="jobs")
    images = relationship("GeneratedImage", back_populates="job")


class GeneratedImage(Base):
    """Metadata for each generated synthetic image (US-FUT-019)."""
    __tablename__ = "generated_images"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)
    job_id = _fk_uuid_column("synthesis_jobs.id", nullable=False)
    config_id = _fk_uuid_column("synthetic_data_configs.id", nullable=False)

    file_path = Column(String, nullable=False)
    file_hash = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)

    fid_score = Column(Float, nullable=True)
    lpips_score = Column(Float, nullable=True)
    detection_confidence = Column(Float, nullable=True)

    noise_seed = Column(Integer, nullable=True)
    demographic_attributes = _jsonb_column(default=dict)

    used_in_training = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    job = relationship("SynthesisJob", back_populates="images")
    config = relationship("SyntheticDataConfig", back_populates="images")


class QualityMetricsSynthetic(Base):
    """Aggregate quality metrics for synthetic data (US-FUT-019)."""
    __tablename__ = "quality_metrics_synthetic"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)
    job_id = _fk_uuid_column("synthesis_jobs.id", nullable=False)

    measurement_timestamp = Column(DateTime, default=utcnow)
    total_samples = Column(Integer, default=0)
    valid_samples = Column(Integer, default=0)
    acceptance_rate = Column(Float, nullable=True)

    avg_fid = Column(Float, nullable=True)
    avg_lpips = Column(Float, nullable=True)
    avg_detection_confidence = Column(Float, nullable=True)

    throughput_samples_per_second = Column(Float, nullable=True)
    demographic_distribution = _jsonb_column(default=dict)

    created_at = Column(DateTime, default=utcnow)


# ─── S21: Temporal Augmentation ─────────────────────────────────────────────


class TemporalAugmentationConfig(Base):
    """Configuration for temporal face augmentation (US-FUT-021)."""
    __tablename__ = "temporal_augmentation_configs"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)

    # Expression Targets
    target_expressions = _jsonb_column(default=lambda: {
        "neutral": 1.0,
        "happy": 1.0,
        "sad": 1.0,
        "angry": 1.0,
        "surprised": 1.0,
    })

    # Interpolation Settings
    frames_per_transition = Column(Integer, default=30)
    fps = Column(Integer, default=30)
    interpolation_method = Column(String, default="bezier")

    # Quality Parameters
    min_expression_confidence = Column(Float, default=0.7)
    optical_flow_smoothness_threshold = Column(Float, default=0.8)

    # Output Settings
    output_resolution = Column(String, default="512x512")
    output_format = Column(String, default="mp4")
    compress_output = Column(Boolean, default=True)

    # Control Flags
    enabled = Column(Boolean, default=False)
    auto_augment = Column(Boolean, default=False)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="temporal_augmentation_configs")
    jobs = relationship("AugmentationJob", back_populates="config")
    sequences = relationship("GeneratedSequence", back_populates="config")


class AugmentationJob(Base):
    """Tracks temporal augmentation jobs (US-FUT-021)."""
    __tablename__ = "augmentation_jobs"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)
    config_id = _fk_uuid_column("temporal_augmentation_configs.id", nullable=False)

    # Input
    input_video_path = Column(String, nullable=True)
    input_face_id = Column(String, nullable=True)

    # Job Status
    status = Column(String, default="pending")
    error_message = Column(String, nullable=True)

    # Progress
    total_frames = Column(Integer, default=0)
    processed_frames = Column(Integer, default=0)
    generated_sequences = Column(Integer, default=0)

    # Metrics
    avg_expression_confidence = Column(Float, nullable=True)
    avg_optical_flow = Column(Float, nullable=True)

    # Timing
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    config = relationship("TemporalAugmentationConfig", back_populates="jobs")
    sequences = relationship("GeneratedSequence", back_populates="job")


class GeneratedSequence(Base):
    """Metadata for generated expression sequences (US-FUT-021)."""
    __tablename__ = "generated_sequences"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)
    job_id = _fk_uuid_column("augmentation_jobs.id", nullable=False)
    config_id = _fk_uuid_column("temporal_augmentation_configs.id", nullable=False)

    # Video File
    video_path = Column(String, nullable=False)
    file_size = Column(Integer, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    frame_count = Column(Integer, nullable=True)
    fps = Column(Integer, nullable=True)

    # Expression Information
    source_expression = Column(String, nullable=True)
    target_expression = Column(String, nullable=True)
    transition_type = Column(String, nullable=True)

    # Quality Metrics
    expression_confidence_target = Column(Float, nullable=True)
    optical_flow_smoothness = Column(Float, nullable=True)

    used_in_training = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    job = relationship("AugmentationJob", back_populates="sequences")
    config = relationship("TemporalAugmentationConfig", back_populates="sequences")


class ExpressionMetrics(Base):
    """Aggregate metrics for expression augmentation (US-FUT-021)."""
    __tablename__ = "expression_metrics"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)
    job_id = _fk_uuid_column("augmentation_jobs.id", nullable=False)

    measurement_timestamp = Column(DateTime, default=utcnow)
    expression_distribution = _jsonb_column(default=dict)
    transition_distribution = _jsonb_column(default=dict)
    avg_confidence = Column(Float, nullable=True)
    acceptance_rate = Column(Float, nullable=True)
    created_at = Column(DateTime, default=utcnow)


# ─── Model Versioning & A/B Testing ─────────────────────────────────────────


class ModelVersion(Base):
    """Tracks trained model versions with performance metrics."""
    __tablename__ = "model_versions"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)

    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    model_type = Column(String, nullable=False)  # face_recognition, liveness, behavior, etc.
    file_path = Column(String, nullable=True)

    # Performance metrics
    accuracy = Column(Float, nullable=True)
    precision = Column(Float, nullable=True)
    recall = Column(Float, nullable=True)
    f1_score = Column(Float, nullable=True)
    parameters = _jsonb_column(default=dict)

    is_active = Column(Boolean, default=True)
    is_production = Column(Boolean, default=False)

    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="model_versions")
    ab_tests_as_a = relationship("ABTestExperiment", foreign_keys="ABTestExperiment.model_a_id", back_populates="model_a")
    ab_tests_as_b = relationship("ABTestExperiment", foreign_keys="ABTestExperiment.model_b_id", back_populates="model_b")
    ab_tests_won = relationship("ABTestExperiment", foreign_keys="ABTestExperiment.winner_model_id", back_populates="winner_model")
    ab_test_results = relationship("ABTestResult", back_populates="model_version")


class ABTestExperiment(Base):
    """A/B test experiments comparing two model versions."""
    __tablename__ = "ab_test_experiments"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)

    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    model_a_id = _fk_uuid_column("model_versions.id", nullable=False)
    model_b_id = _fk_uuid_column("model_versions.id", nullable=False)
    traffic_split_percent = Column(Integer, default=50)  # percentage routed to model B

    status = Column(String, default="draft")  # draft, running, completed, cancelled
    winner_model_id = _fk_uuid_column("model_versions.id", nullable=True)

    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="ab_test_experiments")
    model_a = relationship("ModelVersion", foreign_keys=[model_a_id], back_populates="ab_tests_as_a")
    model_b = relationship("ModelVersion", foreign_keys=[model_b_id], back_populates="ab_tests_as_b")
    winner_model = relationship("ModelVersion", foreign_keys=[winner_model_id], back_populates="ab_tests_won")
    results = relationship("ABTestResult", back_populates="experiment", cascade="all, delete-orphan")


class ABTestResult(Base):
    """Individual prediction results within an A/B test experiment."""
    __tablename__ = "ab_test_results"

    id = _uuid_column(primary_key=True)
    experiment_id = _fk_uuid_column("ab_test_experiments.id", nullable=False)
    model_version_id = _fk_uuid_column("model_versions.id", nullable=False)
    visitor_log_id = _fk_uuid_column("visitor_logs.id", nullable=True)

    predicted_correctly = Column(Boolean, nullable=True)
    confidence = Column(Float, nullable=True)
    latency_ms = Column(Float, nullable=True)

    created_at = Column(DateTime, default=utcnow)

    experiment = relationship("ABTestExperiment", back_populates="results")
    model_version = relationship("ModelVersion", back_populates="ab_test_results")


# ─── Federated Learning (ENH-016) ──────────────────────────────────────────


class FederatedRound(Base):
    """Tracks a federated learning round."""
    __tablename__ = "federated_rounds"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)

    model_type = Column(String, nullable=False)
    round_number = Column(Integer, default=1)
    num_participants = Column(Integer, default=1)
    status = Column(String, default="initialized")  # initialized, collecting, aggregated, failed
    global_accuracy_before = Column(Float, nullable=True)
    global_accuracy_after = Column(Float, nullable=True)
    aggregated_weights = _jsonb_column(nullable=True)
    config = _jsonb_column(default=dict)
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization")
    updates = relationship("FederatedUpdate", back_populates="fl_round", cascade="all, delete-orphan")


class FederatedUpdate(Base):
    """Local training update from a federated participant."""
    __tablename__ = "federated_updates"

    id = _uuid_column(primary_key=True)
    round_id = _fk_uuid_column("federated_rounds.id", nullable=False)

    participant_id = Column(String, nullable=False)
    local_accuracy = Column(Float, nullable=True)
    local_loss = Column(Float, nullable=True)
    num_samples = Column(Integer, default=0)
    weight_deltas = _jsonb_column(nullable=True)
    submitted_at = Column(DateTime, default=utcnow)

    fl_round = relationship("FederatedRound", back_populates="updates")


# ─── Gait Recognition (ENH-014) ────────────────────────────────────────────


class GaitSignature(Base):
    """Stored gait signature for a visitor."""
    __tablename__ = "gait_signatures"

    id = _uuid_column(primary_key=True)
    visitor_id = _fk_uuid_column("visitors.id", nullable=False)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)

    embedding = _jsonb_column(nullable=True)  # 64-dim gait embedding
    quality_score = Column(Float, default=0.0)
    num_frames_analyzed = Column(Integer, default=0)
    features = _jsonb_column(default=dict)
    created_at = Column(DateTime, default=utcnow)

    visitor = relationship("Visitor")
    organization = relationship("Organization")


# ─── Voice Recognition (ENH-015) ───────────────────────────────────────────


class VoicePrint(Base):
    """Stored voice print for a visitor."""
    __tablename__ = "voice_prints"

    id = _uuid_column(primary_key=True)
    visitor_id = _fk_uuid_column("visitors.id", nullable=False)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)

    embedding = _jsonb_column(nullable=True)  # 128-dim voice embedding
    quality_score = Column(Float, default=0.0)
    duration_seconds = Column(Float, nullable=True)
    features = _jsonb_column(default=dict)
    created_at = Column(DateTime, default=utcnow)

    visitor = relationship("Visitor")
    organization = relationship("Organization")


# ─── Multimodal Learning (US-FUT-001) ───────────────────────────────────────


class MultimodalEmbedding(Base):
    """Combined face/audio/text embeddings with fusion metadata."""
    __tablename__ = "multimodal_embeddings"

    id = _uuid_column(primary_key=True)
    visitor_id = _fk_uuid_column("visitors.id", nullable=False)
    detection_log_id = _fk_uuid_column("detection_logs.id", nullable=True)

    face_embedding = _jsonb_column(nullable=True)  # 512-d ArcFace embedding
    audio_embedding = _jsonb_column(nullable=True)  # 128-d MFCC embedding
    text_embedding = _jsonb_column(nullable=True)  # 256-d BERT embedding
    sensor_data = _jsonb_column(default=dict)
    fusion_score = Column(Float, default=0.0)

    embedding_model_version = Column(String(50), default="1.0")
    audio_present = Column(Boolean, default=False)
    text_present = Column(Boolean, default=False)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    visitor = relationship("Visitor", back_populates="multimodal_embeddings")
    detection_log = relationship("DetectionLog")


class AudioFeature(Base):
    """Audio feature extraction metadata for multimodal learning."""
    __tablename__ = "audio_features"

    id = _uuid_column(primary_key=True)
    visitor_id = _fk_uuid_column("visitors.id", nullable=False)
    detection_log_id = _fk_uuid_column("detection_logs.id", nullable=True)

    mfcc_features = _jsonb_column(nullable=True)
    spectral_energy = Column(Float, nullable=True)
    zero_crossing_rate = Column(Float, nullable=True)
    voice_confidence = Column(Float, default=0.0)
    pitch_frequency = Column(Float, nullable=True)
    audio_duration_ms = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=utcnow)

    visitor = relationship("Visitor", back_populates="audio_features")
    detection_log = relationship("DetectionLog")


class TextBioFeature(Base):
    """Text and bio-derived embeddings for multimodal learning."""
    __tablename__ = "text_bio_features"

    id = _uuid_column(primary_key=True)
    visitor_id = _fk_uuid_column("visitors.id", nullable=False)

    name = Column(String(255), nullable=True)
    department = Column(String(255), nullable=True)
    position = Column(String(255), nullable=True)
    phone_number = Column(String(20), nullable=True)
    email = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)

    text_embedding = _jsonb_column(nullable=True)
    embedding_confidence = Column(Float, default=0.0)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    visitor = relationship("Visitor", back_populates="text_bio_features")


class MultimodalFusionConfig(Base):
    """Organization-level fusion configuration for multimodal embeddings."""
    __tablename__ = "multimodal_fusion_configs"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)

    face_weight = Column(Float, default=0.6)
    audio_weight = Column(Float, default=0.2)
    text_weight = Column(Float, default=0.1)
    sensor_weight = Column(Float, default=0.1)

    fusion_strategy = Column(String(50), default="weighted_mean")
    fusion_threshold = Column(Float, default=0.7)

    require_face = Column(Boolean, default=True)
    require_audio = Column(Boolean, default=False)
    require_text = Column(Boolean, default=False)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="multimodal_fusion_configs")


# ─── 3D Face Recognition (US-FUT-033) ──────────────────────────────────────


class ThreeDFaceData(Base):
    """Captured 3D face data and embeddings."""
    __tablename__ = "three_d_face_data"

    id = _uuid_column(primary_key=True)
    visitor_id = _fk_uuid_column("visitors.id", nullable=False)
    detection_log_id = _fk_uuid_column("detection_logs.id", nullable=True)

    depth_map_path = Column(String(512), nullable=True)
    point_cloud_path = Column(String(512), nullable=True)
    face_mesh = _jsonb_column(nullable=True)
    texture_map_path = Column(String(512), nullable=True)

    face_width_mm = Column(Float, nullable=True)
    face_height_mm = Column(Float, nullable=True)
    face_depth_mm = Column(Float, nullable=True)
    forehead_width_mm = Column(Float, nullable=True)
    nose_height_mm = Column(Float, nullable=True)

    embedding_3d = _jsonb_column(nullable=True)
    embedding_confidence = Column(Float, default=0.0)

    capture_quality_score = Column(Float, default=0.0)
    mesh_density = Column(Integer, nullable=True)
    depth_map_resolution = Column(String(20), nullable=True)

    created_at = Column(DateTime, default=utcnow)

    visitor = relationship("Visitor", back_populates="three_d_face_data")
    detection_log = relationship("DetectionLog")


class ThreeDFaceComparison(Base):
    """Comparison result between two 3D face captures."""
    __tablename__ = "three_d_face_comparisons"

    id = _uuid_column(primary_key=True)
    face_data_1_id = _fk_uuid_column("three_d_face_data.id", nullable=False)
    face_data_2_id = _fk_uuid_column("three_d_face_data.id", nullable=False)

    euclidean_distance = Column(Float, nullable=True)
    cosine_similarity = Column(Float, nullable=True)
    l2_distance = Column(Float, nullable=True)
    shape_similarity = Column(Float, nullable=True)
    texture_similarity = Column(Float, nullable=True)
    geometric_liveness_score = Column(Float, nullable=True)

    match_confidence = Column(Float, default=0.0)
    is_same_person = Column(Boolean, default=False)

    created_at = Column(DateTime, default=utcnow)

    face_data_1 = relationship("ThreeDFaceData", foreign_keys=[face_data_1_id])
    face_data_2 = relationship("ThreeDFaceData", foreign_keys=[face_data_2_id])


# ─── SSO/OAuth (ENH-012) ───────────────────────────────────────────────────


class SSOConnection(Base):
    """SSO provider connection linked to a user account."""
    __tablename__ = "sso_connections"

    id = _uuid_column(primary_key=True)
    user_id = _fk_uuid_column("users.id", nullable=False)

    provider = Column(String, nullable=False)  # google, github
    provider_user_id = Column(String, nullable=True)
    provider_email = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    user = relationship("User")


# ─── Phase 3: SAML/SSO Provider Configuration ───────────────────────────────


class SSOProvider(Base):
    """SAML/OAuth2/OpenID provider configuration for organization (US-ENT-010)."""
    __tablename__ = "sso_providers"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)
    
    provider_type = Column(String(50), nullable=False)  # 'saml', 'oauth2', 'openid'
    provider_name = Column(String(255), nullable=False)
    entity_id = Column(String(255), nullable=True)
    sso_url = Column(String(255), nullable=True)
    certificate = Column(Text(), nullable=True)
    attribute_mappings = _jsonb_column(default=dict)  # {email: 'http://...', name: 'http://...'}
    active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="sso_providers")
    sessions = relationship("SSOSession", back_populates="provider", cascade="all, delete-orphan")


class SSOSession(Base):
    """SSO session tracking for user authentication (US-ENT-010)."""
    __tablename__ = "sso_sessions"

    id = _uuid_column(primary_key=True)
    user_id = _fk_uuid_column("users.id", nullable=False)
    provider_id = _fk_uuid_column("sso_providers.id", nullable=False)
    
    token = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=True)

    user = relationship("User")
    provider = relationship("SSOProvider", back_populates="sessions")


# ─── Phase 3: LDAP Configuration ───────────────────────────────────────────


class LdapConfig(Base):
    """LDAP configuration for directory sync (LD-001 to LD-004)."""
    __tablename__ = "ldap_configs"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)

    ldap_server = Column(String(255), nullable=False)
    ldap_port = Column(Integer, default=389)
    use_ssl = Column(Boolean, default=False)
    bind_dn = Column(String(255), nullable=True)
    bind_password = Column(Text, nullable=True)
    user_search_base = Column(String(255), nullable=False)
    group_search_base = Column(String(255), nullable=True)
    user_attribute = Column(String(100), default="uid")
    group_attribute = Column(String(100), default="cn")
    active = Column(Boolean, default=False)
    last_sync_at = Column(DateTime, nullable=True)
    last_sync_status = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="ldap_configs")
    sync_logs = relationship("LdapSyncLog", back_populates="ldap_config", cascade="all, delete-orphan")


class LdapSyncLog(Base):
    """Tracks LDAP sync runs and their outcomes."""
    __tablename__ = "ldap_sync_logs"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)
    ldap_config_id = _fk_uuid_column("ldap_configs.id", nullable=False)

    users_synced = Column(Integer, default=0)
    groups_synced = Column(Integer, default=0)
    users_disabled = Column(Integer, default=0)
    status = Column(String(20), default="pending")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    organization = relationship("Organization", back_populates="ldap_sync_logs")
    ldap_config = relationship("LdapConfig", back_populates="sync_logs")


# ─── Phase 3: GDPR Compliance ───────────────────────────────────────────────


class GDPRRequest(Base):
    """GDPR data export and deletion requests (US-SEC-015)."""
    __tablename__ = "gdpr_requests"

    id = _uuid_column(primary_key=True)
    visitor_id = _fk_uuid_column("visitors.id", nullable=False)
    
    request_type = Column(String(50), nullable=False)  # 'data_export', 'data_deletion', 'consent_withdrawal'
    status = Column(String(20), default="pending")  # 'pending', 'processing', 'completed'
    request_date = Column(DateTime, default=utcnow)
    completion_date = Column(DateTime, nullable=True)
    response_file_url = Column(String(255), nullable=True)
    notes = Column(Text(), nullable=True)

    visitor = relationship("Visitor")


class VisitorConsent(Base):
    """Consent tracking for GDPR / APP compliance (US-SEC-015).

    Extended in migration 018 to satisfy the audit requirement that every
    biometric-template enrolment is linked to a contemporaneous, evidenced
    consent record. New columns:

    * ``organization_id`` — explicit FK so consent can be queried without
      the visitor join; required for "find all consents for org" reports.
    * ``data_subject_email`` — lets us match consent to a person before a
      Visitor row exists (e.g. pre-enrolment intake form).
    * ``lawful_basis`` — Art 6 / Art 9 lawful basis label
      (e.g. ``art6_consent``, ``art6_legitimate_interest``,
      ``art9_explicit_consent``, ``app3_3_sensitive_information``).
    * ``consent_text_version`` — semver of the consent notice the subject
      was shown; required to evidence what they actually agreed to.
    * ``capture_method`` — ``web_form``, ``kiosk``, ``paper``, ``api``.
    * ``ip_address``, ``user_agent`` — capture audit trail.
    * ``evidence_url`` — link to a signed PDF / scanned form / e-sign
      receipt held in object storage.
    """
    __tablename__ = "visitor_consent"

    id = _uuid_column(primary_key=True)
    visitor_id = _fk_uuid_column("visitors.id", nullable=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=True)
    data_subject_email = Column(String(255), nullable=True)

    consent_type = Column(String(50), nullable=False)  # 'face_recognition', 'tracking', 'analytics'
    lawful_basis = Column(String(64), nullable=True)
    consent_text_version = Column(String(32), nullable=True)
    capture_method = Column(String(32), nullable=True)
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    evidence_url = Column(String(1024), nullable=True)

    consent_given = Column(Boolean, nullable=False)
    consent_date = Column(DateTime, default=utcnow)
    consent_withdrawn_date = Column(DateTime, nullable=True)

    visitor = relationship("Visitor")


class DataRetentionPolicy(Base):
    """Data retention policies per organization (US-SEC-015)."""
    __tablename__ = "data_retention_policies"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id", nullable=False)

    # Keep the legacy physical column names for SQLite/PostgreSQL compatibility
    # while exposing the logical API names used by the compliance endpoints.
    entity_type = Column("data_type", String(50), nullable=False)
    retention_days = Column(Integer, nullable=False)
    auto_delete = Column("auto_delete_enabled", Boolean, default=True)
    last_cleanup_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

    data_type = synonym("entity_type")
    auto_delete_enabled = synonym("auto_delete")

    organization = relationship("Organization", back_populates="retention_policies")


# ─── MP: Missing Person Cases, Evidence Intake & Safe Reports ────────────────
#
# A missing-person case is the anchor record. Everything a member of the
# public, a family member, or an investigator sends in — an email, an uploaded
# photo, CCTV footage, a scanned document — lands as a MissingPersonSubmission
# with zero or more MissingPersonAttachment rows, and is linked back to the
# correct case either automatically (case reference, per-case intake token,
# email thread, name match, face match) or manually from the triage queue.
#
# `visitor_id` optionally links the case to a Visitor record so the existing
# recognition path (api/camera.py) can raise sightings for the missing person
# using the reference photos enrolled on the case.


class DisasterEvent(Base):
    """Tenant-scoped disaster response operation, e.g. 2026 Nepal Flood Response."""
    __tablename__ = "disaster_events"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    name = Column(String(255), nullable=False)
    event_type = Column(String(64), nullable=False)
    affected_areas = _jsonb_column(default=list)
    starts_at = Column(DateTime, nullable=False, default=utcnow)
    ends_at = Column(DateTime, nullable=True)
    status = Column(String(32), nullable=False, default="active")
    notes = Column(Text, nullable=True)
    created_by = _fk_uuid_column("users.id", nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class MissingPersonCase(Base):
    """MP1: a reported missing person and the identifying detail about them."""
    __tablename__ = "missing_person_cases"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    disaster_event_id = _fk_uuid_column("disaster_events.id", nullable=True, index=True)
    # Human-quotable reference printed on posters and used to route email
    # (e.g. "MP-2026-0042"). Unique per organization.
    case_reference = Column(String(32), nullable=False, index=True)
    # Opaque per-case token used for plus-addressed intake mailboxes
    # (tips+<intake_token>@...) and for public tip links. Never guessable.
    intake_token = Column(String(64), nullable=False, index=True)
    # Optional link to the biometric Visitor record holding reference face
    # embeddings, so live recognition can flag a sighting.
    visitor_id = _fk_uuid_column("visitors.id", nullable=True)

    # -- Identity ------------------------------------------------------------
    full_name = Column(String(255), nullable=False)
    nickname = Column(String(120), nullable=True)
    age = Column(Integer, nullable=True)
    date_of_birth = Column(DateTime, nullable=True)
    gender = Column(String(32), nullable=True)

    # -- Physical description ------------------------------------------------
    height_cm = Column(Float, nullable=True)
    weight_kg = Column(Float, nullable=True)
    build = Column(String(64), nullable=True)
    hair_color = Column(String(64), nullable=True)
    eye_color = Column(String(64), nullable=True)
    complexion = Column(String(64), nullable=True)
    # Scars, tattoos, birthmarks, prosthetics, medical devices.
    distinguishing_marks = Column(Text, nullable=True)
    clothing_description = Column(Text, nullable=True)
    # Medical conditions / medication needs that raise urgency.
    medical_notes = Column(Text, nullable=True)
    languages_spoken = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)

    # -- Last known location -------------------------------------------------
    last_seen_location = Column(String(512), nullable=True)
    last_seen_latitude = Column(Float, nullable=True)
    last_seen_longitude = Column(Float, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    last_seen_wearing = Column(Text, nullable=True)

    # -- Case handling -------------------------------------------------------
    # open | found_safe | found_deceased | closed | withdrawn
    status = Column(String(32), default="open", index=True)
    # low | medium | high | critical - critical drives immediate alerting.
    priority = Column(String(16), default="medium")
    # Whether the case may be shown on a public-facing appeal page.
    is_public = Column(Boolean, default=False)
    # Police / partner-agency reference so submissions can be handed over.
    external_reference = Column(String(128), nullable=True)

    # -- Reporter (family member / guardian raising the case) ----------------
    reporter_name = Column(String(255), nullable=True)
    reporter_email = Column(String(255), nullable=True)
    reporter_phone = Column(String(64), nullable=True)
    reporter_relationship = Column(String(120), nullable=True)
    # Set when the reporter confirmed they are authorised to share the
    # person's photo and identifying data (GDPR Art 6 / Art 9 evidence).
    reporter_consent_given = Column(Boolean, default=False)

    # -- Resolution ----------------------------------------------------------
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)
    resolved_by = _fk_uuid_column("users.id", nullable=True)

    case_metadata = _jsonb_column(default=dict)
    created_by = _fk_uuid_column("users.id", nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    visitor = relationship("Visitor")
    submissions = relationship(
        "MissingPersonSubmission",
        back_populates="case",
        cascade="all, delete-orphan",
    )
    attachments = relationship(
        "MissingPersonAttachment",
        back_populates="case",
        cascade="all, delete-orphan",
    )
    updates = relationship(
        "MissingPersonCaseUpdate",
        back_populates="case",
        cascade="all, delete-orphan",
    )


class MissingPersonSubmission(Base):
    """MP2: one inbound piece of information about a missing person.

    Arrives from a web form, an email, or the authenticated API. A submission
    with a NULL ``case_id`` is unrouted and sits in the triage queue until an
    investigator assigns it - nothing is silently discarded.
    """
    __tablename__ = "missing_person_submissions"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    case_id = _fk_uuid_column("missing_person_cases.id", nullable=True, index=True)

    # web_form | email | api | internal | public_form
    source = Column(String(32), default="web_form")
    # sighting | evidence | safe_report | information | duplicate_report
    submission_type = Column(String(32), default="information")

    submitter_name = Column(String(255), nullable=True)
    submitter_email = Column(String(255), nullable=True)
    submitter_phone = Column(String(64), nullable=True)
    submitter_relationship = Column(String(120), nullable=True)
    is_anonymous = Column(Boolean, default=False)

    subject = Column(String(512), nullable=True)
    message = Column(Text, nullable=True)

    # Where/when the submitter claims to have seen the person.
    sighting_location = Column(String(512), nullable=True)
    sighting_latitude = Column(Float, nullable=True)
    sighting_longitude = Column(Float, nullable=True)
    sighting_at = Column(DateTime, nullable=True)

    # -- Email provenance (populated for source="email") ---------------------
    email_message_id = Column(String(512), nullable=True, index=True)
    email_in_reply_to = Column(String(512), nullable=True)
    email_from = Column(String(320), nullable=True)
    email_to = Column(String(512), nullable=True)

    # -- How this submission got linked to its case --------------------------
    # case_reference | intake_token | email_thread | name_match | face_match
    # | manual | explicit_id | unmatched
    match_method = Column(String(32), default="unmatched")
    match_confidence = Column(Float, default=0.0)
    # Candidate cases considered by the auto-router, kept so a reviewer can
    # see why a submission landed where it did.
    match_candidates = _jsonb_column(default=list)

    # new | triage | reviewing | verified | rejected | duplicate
    status = Column(String(24), default="new", index=True)
    review_notes = Column(Text, nullable=True)
    reviewed_by = _fk_uuid_column("users.id", nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    submission_metadata = _jsonb_column(default=dict)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    case = relationship("MissingPersonCase", back_populates="submissions")
    attachments = relationship(
        "MissingPersonAttachment",
        back_populates="submission",
        cascade="all, delete-orphan",
    )


class MissingPersonAttachment(Base):
    """MP3: a file attached to a case or submission.

    Covers reference photos, public sighting photos, CCTV/camera footage,
    and documents (police reports, medical letters, scans). ``case_id`` is
    denormalised from the parent submission so case evidence can be listed
    without a join, and stays NULL while the submission is untriaged.
    """
    __tablename__ = "missing_person_attachments"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    case_id = _fk_uuid_column("missing_person_cases.id", nullable=True, index=True)
    submission_id = _fk_uuid_column("missing_person_submissions.id", nullable=True, index=True)

    # photo | reference_photo | cctv_footage | video | document | audio | other
    file_kind = Column(String(32), default="photo")
    file_url = Column(String(1024), nullable=False)
    original_filename = Column(String(512), nullable=True)
    content_type = Column(String(128), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    # SHA-256 of the stored bytes - used to collapse the same photo mailed in
    # by ten different people into one piece of evidence.
    checksum_sha256 = Column(String(64), nullable=True, index=True)

    # Where the footage came from, when it was recorded.
    captured_at = Column(DateTime, nullable=True)
    capture_location = Column(String(512), nullable=True)
    camera_id = _fk_uuid_column("cameras.id", nullable=True)

    # Set once the file has been pushed through the AI face pipeline.
    face_indexed = Column(Boolean, default=False)
    face_data_id = _fk_uuid_column("face_data.id", nullable=True)
    face_match_score = Column(Float, nullable=True)
    processing_notes = Column(Text, nullable=True)

    uploaded_by = _fk_uuid_column("users.id", nullable=True)
    created_at = Column(DateTime, default=utcnow)

    case = relationship("MissingPersonCase", back_populates="attachments")
    submission = relationship("MissingPersonSubmission", back_populates="attachments")


class MissingPersonCaseUpdate(Base):
    """MP4: append-only case timeline - status changes, safe reports, notes.

    A "found safe" report from the public lands here as an unverified
    ``safe_report`` entry; the case status only moves once an authorised
    user verifies it. That keeps a hoax or a mistaken sighting from closing
    a live case.
    """
    __tablename__ = "missing_person_case_updates"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    case_id = _fk_uuid_column("missing_person_cases.id", index=True)
    submission_id = _fk_uuid_column("missing_person_submissions.id", nullable=True)

    # status_change | safe_report | sighting | note | evidence_added
    # | case_created | assignment
    update_type = Column(String(32), default="note")
    previous_status = Column(String(32), nullable=True)
    new_status = Column(String(32), nullable=True)
    notes = Column(Text, nullable=True)

    # Who reported it - public safe reports carry no user id.
    reported_by_name = Column(String(255), nullable=True)
    reported_by_contact = Column(String(255), nullable=True)
    reported_by_relationship = Column(String(120), nullable=True)

    # A public safe report is untrusted until an authorised user verifies it.
    is_verified = Column(Boolean, default=False)
    verified_by = _fk_uuid_column("users.id", nullable=True)
    verified_at = Column(DateTime, nullable=True)

    created_by = _fk_uuid_column("users.id", nullable=True)
    created_at = Column(DateTime, default=utcnow)

    case = relationship("MissingPersonCase", back_populates="updates")


class LocatedPerson(Base):
    """Private staff record for a disaster survivor or unidentified person."""
    __tablename__ = "located_persons"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    disaster_event_id = _fk_uuid_column("disaster_events.id", nullable=True, index=True)
    record_reference = Column(String(48), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="identity_unknown")
    full_name = Column(String(255), nullable=True)
    approximate_age = Column(Integer, nullable=True)
    gender = Column(String(32), nullable=True)
    found_location = Column(String(512), nullable=True)
    found_at = Column(DateTime, nullable=True)
    facility_name = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    photo_url = Column(String(1024), nullable=True)
    photo_content_type = Column(String(128), nullable=True)
    submitted_by = _fk_uuid_column("users.id", nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class MissingPersonPossibleMatch(Base):
    """AI suggestion. A human reviewer must confirm or reject it."""
    __tablename__ = "missing_person_possible_matches"

    id = _uuid_column(primary_key=True)
    organization_id = _fk_uuid_column("organizations.id")
    located_person_id = _fk_uuid_column("located_persons.id", index=True)
    case_id = _fk_uuid_column("missing_person_cases.id", index=True)
    confidence = Column(Float, nullable=False)
    match_reasons = _jsonb_column(default=list)
    status = Column(String(24), nullable=False, default="pending")
    reviewer_notes = Column(Text, nullable=True)
    reviewed_by = _fk_uuid_column("users.id", nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
