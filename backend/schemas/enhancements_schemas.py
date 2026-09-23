"""
Pydantic schemas for Enhancement APIs
"""
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class EnhancementPrioritySchema(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EnhancementStatusSchema(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ENABLED = "enabled"
    DISABLED = "disabled"


class EnhancementCategorySchema(str, Enum):
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


# ========== ENHANCEMENT SCHEMAS ==========
class EnhancementCreate(BaseModel):
    name: str
    description: Optional[str] = None
    category: str
    priority: EnhancementPrioritySchema = EnhancementPrioritySchema.MEDIUM
    estimated_effort_weeks: Optional[int] = None
    phase: Optional[int] = None


class EnhancementUpdate(BaseModel):
    status: Optional[EnhancementStatusSchema] = None
    enabled: Optional[bool] = None
    priority: Optional[EnhancementPrioritySchema] = None


class EnhancementResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    category: str
    priority: str
    status: str
    enabled: bool
    estimated_effort_weeks: Optional[int]
    phase: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ========== CONFIG SCHEMAS ==========
class AugmentationConfigSchema(BaseModel):
    rotation_enabled: bool = True
    rotation_range: int = 30
    flip_enabled: bool = True
    scale_enabled: bool = True
    scale_range: List[float] = [0.8, 1.2]
    color_jitter_enabled: bool = True
    color_jitter_intensity: float = 0.3
    cutout_enabled: bool = False
    quality_checks_enabled: bool = True
    demographic_balancing: bool = False


class ModelArchConfigSchema(BaseModel):
    vit_enabled: bool = False
    cnn_vit_hybrid: bool = False
    ensemble_enabled: bool = False
    ensemble_strategy: str = "voting"  # voting, averaging
    num_models: int = 3


class TrainingConfigSchema(BaseModel):
    self_supervised_enabled: bool = False
    continual_learning_enabled: bool = False
    learning_rate: float = 0.001
    batch_size: int = 32
    hpo_enabled: bool = False
    hpo_strategy: str = "bayesian"  # bayesian, grid, random


class RobustnessConfigSchema(BaseModel):
    adversarial_training_enabled: bool = False
    defense_enabled: bool = False
    occlusion_handling_enabled: bool = False
    confidence_threshold: float = 0.6


class AccuracyConfigSchema(BaseModel):
    multi_angle_enabled: bool = True
    consensus_voting_enabled: bool = False
    temporal_smoothing_enabled: bool = False
    num_angles: int = 3


class PerformanceConfigSchema(BaseModel):
    target_latency_ms: int = 1000
    target_fps: int = 30
    gpu_enabled: bool = True
    batch_size: int = 8
    precision: str = "FP32"  # FP32, FP16, INT8


class EnhancementConfigResponse(BaseModel):
    id: str
    category: str
    config_data: Dict[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ========== METRICS SCHEMAS ==========
class MetricResponse(BaseModel):
    id: str
    metric_name: str
    current_value: Optional[float]
    target_value: Optional[float]
    unit: Optional[str]
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)

class MetricsListResponse(BaseModel):
    metrics: List[MetricResponse]
    summary: Dict[str, Any]


# ========== BIAS AUDIT SCHEMAS ==========
class BiasAuditResponse(BaseModel):
    id: str
    demographic_group: str
    accuracy_rate: Optional[float]
    false_positive_rate: Optional[float]
    false_negative_rate: Optional[float]
    inference_count: int
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)

class BiasAuditListResponse(BaseModel):
    audits: List[BiasAuditResponse]
    summary: Dict[str, Any]


# ========== EXPLAINABILITY SCHEMAS ==========
class ExplainabilityResponse(BaseModel):
    id: str
    detection_id: Optional[str]
    method: str
    explanation_data: Dict[str, Any]
    confidence_breakdown: Dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ========== RATE LIMIT SCHEMAS ==========
class RateLimitCreate(BaseModel):
    endpoint_pattern: str
    max_requests: int
    time_window_seconds: int


class RateLimitUpdate(BaseModel):
    max_requests: Optional[int] = None
    time_window_seconds: Optional[int] = None
    active: Optional[bool] = None


class RateLimitResponse(BaseModel):
    id: str
    endpoint_pattern: str
    max_requests: int
    time_window_seconds: int
    active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ========== SUSTAINABILITY SCHEMAS ==========
class SustainabilityMetricResponse(BaseModel):
    id: str
    gpu_hours: float
    cpu_hours: float
    kwh_consumed: float
    co2_kg: float
    training_runs: int
    inference_count: int
    period_start: datetime
    period_end: datetime
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# ========== ROADMAP SCHEMAS ==========
class RoadmapItem(BaseModel):
    task_id: str
    task_name: str
    phase: int
    effort_weeks: int
    status: str
    priority: str


class RoadmapPhase(BaseModel):
    phase_number: int
    phase_name: str
    duration_months: str
    items: List[RoadmapItem]
    total_items: int


class RoadmapResponse(BaseModel):
    phases: List[RoadmapPhase]
    total_enhancements: int


# ========== PRIORITY MATRIX SCHEMAS ==========
class PriorityMatrixItem(BaseModel):
    id: str
    name: str
    priority: str
    impact: str
    effort: str
    roi: float


class PriorityMatrixResponse(BaseModel):
    critical: List[PriorityMatrixItem]
    high: List[PriorityMatrixItem]
    medium: List[PriorityMatrixItem]
    low: List[PriorityMatrixItem]


