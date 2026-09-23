"""
Enhancement Models for Future Features Management
"""
from datetime import datetime, timezone
from enum import Enum
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, ForeignKey, Text
from sqlalchemy.orm import relationship
from db.base import Base


def utcnow():
    return datetime.now(timezone.utc)


class EnhancementStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ENABLED = "enabled"
    DISABLED = "disabled"


class EnhancementPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EnhancementCategory(str, Enum):
    AUGMENTATION = "augmentation"
    MODEL_ARCHITECTURE = "model_architecture"
    TRAINING = "training"
    ROBUSTNESS = "robustness"
    BIAS_FAIRNESS = "bias_fairness"
    PRIVACY = "privacy"
    SCALABILITY = "scalability"
    CV_ADVANCED = "cv_advanced"
    SYSTEM = "system"
    UX = "ux"
    EMERGING = "emerging"
    EXPLAINABILITY = "explainability"


class Enhancement(Base):
    """Enhancement Feature Model"""
    __tablename__ = "enhancements"

    id = Column(String, primary_key=True)  # US-FUT-001, etc
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False)
    priority = Column(String(20), default=EnhancementPriority.MEDIUM)
    status = Column(String(20), default=EnhancementStatus.PLANNED)
    enabled = Column(Boolean, default=False)
    estimated_effort_weeks = Column(Integer, nullable=True)
    phase = Column(Integer, nullable=True)  # 1-4
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    config = Column(JSON, default={})


class EnhancementConfig(Base):
    """Configuration for Enhancement Modules"""
    __tablename__ = "enhancement_configs"

    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False)
    category = Column(String(50), nullable=False)
    config_data = Column(JSON, default={})
    enabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Metric(Base):
    """System Metrics and KPIs"""
    __tablename__ = "metrics"

    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False)
    metric_name = Column(String(255), nullable=False)
    current_value = Column(Float, nullable=True)
    target_value = Column(Float, nullable=True)
    unit = Column(String(100), nullable=True)
    timestamp = Column(DateTime, default=utcnow)
    config = Column(JSON, default={})


class BiasAudit(Base):
    """Bias and Fairness Audit Results"""
    __tablename__ = "bias_audits"

    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False)
    demographic_group = Column(String(100), nullable=False)
    accuracy_rate = Column(Float, nullable=True)
    false_positive_rate = Column(Float, nullable=True)
    false_negative_rate = Column(Float, nullable=True)
    inference_count = Column(Integer, default=0)
    timestamp = Column(DateTime, default=utcnow)
    config = Column(JSON, default={})


class ExplainabilityResult(Base):
    """Explainable AI (XAI) Analysis Results"""
    __tablename__ = "explainability_results"

    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False)
    detection_id = Column(String, nullable=True)
    method = Column(String(50))  # SHAP, LIME, attention_map
    explanation_data = Column(JSON, default={})
    confidence_breakdown = Column(JSON, default={})
    created_at = Column(DateTime, default=utcnow)


class RateLimit(Base):
    """API Rate Limiting Rules"""
    __tablename__ = "rate_limits"

    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False)
    endpoint_pattern = Column(String(255), nullable=False)
    max_requests = Column(Integer, nullable=False)
    time_window_seconds = Column(Integer, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class SustainabilityMetric(Base):
    """Carbon Footprint and Sustainability Metrics"""
    __tablename__ = "sustainability_metrics"

    id = Column(String, primary_key=True)
    organization_id = Column(String, ForeignKey("organizations.id"), nullable=False)
    gpu_hours = Column(Float, default=0.0)
    cpu_hours = Column(Float, default=0.0)
    kwh_consumed = Column(Float, default=0.0)
    co2_kg = Column(Float, default=0.0)
    training_runs = Column(Integer, default=0)
    inference_count = Column(Integer, default=0)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utcnow)
