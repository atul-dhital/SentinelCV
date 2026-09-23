from datetime import datetime, timedelta, timezone
"""S26-S27: Future Enhancements in Computer Vision — management, configuration,
roadmap, priority matrix, metrics targets, and category-specific configuration."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from db.base import get_db
from db.base import SQLALCHEMY_DATABASE_URL
from models import models
from schemas import schemas
from services import (
    user_service,
    visitor_service,
    reid_service,
    mlflow_registry_service,
    behavior_analytics_service,
    vision_analytics_service,
    video_queue_service,
)
from services.redis_service import get_redis_service
from core.security import get_current_user
from core.runtime_registry import load_runtime_registry, save_runtime_registry
from typing import Any, Dict, List, Optional
from uuid import UUID
from collections import Counter
import asyncio
import base64
import httpx
import mimetypes
import math
import os
import re
import time
from core.paths import data_path
from services.benchmark_service import load_benchmark_summary, run_baseline_benchmark

router = APIRouter(prefix="/future-enhancements", tags=["Future Enhancements"])

# Configuration
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001")

# ── Default enhancement catalogue (seeded on first list if empty) ────────────

_DEFAULT_ENHANCEMENTS = [
    # --- Original S26 enhancements (US-FUT-001 to US-FUT-018) ---
    {"story_id": "US-FUT-001", "category": "multimodal", "title": "Multimodal Learning Integration",
     "description": "Combine facial recognition with gait analysis, voice recognition, and behavioral patterns for robust identification.",
     "roadmap_phase": "long_term", "priority": "high", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-002", "category": "edge", "title": "Edge Computing Deployment",
     "description": "Deploy lightweight models on edge devices for real-time processing without cloud dependency.",
     "roadmap_phase": "medium_term", "priority": "high", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-003", "category": "edge", "title": "Model Optimization for Edge",
     "description": "Apply quantization, pruning, and knowledge distillation to reduce model size for edge deployment.",
     "roadmap_phase": "medium_term", "priority": "medium", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-004", "category": "model_arch", "title": "Vision Transformer Integration",
     "description": "Explore ViT and DeiT architectures as alternatives to CNN-based face recognition.",
     "roadmap_phase": "medium_term", "priority": "medium", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-005", "category": "model_arch", "title": "Ensemble Methods",
     "description": "Combine multiple model predictions for improved accuracy and robustness.",
     "roadmap_phase": "medium_term", "priority": "medium", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-006", "category": "learning", "title": "Self-Supervised Learning",
     "description": "Leverage unlabeled data to pre-train feature extractors and reduce annotation requirements.",
     "roadmap_phase": "long_term", "priority": "medium", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-007", "category": "learning", "title": "Continual Learning Pipeline",
     "description": "Enable models to learn from new data without catastrophic forgetting of previous knowledge.",
     "roadmap_phase": "medium_term", "priority": "high", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-008", "category": "augmentation", "title": "Advanced Data Augmentation (CutMix/MixUp)",
     "description": "Apply CutMix, MixUp, and CutOut techniques to improve model generalization.",
     "roadmap_phase": "short_term", "priority": "medium", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-009", "category": "augmentation", "title": "Synthetic Data Generation (GANs)",
     "description": "Use generative adversarial networks to create synthetic training data for underrepresented classes.",
     "roadmap_phase": "long_term", "priority": "low", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-010", "category": "optimization", "title": "Bayesian Hyperparameter Optimization",
     "description": "Use Bayesian optimization for automated hyperparameter tuning of recognition models.",
     "roadmap_phase": "short_term", "priority": "medium", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-011", "category": "robustness", "title": "Adversarial Defense Mechanisms",
     "description": "Implement adversarial training and input validation to defend against adversarial attacks.",
     "roadmap_phase": "medium_term", "priority": "high", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-012", "category": "fairness", "title": "Bias Detection & Mitigation",
     "description": "Detect and mitigate demographic bias in face recognition models for equitable performance.",
     "roadmap_phase": "short_term", "priority": "critical", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-013", "category": "privacy", "title": "Differential Privacy",
     "description": "Apply differential privacy mechanisms to protect individual identity during model training.",
     "roadmap_phase": "medium_term", "priority": "high", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-014", "category": "emerging", "title": "Quantum Computing Exploration",
     "description": "Research quantum computing applications for faster feature extraction and matching.",
     "roadmap_phase": "future_ready", "priority": "low", "status": "research", "enabled": False},
    {"story_id": "US-FUT-015", "category": "emerging", "title": "Explainable AI (XAI)",
     "description": "Implement Grad-CAM, LIME, and SHAP explanations for model decision transparency.",
     "roadmap_phase": "short_term", "priority": "high", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-016", "category": "integration", "title": "Federated Learning",
     "description": "Train models across distributed sites without sharing raw biometric data.",
     "roadmap_phase": "long_term", "priority": "medium", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-017", "category": "integration", "title": "API Rate Limiting & Scalability",
     "description": "Implement intelligent rate limiting and horizontal scaling for high-traffic deployments.",
     "roadmap_phase": "short_term", "priority": "high", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-018", "category": "sustainability", "title": "Carbon-Neutral Training",
     "description": "Track and optimize energy consumption to achieve carbon-neutral model training operations.",
     "roadmap_phase": "medium_term", "priority": "medium", "status": "deployed", "enabled": True},

    # --- S27: New enhancements from FUTURE_ENHANCEMENTS.md ---
    # Section 3.1 - Data Quality
    {"story_id": "US-FUT-019", "category": "augmentation", "title": "Adversarial Training Augmentation",
     "description": "Train models with adversarial examples to improve robustness against input perturbations.",
     "roadmap_phase": "short_term", "priority": "medium", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-020", "category": "augmentation", "title": "Random Erasing & Geometric Transforms",
     "description": "Randomly erase image regions and apply geometric transforms (rotation, scaling, flipping) for occlusion handling and angle diversity.",
     "roadmap_phase": "short_term", "priority": "medium", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-021", "category": "augmentation", "title": "Color Jittering & Lighting Variation",
     "description": "Apply brightness, contrast, and saturation jittering to handle diverse lighting conditions.",
     "roadmap_phase": "short_term", "priority": "low", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-022", "category": "augmentation", "title": "Automated Data Quality Checks",
     "description": "Implement automated quality audits: duplicate removal, noise detection, and balanced demographic representation.",
     "roadmap_phase": "short_term", "priority": "high", "status": "deployed", "enabled": True},

    # Section 3.2 - Model Architecture
    {"story_id": "US-FUT-023", "category": "model_arch", "title": "Hybrid CNN-Transformer Architecture",
     "description": "Combine CNN feature extraction with Transformer global context for improved accuracy while maintaining real-time performance.",
     "roadmap_phase": "long_term", "priority": "medium", "status": "deployed", "enabled": True},

    # Section 3.4 - Robustness
    {"story_id": "US-FUT-024", "category": "robustness", "title": "Occlusion Handling & Partial Face Recognition",
     "description": "Recognize faces with partial occlusions using multi-angle embedding storage and confidence adjustment.",
     "roadmap_phase": "medium_term", "priority": "high", "status": "deployed", "enabled": True},

    # Section 3.5 - Accuracy Boost
    {"story_id": "US-FUT-025", "category": "accuracy", "title": "Multi-Angle Face Recognition",
     "description": "Store embeddings for multiple angles (frontal, profile left/right, 45-degree, top-down) for recognition from any viewpoint.",
     "roadmap_phase": "medium_term", "priority": "high", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-026", "category": "accuracy", "title": "Consensus Voting System",
     "description": "Query against all embeddings per person, average top-k confidence scores, require consensus threshold before identification.",
     "roadmap_phase": "medium_term", "priority": "medium", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-027", "category": "accuracy", "title": "Temporal Enhancement",
     "description": "Use time-based context: recent matches weighted higher, visit frequency patterns, time-of-day considerations.",
     "roadmap_phase": "short_term", "priority": "medium", "status": "deployed", "enabled": True},

    # Section 4.2 - Privacy
    {"story_id": "US-FUT-028", "category": "privacy", "title": "Consent Management & GDPR Compliance",
     "description": "Full consent management system, data retention policies, and right-to-deletion support for GDPR/privacy compliance.",
        "roadmap_phase": "short_term", "priority": "high", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-029", "category": "privacy", "title": "Data Minimization & Secure Computation",
     "description": "Store only necessary features, implement secure multi-party computation to protect data during processing.",
     "roadmap_phase": "medium_term", "priority": "medium", "status": "deployed", "enabled": True},

    # Section 4.3 - Scalability
    {"story_id": "US-FUT-030", "category": "scalability", "title": "Distributed Processing Architecture",
     "description": "Multiple processing nodes with load balancing, horizontal scaling, and geographic distribution.",
        "roadmap_phase": "future_ready", "priority": "medium", "status": "deployed", "enabled": True},

    # Section 4.4 - Performance
    {"story_id": "US-FUT-031", "category": "performance", "title": "GPU Optimization Pipeline",
     "description": "Batch processing, TensorRT optimization, mixed precision training, and pipeline parallelization for real-time performance.",
     "roadmap_phase": "medium_term", "priority": "high", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-032", "category": "performance", "title": "Latency Optimization Targets",
     "description": "Achieve <50ms frame processing, <20ms face detection, <30ms embedding generation, <10ms vector search.",
     "roadmap_phase": "medium_term", "priority": "high", "status": "deployed", "enabled": True},

    # Section 5.1 - CV Improvements
    {"story_id": "US-FUT-033", "category": "cv_advanced", "title": "3D Face Recognition",
     "description": "Use 3D morphable models for depth-based face recognition, improving accuracy in varied poses.",
        "roadmap_phase": "future_ready", "priority": "high", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-034", "category": "cv_advanced", "title": "Infrared & Multi-Spectral Recognition",
     "description": "Support NIR cameras and different light spectrums for recognition in low-light and varied environments.",
        "roadmap_phase": "future_ready", "priority": "medium", "status": "prototype", "enabled": True},
    {"story_id": "US-FUT-035", "category": "cv_advanced", "title": "Emotion Recognition",
     "description": "Add emotional state detection to visitor tracking for enhanced behavioral analytics.",
     "roadmap_phase": "future_ready", "priority": "low", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-036", "category": "cv_advanced", "title": "Action Recognition & Gesture Detection",
     "description": "Detect actions and gestures beyond face recognition, supporting higher resolution (4K+) and multi-object tracking.",
     "roadmap_phase": "future_ready", "priority": "low", "status": "deployed", "enabled": True},

    # Section 5.2 - System Capabilities
    {"story_id": "US-FUT-037", "category": "system", "title": "Multi-Camera & Cross-Camera Tracking",
     "description": "Support 4+ concurrent cameras with cross-camera tracking, spatial awareness, and zone-based analytics.",
     "roadmap_phase": "medium_term", "priority": "high", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-038", "category": "system", "title": "Intelligent Alert System",
     "description": "Anomaly detection, suspicious behavior alerts, peak hour notifications, and VIP visitor alerts.",
     "roadmap_phase": "medium_term", "priority": "medium", "status": "deployed", "enabled": True},

    # Section 5.3 - UX Enhancements
    {"story_id": "US-FUT-039", "category": "ux", "title": "Real-Time Heatmaps & Visitor Flow Analysis",
     "description": "Dashboard enhancements including real-time heatmaps, visitor flow visualization, dwell time tracking, and queue management.",
     "roadmap_phase": "medium_term", "priority": "medium", "status": "deployed", "enabled": True},
    {"story_id": "US-FUT-040", "category": "ux", "title": "PWA & Mobile Features",
     "description": "Progressive Web App support, mobile push notifications, touch-optimized interface, and offline capability.",
        "roadmap_phase": "future_ready", "priority": "low", "status": "deployed", "enabled": True},

    # Section 6 - Emerging Technologies
    {"story_id": "US-FUT-041", "category": "emerging", "title": "Edge AI Device Support",
     "description": "Target NVIDIA Jetson, Google Coral, Intel NCS, and custom edge servers for <10ms latency with privacy preserved.",
        "roadmap_phase": "future_ready", "priority": "medium", "status": "prototype", "enabled": True},

    # Section 4.4 / 7 - Advanced Security
    {"story_id": "US-FUT-042", "category": "robustness", "title": "Liveness Detection & Anti-Spoofing",
     "description": "Advanced liveness detection and anti-spoofing measures to prevent photo/video-based impersonation attacks.",
     "roadmap_phase": "long_term", "priority": "high", "status": "deployed", "enabled": True},
]


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _resolve_face_recognition_runtime_model(
    config: schemas.ModelArchitectureConfig,
) -> tuple[str, Optional[str]]:
    """Resolve the runtime model name and artifact for face recognition."""
    if config.ensemble_enabled:
        return "Ensemble", "ArcFace + ViT"
    if config.vit_enabled:
        return "ViT", config.vit_variant or "vit_base"
    return "ArcFace", None


# Status lifecycle ladder — higher is "more mature / more implemented".
# Used by the seed sync to upgrade rows whose implementations shipped
# since they were last seeded, without ever downgrading or clobbering an
# admin's explicit "disabled" choice.
_STATUS_RANK = {
    "disabled": -1,   # Admin explicitly turned off — never overwrite.
    "planned": 0,
    "research": 1,
    "prototype": 2,
    "testing": 3,
    "deployed": 4,
}


def _seed_defaults(db: Session, org_id: str):
    """Upsert-sync default enhancements for this org.

    - Inserts any story_id that doesn't yet exist.
    - Keeps definitional fields (title, description, category, priority,
      roadmap_phase) in sync with the seed list so re-categorization lands
      in the UI without a manual migration.
    - Upgrades `status` monotonically along _STATUS_RANK: if the seed ships
      a higher status than the DB row, the row is promoted. An admin who
      has moved a row to "disabled" is never overwritten, and an admin who
      has promoted a row beyond the seed level is preserved.
    - Only touches `enabled` when status is upgraded at the same time, so
      admin toggles via /toggle are preserved after the initial promotion.
    """
    existing_rows = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == org_id
    ).limit(1000).all()
    existing_by_story = {row.story_id: row for row in existing_rows}

    dirty = False
    for item in _DEFAULT_ENHANCEMENTS:
        row = existing_by_story.get(item["story_id"])
        if row is None:
            db.add(models.FutureEnhancement(organization_id=org_id, **item))
            dirty = True
            continue

        # Definitional fields are always kept in sync with the seed file.
        for field in ("title", "description", "category", "priority", "roadmap_phase"):
            new_value = item.get(field)
            if new_value is not None and getattr(row, field) != new_value:
                setattr(row, field, new_value)
                dirty = True

        # Status: monotonic upgrade along _STATUS_RANK.
        seed_status = item.get("status", "planned")
        seed_rank = _STATUS_RANK.get(seed_status, 0)
        current_rank = _STATUS_RANK.get(row.status or "planned", 0)
        if current_rank >= 0 and seed_rank > current_rank:
            row.status = seed_status
            # Sync enabled alongside an upgrade so freshly-promoted features
            # light up in the UI without a manual toggle.
            row.enabled = bool(item.get("enabled", False))
            dirty = True

    if dirty:
        db.commit()


def _component_label(component: dict, fallback: str) -> str:
    model = component.get("current_model") or fallback
    artifact = component.get("current_artifact")
    if artifact and artifact != model:
        return f"{model} ({artifact})"
    return model


def _phase_status_from_items(items: List[schemas.CurrentPhaseItem]) -> tuple[str, int, int]:
    implemented_count = sum(1 for item in items if item.status == "implemented")
    planned_count = len(items) - implemented_count
    if implemented_count == len(items):
        return "implemented", implemented_count, planned_count
    if implemented_count == 0:
        return "planned", implemented_count, planned_count
    return "partial", implemented_count, planned_count


def _phase_item_status_from_capability(status: str) -> str:
    normalized = (status or "").strip().lower()
    if normalized == "live":
        return "implemented"
    if normalized in {"beta", "experimental"}:
        return "partial"
    return "planned"


# US-FUT Roadmap Status Normalization
# Maps old model statuses to truth-aligned display labels
_STATUS_NORMALIZATION_MAP = {
    "deployed": "live",
    "testing": "beta",
    "prototype": "beta",
    "research": "experimental",
    "planned": "planned",
    "disabled": "experimental",
}


def _normalize_enhancement_status(model_status: str) -> str:
    """US-FUT: Normalize enhancement status to truth-aligned labels.
    
    Mapping:
    - deployed -> live (production-ready)
    - testing -> beta (in testing)
    - prototype -> beta (functional prototype)
    - research -> experimental (research/exploration)
    - planned -> planned (not yet started)
    - disabled -> experimental (disabled)
    """
    return _STATUS_NORMALIZATION_MAP.get(model_status, "planned")


def _to_enhancement_response(item: models.FutureEnhancement) -> schemas.FutureEnhancementResponse:
    payload = schemas.FutureEnhancementResponse.model_validate(item).model_dump()
    payload["status"] = _normalize_enhancement_status(str(payload.get("status") or "planned"))
    return schemas.FutureEnhancementResponse(**payload)


def _normalize_timestamp(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _validate_runtime_registry_components(components: List[schemas.RuntimeModelComponent]) -> None:
    seen: set[str] = set()
    valid_statuses = {"active", "pilot", "staging", "disabled"}
    for item in components:
        name = (item.component or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Runtime registry component name cannot be empty")
        if name in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate runtime registry component: {name}")
        seen.add(name)
        if item.status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported runtime status '{item.status}' for component '{name}'",
            )


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _runtime_database_profile(db: Optional[Session] = None) -> dict:
    db_url = (SQLALCHEMY_DATABASE_URL or "").strip().lower()
    if db_url.startswith("sqlite"):
        return {
            "backend": "sqlite",
            "label": "SQLite",
            "vector_technology": "Application-level cosine scan (SQLite)",
            "vector_status": "beta",
            "vector_limitation": "Vector search runs as an application-level cosine scan; pgvector indexed retrieval is not active.",
        }

    if db_url.startswith("postgresql"):
        expected_index_type = (os.getenv("PGVECTOR_INDEX_TYPE", "hnsw") or "hnsw").strip().lower()
        if expected_index_type not in {"hnsw", "ivfflat"}:
            expected_index_type = "hnsw"

        extension_installed = False
        ann_index_verified = False
        has_any_embedding_index = False
        verification_error: Optional[str] = None

        if db is not None:
            try:
                extension_installed = bool(
                    db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector' LIMIT 1")).scalar()
                )
            except Exception as exc:
                verification_error = f"pgvector extension verification failed: {exc}"

            try:
                rows = db.execute(
                    text(
                        """
                        SELECT indexname, indexdef
                        FROM pg_indexes
                        WHERE schemaname = ANY(current_schemas(false))
                          AND tablename = 'face_data'
                          AND indexdef ILIKE '%embedding%'
                        LIMIT 100
                        """
                    )
                ).all()
                has_any_embedding_index = len(rows) > 0
                ann_index_verified = any(
                    expected_index_type in (str(row[0]).lower() + " " + str(row[1]).lower())
                    for row in rows
                )
            except Exception as exc:
                verification_error = f"embedding index verification failed: {exc}"

        if extension_installed and ann_index_verified:
            return {
                "backend": "postgresql",
                "label": "PostgreSQL",
                "vector_technology": f"PostgreSQL + pgvector cosine distance ({expected_index_type.upper()} ANN index)",
                "vector_status": "live",
                "vector_limitation": "",
            }

        if extension_installed:
            detail = (
                f"pgvector is installed, but the expected {expected_index_type} ANN embedding index is not verified on face_data."
                if not has_any_embedding_index
                else f"Embedding indexes exist, but the expected {expected_index_type} ANN index is not verified on face_data."
            )
            if verification_error:
                detail = f"{detail} ({verification_error})"

            return {
                "backend": "postgresql",
                "label": "PostgreSQL",
                "vector_technology": "PostgreSQL + pgvector cosine distance search",
                "vector_status": "beta",
                "vector_limitation": detail,
            }

        if verification_error:
            return {
                "backend": "postgresql",
                "label": "PostgreSQL",
                "vector_technology": "PostgreSQL vector search (verification incomplete)",
                "vector_status": "beta",
                "vector_limitation": verification_error,
            }

        return {
            "backend": "postgresql",
            "label": "PostgreSQL",
            "vector_technology": "PostgreSQL + pgvector cosine distance search",
            "vector_status": "experimental",
            "vector_limitation": "PostgreSQL is configured, but pgvector extension is not installed.",
        }

    return {
        "backend": "unknown",
        "label": "Custom SQL backend",
        "vector_technology": "Application-level cosine scoring",
        "vector_status": "experimental",
        "vector_limitation": "Vector search behavior depends on runtime SQL dialect; no indexed vector backend is guaranteed.",
    }


def _runtime_queue_profile() -> dict:
    queue_status = video_queue_service.get_video_job_queue_status()
    mode = queue_status.get("mode")
    active = bool(queue_status.get("active"))

    if mode == "redis" and active:
        worker_count = int(queue_status.get("worker_count") or 0)
        queue_depth = queue_status.get("queue_depth")
        if worker_count > 0:
            depth_text = "unknown" if queue_depth is None else str(queue_depth)
            return {
                "technology": f"Redis list queue + active worker heartbeat ({worker_count} worker(s), depth {depth_text})",
                "status": "live",
                "limitation": "",
            }

        return {
            "technology": "Redis list queue + worker",
            "status": "beta",
            "limitation": "Redis queue is active, but no worker heartbeat is currently detected.",
        }

    if mode == "redis" and not active:
        return {
            "technology": "FastAPI background task fallback",
            "status": "beta",
            "limitation": f"Redis queue is configured but unavailable ({queue_status.get('reason') or 'unknown'}); jobs fall back to in-process background tasks.",
        }

    return {
        "technology": "FastAPI background tasks (in-process)",
        "status": "beta",
        "limitation": "Jobs are asynchronous but not durable across process restarts because no external queue is active.",
    }


def _normalized_entropy(counts: Counter) -> float:
    total = sum(counts.values())
    if total <= 1:
        return 0.0
    entropy = 0.0
    for value in counts.values():
        p = value / total
        if p > 0:
            entropy -= p * math.log2(p)
    max_entropy = math.log2(len(counts)) if len(counts) > 1 else 1.0
    return max(0.0, min(1.0, entropy / max_entropy))


async def _probe_rtsp_stream(rtsp_url: str, probe_timeout_seconds: int) -> dict:
    started_at = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=probe_timeout_seconds) as client:
            response = await client.post(
                f"{AI_SERVICE_URL}/realtime/rtsp-probe",
                json={"rtsp_url": rtsp_url},
            )
        latency_ms = int((time.perf_counter() - started_at) * 1000)

        if response.status_code != 200:
            return {
                "probe_attempted": True,
                "probe_connected": False,
                "probe_latency_ms": latency_ms,
                "probe_error": f"AI service returned {response.status_code}",
            }

        payload = response.json()
        return {
            "probe_attempted": True,
            "probe_connected": bool(payload.get("connected")),
            "probe_latency_ms": latency_ms,
            "probe_width": payload.get("width"),
            "probe_height": payload.get("height"),
            "probe_fps": payload.get("fps"),
            "probe_error": payload.get("error"),
        }
    except Exception as exc:
        return {
            "probe_attempted": True,
            "probe_connected": None,
            "probe_latency_ms": int((time.perf_counter() - started_at) * 1000),
            "probe_error": str(exc),
        }


def _resolve_local_image_path(image_path: str) -> str:
    normalized_input = image_path.replace("\\", "/")
    data_relative = (
        normalized_input[5:]
        if normalized_input.startswith("data/")
        else normalized_input
    )
    # Only DATA_DIR-relative candidates — never the raw input or a cwd-joined
    # path, both of which let an absolute path (C:\..., /etc/passwd, \\host\share)
    # bypass the data directory entirely. data_path() enforces containment.
    candidates = []
    for rel in (normalized_input, data_relative):
        try:
            candidates.append(data_path(rel))
        except ValueError:
            continue

    checked: List[str] = []
    for candidate in candidates:
        fixed = os.path.normpath(candidate)
        if fixed not in checked:
            checked.append(fixed)

    for candidate in checked:
        if os.path.exists(candidate):
            return candidate

    raise HTTPException(status_code=404, detail=f"Image not found: {image_path}")


async def _fetch_rtsp_snapshot_bytes(rtsp_url: str) -> bytes:
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                f"{AI_SERVICE_URL}/realtime/rtsp-snapshot",
                json={
                    "rtsp_url": rtsp_url,
                    "max_width": 1280,
                    "jpeg_quality": 80,
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"AI service unavailable: {exc}") from exc

    if response.status_code != 200:
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = response.text
        raise HTTPException(
            status_code=response.status_code,
            detail=detail or "Unable to capture RTSP snapshot",
        )

    if not response.content:
        raise HTTPException(status_code=502, detail="AI service returned an empty RTSP snapshot")

    return response.content


async def _post_ai_json(endpoint: str, payload: dict, timeout_seconds: float = 20.0) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(f"{AI_SERVICE_URL}{endpoint}", json=payload)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"AI service unavailable: {exc}") from exc

    if response.status_code != 200:
        try:
            detail = response.json().get("detail")
        except Exception:
            detail = response.text
        raise HTTPException(
            status_code=response.status_code,
            detail=detail or f"AI service call failed for {endpoint}",
        )

    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="AI service returned invalid JSON") from exc


async def _resolve_vision_frame_source(
    data: schemas.VisionInferenceRequest,
    user: models.User,
    db: Session,
) -> tuple[str, Optional[str], str, Optional[str]]:
    if data.frame_data:
        normalized_frame, thumbnail = vision_analytics_service.normalize_frame_payload(data.frame_data)
        return normalized_frame, None, "frame_upload", thumbnail

    if data.image_path:
        resolved_path = _resolve_local_image_path(data.image_path)
        try:
            with open(resolved_path, "rb") as handle:
                image_bytes = handle.read()
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Unable to read image: {exc}") from exc
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        mime_type, _ = mimetypes.guess_type(resolved_path)
        thumbnail = f"data:{mime_type or 'image/jpeg'};base64,{encoded}"
        return encoded, None, "image_path", thumbnail

    if data.camera_id:
        camera = db.query(models.Camera).filter(
            models.Camera.id == data.camera_id,
            models.Camera.organization_id == user.organization_id,
        ).first()
        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")
        if not camera.rtsp_url:
            raise HTTPException(status_code=400, detail="Camera does not have an RTSP URL")
        snapshot_bytes = await _fetch_rtsp_snapshot_bytes(camera.rtsp_url)
        encoded = base64.b64encode(snapshot_bytes).decode("utf-8")
        return encoded, str(camera.id), "camera_snapshot", f"data:image/jpeg;base64,{encoded}"

    if data.rtsp_url:
        snapshot_bytes = await _fetch_rtsp_snapshot_bytes(data.rtsp_url)
        encoded = base64.b64encode(snapshot_bytes).decode("utf-8")
        return encoded, None, "rtsp_snapshot", f"data:image/jpeg;base64,{encoded}"

    raise HTTPException(
        status_code=400,
        detail="Provide one of frame_data, image_path, camera_id, or rtsp_url.",
    )


async def _build_stream_health_items(
    user: models.User,
    db: Session,
    stale_after_seconds: int = 90,
    probe_mode: bool = False,
    probe_timeout_seconds: int = 4,
) -> List[schemas.StreamHealthItem]:
    cameras = db.query(models.Camera).filter(
        models.Camera.organization_id == user.organization_id,
    ).order_by(models.Camera.created_at.desc()).limit(500).all()

    now = datetime.now(timezone.utc)
    probe_results: dict[str, dict] = {}

    if probe_mode:
        probe_targets = [camera for camera in cameras if camera.rtsp_url and camera.is_active]
        if probe_targets:
            probe_payloads = await asyncio.gather(
                *[_probe_rtsp_stream(camera.rtsp_url, probe_timeout_seconds) for camera in probe_targets],
            )
            probe_results = {
                str(camera.id): payload
                for camera, payload in zip(probe_targets, probe_payloads)
            }

    items: List[schemas.StreamHealthItem] = []
    for camera in cameras:
        last_seen = _normalize_timestamp(camera.last_seen)
        seconds_since_last_seen = None
        is_stale = True

        if last_seen:
            seconds_since_last_seen = int((now - last_seen).total_seconds())
            is_stale = seconds_since_last_seen > stale_after_seconds

        status = camera.status
        health_source = "database"
        recovery_hint = "Healthy"
        probe_result = probe_results.get(str(camera.id))

        if not camera.rtsp_url:
            recovery_hint = "Add RTSP URL to enable live health probing."
        elif camera.status == "error":
            recovery_hint = "Run camera test and verify credentials/network path."
        elif is_stale:
            recovery_hint = "Feed appears stale; check camera power and RTSP transport."

        if probe_result:
            if probe_result.get("probe_connected") is True:
                status = "online"
                is_stale = False
                health_source = "active_probe"
                resolution = (
                    f"{probe_result.get('probe_width', 0)}x{probe_result.get('probe_height', 0)}"
                    if probe_result.get("probe_width") and probe_result.get("probe_height")
                    else "stream opened"
                )
                fps = probe_result.get("probe_fps")
                fps_text = f" at {float(fps):.1f}fps" if fps not in (None, 0, 0.0) else ""
                recovery_hint = f"Active probe succeeded: {resolution}{fps_text}."
            elif probe_result.get("probe_connected") is False:
                status = "error"
                is_stale = True
                health_source = "active_probe"
                recovery_hint = probe_result.get("probe_error") or "Active probe failed."
            elif probe_result.get("probe_attempted"):
                health_source = "database_fallback"
                recovery_hint = (
                    f"Probe unavailable; using database heartbeat fallback. {probe_result.get('probe_error')}"
                )

        items.append(
            schemas.StreamHealthItem(
                camera_id=camera.id,
                camera_name=camera.name,
                status=status,
                is_active=bool(camera.is_active),
                has_rtsp=bool(camera.rtsp_url),
                last_seen=last_seen,
                seconds_since_last_seen=seconds_since_last_seen,
                is_stale=is_stale,
                health_source=health_source,
                probe_attempted=bool(probe_result and probe_result.get("probe_attempted")),
                probe_connected=probe_result.get("probe_connected") if probe_result else None,
                probe_latency_ms=probe_result.get("probe_latency_ms") if probe_result else None,
                probe_width=probe_result.get("probe_width") if probe_result else None,
                probe_height=probe_result.get("probe_height") if probe_result else None,
                probe_fps=probe_result.get("probe_fps") if probe_result else None,
                probe_error=probe_result.get("probe_error") if probe_result else None,
                recovery_hint=recovery_hint,
            )
        )

    return items


# ── CRUD Endpoints ───────────────────────────────────────────────────────────


@router.get("/", response_model=List[schemas.FutureEnhancementResponse])
async def list_enhancements(
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    roadmap_phase: Optional[str] = Query(None),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all future enhancements, optionally filtered by category/status/phase."""
    user = _get_user(db, current_user_id)
    _seed_defaults(db, str(user.organization_id))

    query = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id
    )
    if category:
        query = query.filter(models.FutureEnhancement.category == category)
    if status:
        query = query.filter(models.FutureEnhancement.status == status)
    if roadmap_phase:
        query = query.filter(models.FutureEnhancement.roadmap_phase == roadmap_phase)

    return [_to_enhancement_response(item) for item in query.order_by(models.FutureEnhancement.story_id).limit(1000).all()]


@router.post("/", response_model=schemas.FutureEnhancementResponse)
async def create_enhancement(
    data: schemas.FutureEnhancementCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new future enhancement entry. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    existing = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == data.story_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Enhancement {data.story_id} already exists")

    enhancement = models.FutureEnhancement(
        organization_id=user.organization_id,
        **data.model_dump(exclude_none=True),
    )
    db.add(enhancement)
    db.commit()
    db.refresh(enhancement)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "create_enhancement",
        "future_enhancement", data.story_id,
    )
    return _to_enhancement_response(enhancement)



# ── Roadmap (4-phase) ────────────────────────────────────────────────────────

_PHASE_META = {
    "short_term": {
        "title": "Phase 1: Quick Wins (1-3 months)",
        "description": "Quick wins and foundational improvements that can be implemented with current infrastructure.",
        "timeline": "1-3 months",
        "tasks": [
            {"task": "Data Augmentation", "description": "Add CutMix, MixUp", "effort": "2 weeks"},
            {"task": "Ensemble Methods", "description": "Add model voting", "effort": "3 weeks"},
            {"task": "Hyperparameter Tuning", "description": "Bayesian optimization", "effort": "2 weeks"},
            {"task": "Quality Checks", "description": "Automated validation", "effort": "2 weeks"},
        ],
    },
    "medium_term": {
        "title": "Phase 2: Core Improvements (3-6 months)",
        "description": "Significant upgrades requiring moderate research and infrastructure changes.",
        "timeline": "3-6 months",
        "tasks": [
            {"task": "Multi-Angle Storage", "description": "Store multiple embeddings", "effort": "4 weeks"},
            {"task": "Occlusion Handling", "description": "Partial face recognition", "effort": "4 weeks"},
            {"task": "Continual Learning", "description": "Add new faces incrementally", "effort": "6 weeks"},
            {"task": "Edge Optimization", "description": "Model pruning/quantization", "effort": "8 weeks"},
        ],
    },
    "long_term": {
        "title": "Phase 3: Advanced Features (6-12 months)",
        "description": "Ambitious research initiatives integrating cutting-edge technology.",
        "timeline": "6-12 months",
        "tasks": [
            {"task": "Vision Transformers", "description": "ViT integration", "effort": "12 weeks"},
            {"task": "Multimodal Learning", "description": "Add text/audio fusion", "effort": "16 weeks"},
            {"task": "Federated Learning", "description": "Distributed training", "effort": "12 weeks"},
            {"task": "XAI Implementation", "description": "Explainable decisions", "effort": "8 weeks"},
        ],
    },
    "future_ready": {
        "title": "Phase 4: Future-Ready (12-24 months)",
        "description": "Future-ready capabilities including quantum computing research and full edge deployment.",
        "timeline": "12-24 months",
        "tasks": [
            {"task": "Quantum Research", "description": "Algorithm exploration", "effort": "Ongoing"},
            {"task": "3D Face Recognition", "description": "Depth-based recognition", "effort": "12 weeks"},
            {"task": "Edge Deployment", "description": "Full edge support", "effort": "16 weeks"},
            {"task": "Advanced Security", "description": "Liveness detection, anti-spoofing", "effort": "8 weeks"},
        ],
    },
}


@router.get("/roadmap/overview", response_model=schemas.RoadmapDetailResponse)
async def get_roadmap(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27: Get the 4-phase implementation roadmap with tasks, progress, and timelines."""
    user = _get_user(db, current_user_id)
    _seed_defaults(db, str(user.organization_id))

    all_enhancements = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
    ).limit(1000).all()

    phases = []
    for phase_key in ["short_term", "medium_term", "long_term", "future_ready"]:
        meta = _PHASE_META[phase_key]
        phase_items = [e for e in all_enhancements if e.roadmap_phase == phase_key]
        deployed_count = sum(1 for e in phase_items if e.status == "deployed")
        progress = (deployed_count / len(phase_items) * 100) if phase_items else 0.0

        phases.append(schemas.RoadmapPhaseDetail(
            phase=phase_key,
            title=meta["title"],
            description=meta["description"],
            timeline=meta["timeline"],
            tasks=[schemas.RoadmapTask(**t) for t in meta["tasks"]],
            enhancements=[_to_enhancement_response(item) for item in phase_items],
            progress_percent=round(progress, 1),
        ))

    total = len(all_enhancements)
    enabled = sum(1 for e in all_enhancements if e.enabled)
    deployed = sum(1 for e in all_enhancements if e.status == "deployed")
    completion = (deployed / total * 100) if total else 0.0

    return schemas.RoadmapDetailResponse(
        phases=phases,
        total_enhancements=total,
        enabled_count=enabled,
        completion_percent=round(completion, 1),
    )


# ── Current Capabilities (Section 2) ────────────────────────────────────────


@router.get("/capabilities/current", response_model=schemas.CurrentCapabilitiesResponse)
async def get_current_capabilities(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 2: Return current system capabilities and limitations."""
    _get_user(db, current_user_id)

    runtime_registry = load_runtime_registry()
    runtime_components = {
        item.get("component"): item for item in runtime_registry.get("components", [])
    }
    benchmark_summary = load_benchmark_summary()
    database_profile = _runtime_database_profile(db)
    queue_profile = _runtime_queue_profile()

    detector_label = _component_label(
        runtime_components.get("person_detector", {}),
        "YOLOv8n",
    )
    tracker_label = _component_label(
        runtime_components.get("person_tracker", {}),
        "ByteTrack",
    )
    face_detector_label = _component_label(
        runtime_components.get("face_detector", {}),
        "opencv",
    )
    face_recognition_label = _component_label(
        runtime_components.get("face_recognition", {}),
        "ArcFace",
    )
    liveness_label = _component_label(
        runtime_components.get("liveness_engine", {}),
        "Spectral + CNN Ensemble",
    )

    phase_1_items = [
        schemas.CurrentPhaseItem(name="Person detection", component=f"Vision pipeline · {detector_label}", status="implemented"),
        schemas.CurrentPhaseItem(name="Face recognition", component=f"Recognition pipeline · {face_recognition_label}", status="implemented"),
        schemas.CurrentPhaseItem(name="Embedding storage", component=f"512-dimensional vectors in {database_profile['label']}", status="implemented"),
        schemas.CurrentPhaseItem(
            name="Vector retrieval",
            component=database_profile["vector_technology"],
            status=_phase_item_status_from_capability(database_profile["vector_status"]),
        ),
        schemas.CurrentPhaseItem(
            name="Tracking + async processing",
            component=f"{queue_profile['technology']} · {tracker_label}",
            status=_phase_item_status_from_capability(queue_profile["status"]),
        ),
        schemas.CurrentPhaseItem(name="Realtime delivery", component="WebSocket streaming", status="implemented"),
    ]
    phase_1_status, phase_1_implemented, phase_1_planned = _phase_status_from_items(phase_1_items)

    phase_2_items = [
        schemas.CurrentPhaseItem(name="Liveness detection", component=f"Anti-spoofing checks · {liveness_label}", status="implemented"),
        schemas.CurrentPhaseItem(name="Bias audit", component="Audit dashboard tab", status="implemented"),
        schemas.CurrentPhaseItem(
            name="Explainability",
            component="XAI summary endpoint with Grad-CAM integration and deterministic fallback breakdown",
            status="implemented",
        ),
        schemas.CurrentPhaseItem(name="Rate limiting", component="Admin rules API", status="implemented"),
        schemas.CurrentPhaseItem(name="Consent and deletion workflow", component="GDPR export and delete endpoints", status="implemented"),
        schemas.CurrentPhaseItem(name="Edge deployment", component="Edge device registry, heartbeat, token-auth sync, deployment, and export APIs", status="implemented"),
    ]
    phase_2_status, phase_2_implemented, phase_2_planned = _phase_status_from_items(phase_2_items)

    benchmark_status = "implemented" if benchmark_summary.get("status") == "completed" else "planned"
    phase_3_items = [
        schemas.CurrentPhaseItem(name="Augmentation config", component="Quality checks + transform controls", status="implemented"),
        schemas.CurrentPhaseItem(name="Model architecture config", component="ViT / ensemble planning", status="implemented"),
        schemas.CurrentPhaseItem(name="Training strategy", component="Self-supervised and continual learning settings", status="implemented"),
        schemas.CurrentPhaseItem(name="Robustness + accuracy tuning", component="Multi-angle and consensus controls", status="implemented"),
        schemas.CurrentPhaseItem(name="Performance tuning", component="GPU optimization targets", status="implemented"),
        schemas.CurrentPhaseItem(name="Runtime model registry", component="Shared detector / tracker / liveness model source of truth", status="implemented"),
        schemas.CurrentPhaseItem(name="Baseline benchmarking", component="Accuracy and latency summary persisted to shared data", status=benchmark_status),
        schemas.CurrentPhaseItem(
            name="Synthetic data generation",
            component="GAN generation with AI-service/Haar model-backed face validation and persisted quality metrics",
            status="implemented",
        ),
        schemas.CurrentPhaseItem(
            name="Temporal augmentation",
            component="Optical-flow temporal synthesis with optional Torch transition refinement",
            status="implemented",
        ),
        schemas.CurrentPhaseItem(
            name="Pose-aware multi-angle retrieval",
            component="Cross-camera ReID scoring now fuses pose analytics and face-angle diversity",
            status="implemented",
        ),
        schemas.CurrentPhaseItem(name="Multimodal learning", component="Fusion config, embedding storage, and multimodal inference ranking endpoint", status="implemented"),
    ]
    phase_3_status, phase_3_implemented, phase_3_planned = _phase_status_from_items(phase_3_items)

    phase_4_items = [
        schemas.CurrentPhaseItem(name="Roadmap management", component="Phase overview and enhancement list", status="implemented"),
        schemas.CurrentPhaseItem(name="Priority matrix", component="Impact/effort/ROI view", status="implemented"),
        schemas.CurrentPhaseItem(name="Metrics targets", component="Accuracy and business targets", status="implemented"),
        schemas.CurrentPhaseItem(name="Sustainability tracking", component="Carbon summary and metrics", status="implemented"),
        schemas.CurrentPhaseItem(name="Operational readiness checks", component="Live /health/readiness deployment snapshot", status="implemented"),
        schemas.CurrentPhaseItem(
            name="Distributed processing",
            component=f"Redis-backed background queue · {queue_profile['technology']}",
            status=_phase_item_status_from_capability(queue_profile["status"]),
        ),
        schemas.CurrentPhaseItem(name="PWA and mobile support", component="Web manifest, service worker, offline page, and mobile dashboard route", status="implemented"),
        schemas.CurrentPhaseItem(name="3D and multispectral CV", component="3D face capture/compare store + RGB-derived multispectral (thermal/NIR/SWIR) pixel analysis", status="implemented"),
    ]
    phase_4_status, phase_4_implemented, phase_4_planned = _phase_status_from_items(phase_4_items)

    current_limitations: List[schemas.CurrentLimitation] = []
    if database_profile.get("vector_limitation"):
        current_limitations.append(
            schemas.CurrentLimitation(description=database_profile["vector_limitation"], severity="high")
        )
    if queue_profile.get("limitation"):
        current_limitations.append(
            schemas.CurrentLimitation(description=queue_profile["limitation"], severity="medium")
        )
    current_limitations.extend([
        schemas.CurrentLimitation(description="Synthetic and temporal generation are now model-backed, but best results still depend on production model artifacts and calibration.", severity="medium"),
        schemas.CurrentLimitation(description="Pose-aware ReID depends on fresh pose analytics events; sparse pose telemetry reduces confidence gains.", severity="medium"),
    ])

    return schemas.CurrentCapabilitiesResponse(
        implemented_features=[
            schemas.CurrentCapability(feature="Person Detection", technology=detector_label, status="live"),
            schemas.CurrentCapability(feature="Face Recognition", technology=f"{face_recognition_label} + {face_detector_label}", status="live"),
            schemas.CurrentCapability(feature="Face Embeddings", technology=f"512-dimensional vectors in {database_profile['label']}", status="live"),
            schemas.CurrentCapability(feature="Vector Search", technology=database_profile["vector_technology"], status=database_profile["vector_status"]),
            schemas.CurrentCapability(feature="Person Tracking", technology=tracker_label, status="live"),
            schemas.CurrentCapability(feature="Video Processing", technology=queue_profile["technology"], status=queue_profile["status"]),
            schemas.CurrentCapability(feature="Real-time Streaming", technology="WebSocket", status="live"),
            schemas.CurrentCapability(feature="Video Input Sources", technology="RTSP, Upload, Webcam", status="live"),
            schemas.CurrentCapability(feature="Liveness Detection", technology=liveness_label, status="live"),
            schemas.CurrentCapability(feature="Anti-spoofing", technology="FFT Moire + Chroma Analysis", status="beta"),
            schemas.CurrentCapability(feature="Bias Audit", technology="Database-driven metrics checks", status="live"),
            schemas.CurrentCapability(feature="Explainable AI (XAI)", technology="Simulated Grad-CAM style heatmaps", status="experimental"),
            schemas.CurrentCapability(feature="Pose-aware ReID Scoring", technology="Cross-camera transitions + pose event quality fusion", status="beta"),
            schemas.CurrentCapability(feature="Multimodal Fusion Inference", technology="Face/audio/text/sensor weighted ranking", status="beta"),
            schemas.CurrentCapability(feature="Future Enhancements Dashboard", technology="17-tab React + FastAPI module", status="live"),
            schemas.CurrentCapability(feature="Runtime Model Registry", technology="Shared JSON-backed model inventory", status="live"),
        ],
        current_limitations=current_limitations,
        phase_summary=[
            schemas.CurrentPhaseSummary(
                phase="Phase 1",
                title="Core Recognition Stack",
                focus="The production pipeline that already powers visitor detection and recognition.",
                status=phase_1_status,
                implemented_count=phase_1_implemented,
                planned_count=phase_1_planned,
                items=phase_1_items,
            ),
            schemas.CurrentPhaseSummary(
                phase="Phase 2",
                title="Safety and Trust",
                focus="Controls that make the system safer and easier to explain.",
                status=phase_2_status,
                implemented_count=phase_2_implemented,
                planned_count=phase_2_planned,
                items=phase_2_items,
            ),
            schemas.CurrentPhaseSummary(
                phase="Phase 3",
                title="Advanced Model Improvements",
                focus="Configuration surfaces for augmentation, architecture, robustness, accuracy, and performance.",
                status=phase_3_status,
                implemented_count=phase_3_implemented,
                planned_count=phase_3_planned,
                items=phase_3_items,
            ),
            schemas.CurrentPhaseSummary(
                phase="Phase 4",
                title="Operations and Scale",
                focus="Operational planning, sustainability, and the roadmap management surface.",
                status=phase_4_status,
                implemented_count=phase_4_implemented,
                planned_count=phase_4_planned,
                items=phase_4_items,
            ),
        ],
        system_version=runtime_registry.get("version", "1.0.0"),
    )


@router.get("/blueprint/next-gen", response_model=schemas.NextGenBlueprintResponse)
async def get_next_gen_blueprint(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the production-grade target architecture and phased implementation blueprint."""
    _get_user(db, current_user_id)

    return schemas.NextGenBlueprintResponse(
        platform_status="mvp_plus",
        gaps=[
            schemas.BlueprintGapItem(
                area="Multi-camera re-identification",
                status="partial",
                impact="high",
                notes="Cross-camera identity stitching is not yet production-hardened.",
            ),
            schemas.BlueprintGapItem(
                area="Pose estimation pipeline",
                status="missing",
                impact="high",
                notes="Pose is not a first-class stage in the online pipeline.",
            ),
            schemas.BlueprintGapItem(
                area="Gesture and action recognition",
                status="missing",
                impact="high",
                notes="No deployable temporal action model is wired into inference.",
            ),
            schemas.BlueprintGapItem(
                area="Behavior anomaly detection",
                status="planned",
                impact="high",
                notes="Roadmap exists, but no robust online anomaly scorer in production.",
            ),
            schemas.BlueprintGapItem(
                area="Model lifecycle management",
                status="partial",
                impact="high",
                notes="Champion/challenger, rollback automation, and gated promotion need hardening.",
            ),
            schemas.BlueprintGapItem(
                area="Benchmarking and profiling",
                status="partial",
                impact="medium",
                notes="Benchmark scripts exist but need a standardized runbook and CI gates.",
            ),
            schemas.BlueprintGapItem(
                area="Biometric security and privacy",
                status="partial",
                impact="high",
                notes="Compliance controls are present but need stricter policy and audit enforcement at scale.",
            ),
        ],
        target_architecture=[
            schemas.BlueprintLayer(
                name="Ingestion layer",
                capabilities=[
                    "RTSP, HTTP upload, local camera, and edge stream ingestion",
                    "Frame sampling and adaptive throttling",
                    "GPU-aware decode path when available",
                ],
            ),
            schemas.BlueprintLayer(
                name="Detection layer",
                capabilities=[
                    "Person detection",
                    "Face detection",
                    "Pose estimation",
                    "Object and scene context detection",
                ],
            ),
            schemas.BlueprintLayer(
                name="Tracking and identity layer",
                capabilities=[
                    "Multi-object tracking",
                    "Face re-identification",
                    "Cross-camera identity stitching",
                    "Tracklet fusion and temporal smoothing",
                ],
            ),
            schemas.BlueprintLayer(
                name="Analysis layer",
                capabilities=[
                    "Liveness and anti-spoofing",
                    "Action and gesture recognition",
                    "Behavior anomaly detection",
                    "Occupancy, dwell-time, and zone analytics",
                ],
            ),
            schemas.BlueprintLayer(
                name="Serving layer",
                capabilities=[
                    "Real-time event API",
                    "Search API",
                    "Dashboard API",
                    "Natural-language query API via LLM",
                    "Reporting and export service",
                ],
            ),
            schemas.BlueprintLayer(
                name="MLOps layer",
                capabilities=[
                    "Model registry",
                    "Experiment tracking",
                    "Dataset versioning",
                    "Metrics and drift monitoring",
                    "Automated retraining triggers",
                ],
            ),
        ],
        model_recommendations=[
            schemas.BlueprintModelRecommendation(
                task="Person detection",
                primary="YOLO11/YOLOv8 family",
                alternatives=["RT-DETR", "EfficientDet (edge-focused)"],
                rationale="Strong speed/accuracy tradeoff and straightforward TensorRT export.",
            ),
            schemas.BlueprintModelRecommendation(
                task="Face detection",
                primary="RetinaFace or YOLO-face",
                alternatives=["SCRFD"],
                rationale="Reliable landmark quality and practical deployment options.",
            ),
            schemas.BlueprintModelRecommendation(
                task="Face recognition",
                primary="ArcFace",
                alternatives=["AdaFace", "MagFace", "CurricularFace"],
                rationale="Proven baseline with robust performance under pose and illumination shift.",
            ),
            schemas.BlueprintModelRecommendation(
                task="Re-identification",
                primary="OSNet",
                alternatives=["TransReID", "Strong ReID backbones"],
                rationale="Good operating point for cross-camera identity retrieval with metric learning.",
            ),
            schemas.BlueprintModelRecommendation(
                task="Pose estimation",
                primary="YOLO-Pose",
                alternatives=["HRNet", "MediaPipe Pose"],
                rationale="Deployable real-time option while preserving useful keypoint quality.",
            ),
            schemas.BlueprintModelRecommendation(
                task="Action and gesture recognition",
                primary="SlowFast",
                alternatives=["Video Swin Transformer", "TimeSformer"],
                rationale="Strong temporal modeling with production-tested video pipelines.",
            ),
            schemas.BlueprintModelRecommendation(
                task="Anomaly detection",
                primary="Sequence transformer anomaly scoring",
                alternatives=["Temporal autoencoders", "Isolation Forest on embeddings"],
                rationale="Captures richer temporal context than purely static heuristics.",
            ),
        ],
        serving_stack=[
            "FastAPI backend",
            "Redis queue workers",
            "PostgreSQL + pgvector",
            "Next.js dashboard",
            "LLM assistant for analytics and reporting",
        ],
        mlops_stack=[
            "PyTorch training stack",
            "ONNX export bridge",
            "TensorRT optimization for NVIDIA",
            "OpenVINO profile for Intel edge",
            "MLflow for experiment tracking and registry",
            "Prometheus + Grafana for observability",
            "ELK for structured logs and auditability",
        ],
        security_baseline=[
            "TLS in transit and encrypted biometric payloads at rest",
            "Role-based access control with least-privilege service accounts",
            "Identity-access audit logging with retention and deletion workflows",
            "Pseudonymization strategy for embeddings where possible",
            "Data minimization and separation of identity store from operational logs",
        ],
        inference_latency_targets_ms={
            "frame_processing": 100,
            "face_detection": 20,
            "embedding_generation": 30,
            "vector_search": 10,
        },
        phased_rollout=[
            schemas.BlueprintPhase(
                phase="Phase 1",
                timeline="0-8 weeks",
                goals=[
                    "Harden current person detection and face recognition",
                    "Stabilize tracking and improve multi-angle matching",
                    "Standardize benchmark and inference profiling workflow",
                ],
                deliverables=[
                    "Baseline benchmark suite",
                    "Latency and quality dashboard",
                    "Model registry integration and promotion checklist",
                ],
            ),
            schemas.BlueprintPhase(
                phase="Phase 2",
                timeline="2-4 months",
                goals=[
                    "Add pose estimation and action/gesture pipeline",
                    "Improve anti-spoofing and liveness robustness",
                    "Deliver cross-camera re-identification v1",
                ],
                deliverables=[
                    "Pose/action inference microservice",
                    "Cross-camera stitching service",
                    "Expanded evaluation datasets and edge-case tests",
                ],
            ),
            schemas.BlueprintPhase(
                phase="Phase 3",
                timeline="4-6 months",
                goals=[
                    "Optimize edge profile with quantization and TensorRT",
                    "Introduce anomaly detection and NL analytics",
                    "Add champion/challenger model rollout controls",
                ],
                deliverables=[
                    "Edge deployment profile",
                    "Anomaly scoring service",
                    "Canary + rollback model release workflow",
                ],
            ),
            schemas.BlueprintPhase(
                phase="Phase 4",
                timeline="6+ months",
                goals=[
                    "Scale to production with full observability and compliance hardening",
                    "Finalize human-in-the-loop continuous learning controls",
                ],
                deliverables=[
                    "Production SLOs and alerting",
                    "Compliance evidence and audit pack",
                    "Approved active-learning retraining loop",
                ],
            ),
        ],
    )


@router.get("/runtime-registry", response_model=schemas.RuntimeModelRegistryResponse)
async def get_runtime_registry(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Alias for runtime model registry endpoint."""
    return await get_runtime_model_registry(current_user_id=current_user_id, db=db)


@router.put("/runtime-registry", response_model=schemas.RuntimeModelRegistryResponse)
async def update_runtime_registry(
    data: schemas.RuntimeModelRegistryUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Alias for runtime model registry update endpoint."""
    return await update_runtime_model_registry(payload=data, current_user_id=current_user_id, db=db)


@router.get("/benchmark/summary", response_model=schemas.BenchmarkSummaryResponse)
async def get_benchmark_summary(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Alias for baseline benchmark summary endpoint."""
    return await get_baseline_benchmark_summary(current_user_id=current_user_id, db=db)


@router.post("/benchmark/run", response_model=schemas.BenchmarkSummaryResponse)
async def run_benchmark_suite(
    sample_size: int = Query(30, ge=10, le=200),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Alias for baseline benchmark run endpoint."""
    return await run_baseline_benchmark_suite(sample_size=sample_size, current_user_id=current_user_id, db=db)


@router.get("/mlflow/registry", response_model=schemas.MLflowRegistryResponse)
async def get_mlflow_registry(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return MLflow-style model registry projection synced with runtime components."""
    _get_user(db, current_user_id)
    return mlflow_registry_service.get_registry_snapshot()


@router.get("/mlflow/promotions", response_model=List[schemas.ModelPromotionRecord])
async def get_mlflow_promotions(
    limit: int = Query(20, ge=1, le=200),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List recent model promotion attempts and benchmark gate outcomes."""
    _get_user(db, current_user_id)
    return mlflow_registry_service.list_promotions(limit=limit)


@router.get("/mlflow/health-summary", response_model=schemas.MLflowPromotionHealthSummary)
async def get_mlflow_health_summary(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Summarize recent MLflow promotion activity for operational visibility."""
    _get_user(db, current_user_id)
    return schemas.MLflowPromotionHealthSummary(**mlflow_registry_service.promotion_health_summary())


@router.post("/mlflow/promote", response_model=schemas.ModelPromotionResponse)
async def promote_model_candidate(
    data: schemas.ModelPromotionRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Promote runtime model candidate with benchmark gating and promotion metadata."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    runtime_registry = load_runtime_registry()
    component = next(
        (item for item in runtime_registry.get("components", []) if item.get("component") == data.component),
        None,
    )
    if not component:
        raise HTTPException(status_code=404, detail=f"Unknown runtime component: {data.component}")
    if data.candidate_model == component.get("current_model") and (
        not data.candidate_artifact or data.candidate_artifact == component.get("current_artifact")
    ):
        raise HTTPException(status_code=400, detail="Candidate model matches the currently active runtime model")

    previous_model = component.get("current_model")
    previous_artifact = component.get("current_artifact")
    resolved_candidate_artifact = data.candidate_artifact
    if (
        not resolved_candidate_artifact
        and component.get("target_model")
        and component.get("target_model") == data.candidate_model
        and component.get("target_artifact")
    ):
        resolved_candidate_artifact = component.get("target_artifact")

    benchmark_summary = run_baseline_benchmark(sample_size=data.benchmark_sample_size)
    benchmark_status = str(benchmark_summary.get("status", "failed"))
    benchmark_production_ready = bool(benchmark_summary.get("production_ready", False))
    benchmark_gate_passed = benchmark_status == "completed" and (
        (not data.require_production_ready) or benchmark_production_ready
    )

    runtime_registry_to_return = runtime_registry
    status = "blocked"
    message = (
        "Promotion blocked by benchmark gate. "
        "Run benchmark with production-ready metrics before promoting this model."
    )

    if benchmark_gate_passed:
        component["current_model"] = data.candidate_model
        if resolved_candidate_artifact:
            component["current_artifact"] = resolved_candidate_artifact
        component["status"] = "active"
        component["notes"] = f"Promoted on {datetime.now(timezone.utc).isoformat()} after benchmark gate pass"
        runtime_registry_to_return = save_runtime_registry(runtime_registry)
        status = "applied"
        message = "Promotion applied and runtime registry updated."

    _, promotion_record = mlflow_registry_service.record_promotion(
        component=data.component,
        previous_model=previous_model,
        previous_artifact=previous_artifact,
        candidate_model=data.candidate_model,
        candidate_artifact=resolved_candidate_artifact,
        requested_by=str(user.id),
        benchmark_status=benchmark_status,
        benchmark_production_ready=benchmark_production_ready,
        benchmark_sample_size=data.benchmark_sample_size,
        reason=data.reason,
        applied=benchmark_gate_passed,
        notes=message,
    )

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "promote_runtime_model",
        "runtime_registry",
        data.component,
        details={
            "status": status,
            "component": data.component,
            "previous_model": previous_model,
            "candidate_model": data.candidate_model,
            "candidate_artifact": resolved_candidate_artifact,
            "benchmark_status": benchmark_status,
            "benchmark_production_ready": benchmark_production_ready,
        },
    )

    return schemas.ModelPromotionResponse(
        status=status,
        message=message,
        promotion=schemas.ModelPromotionRecord(**promotion_record),
        runtime_registry=schemas.RuntimeModelRegistryResponse(**runtime_registry_to_return),
        benchmark_summary=schemas.BenchmarkSummaryResponse(**benchmark_summary),
    )


@router.get("/streams/health", response_model=List[schemas.StreamHealthItem])
async def get_stream_health(
    stale_after_seconds: int = Query(90, ge=10, le=600),
    probe_mode: bool = Query(False),
    probe_timeout_seconds: int = Query(4, ge=1, le=15),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return stream health for all organization cameras with optional active RTSP probes."""
    user = _get_user(db, current_user_id)
    return await _build_stream_health_items(
        user=user,
        db=db,
        stale_after_seconds=stale_after_seconds,
        probe_mode=probe_mode,
        probe_timeout_seconds=probe_timeout_seconds,
    )


@router.post("/reid/cross-camera/search", response_model=schemas.CrossCameraReidResponse)
async def cross_camera_reid_search(
    data: schemas.CrossCameraReidRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cross-camera ReID query from historical sightings with transition scoring."""
    user = _get_user(db, current_user_id)
    return reid_service.search_cross_camera_matches(
        db=db,
        organization_id=user.organization_id,
        request=data,
    )


@router.post("/reid/cross-camera/sync", response_model=schemas.CrossCameraMovementSyncResponse)
async def sync_cross_camera_reid_movements(
    data: schemas.CrossCameraMovementSyncRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Persist cross-camera transition summaries so movement analytics survive beyond ad hoc searches."""
    user = _get_user(db, current_user_id)
    result = reid_service.sync_cross_camera_movements(
        db=db,
        organization_id=user.organization_id,
        request=data,
    )
    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "sync_cross_camera_movements",
        "cross_camera_movement_summary",
        None,
        details={
            "lookback_minutes": data.lookback_minutes,
            "synced_matches": result.synced_matches,
            "upserted_movements": result.upserted_movements,
        },
    )
    return result


@router.get("/reid/cross-camera/movements", response_model=schemas.CrossCameraMovementListResponse)
async def list_cross_camera_movements(
    visitor_id: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    limit: int = Query(25, ge=1, le=200),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return persisted cross-camera movement summaries for reporting and operations review."""
    user = _get_user(db, current_user_id)
    return reid_service.list_cross_camera_movements(
        db=db,
        organization_id=user.organization_id,
        visitor_id=visitor_id,
        camera_id=camera_id,
        limit=limit,
    )


@router.post("/analytics/query", response_model=schemas.NLAnalyticsQueryResponse)
async def query_analytics(
    data: schemas.NLAnalyticsQueryRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Deterministic natural-language analytics helper over operational event data."""
    user = _get_user(db, current_user_id)
    raw_query = data.query.strip()
    lowered = raw_query.lower()

    hours = data.lookback_hours
    match = re.search(r"(\d+)\s*(hour|hours|hr|hrs)", lowered)
    if match:
        parsed_hours = int(match.group(1))
        hours = max(1, min(parsed_hours, 168))

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    base_logs = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == user.organization_id,
        models.VisitorLog.timestamp >= since,
    )

    if "camera" in lowered and "health" in lowered:
        probe_mode = any(keyword in lowered for keyword in ("probe", "live", "active"))
        health = await _build_stream_health_items(
            user=user,
            db=db,
            stale_after_seconds=90,
            probe_mode=probe_mode,
            probe_timeout_seconds=4,
        )
        stale_count = sum(1 for item in health if item.is_stale)
        result = {
            "total_cameras": len(health),
            "stale_cameras": stale_count,
            "healthy_cameras": len(health) - stale_count,
            "probe_mode": probe_mode,
            "items": [item.model_dump() for item in health],
        }
        summary = f"{result['healthy_cameras']} healthy cameras and {stale_count} stale cameras in the current fleet."
        return schemas.NLAnalyticsQueryResponse(
            query=raw_query,
            interpreted_intent="camera_health_summary",
            summary=summary,
            result=result,
        )

    if "movement" in lowered or "transition" in lowered or "cross camera" in lowered:
        movement_rows = db.query(models.CrossCameraMovementSummary).filter(
            models.CrossCameraMovementSummary.organization_id == user.organization_id,
            models.CrossCameraMovementSummary.updated_at >= since,
        ).order_by(models.CrossCameraMovementSummary.updated_at.desc()).limit(10000).all()
        top_paths = [
            {
                "visitor_id": str(row.visitor_id),
                "from_camera_id": str(row.from_camera_id),
                "to_camera_id": str(row.to_camera_id),
                "transition_count": int(row.transition_count or 0),
                "reid_score": float(row.reid_score or 0.0),
            }
            for row in movement_rows[:5]
        ]
        result = {
            "lookback_hours": hours,
            "movement_summary_count": len(movement_rows),
            "total_transitions": sum(int(row.transition_count or 0) for row in movement_rows),
            "top_paths": top_paths,
        }
        summary = (
            f"Tracked {len(movement_rows)} cross-camera movement summaries "
            f"with {result['total_transitions']} transitions over the last {hours} hour(s)."
        )
        return schemas.NLAnalyticsQueryResponse(
            query=raw_query,
            interpreted_intent="cross_camera_movement_summary",
            summary=summary,
            result=result,
        )

    if "continuous learning" in lowered or ("learning" in lowered and "signal" in lowered):
        signals = db.query(models.ContinuousLearningSignal).filter(
            models.ContinuousLearningSignal.organization_id == user.organization_id,
            models.ContinuousLearningSignal.created_at >= since,
        ).order_by(models.ContinuousLearningSignal.created_at.desc()).limit(10000).all()
        priority_counts = Counter((signal.priority or "low") for signal in signals)
        status_counts = Counter((signal.status or "open") for signal in signals)
        result = {
            "lookback_hours": hours,
            "signal_count": len(signals),
            "open_signals": status_counts.get("open", 0),
            "queued_signals": status_counts.get("queued", 0),
            "priority_breakdown": dict(priority_counts),
            "status_breakdown": dict(status_counts),
        }
        summary = (
            f"Continuous-learning queue has {result['open_signals']} open signal(s) and "
            f"{result['queued_signals']} queued signal(s) in the last {hours} hour(s)."
        )
        return schemas.NLAnalyticsQueryResponse(
            query=raw_query,
            interpreted_intent="continuous_learning_summary",
            summary=summary,
            result=result,
        )

    if "behavior" in lowered or "gesture" in lowered or "pose" in lowered:
        behavior_rows = db.query(models.BehaviorEvent).filter(
            models.BehaviorEvent.organization_id == user.organization_id,
            models.BehaviorEvent.created_at >= since,
        ).order_by(models.BehaviorEvent.created_at.desc()).limit(10000).all()
        vision_summary = vision_analytics_service.summarize_recent_vision_activity(
            db,
            organization_id=user.organization_id,
            lookback_hours=hours,
        )

        if behavior_rows:
            posture_counts = Counter((row.posture or "unknown") for row in behavior_rows)
            action_counts = Counter((row.action or "unknown") for row in behavior_rows)
            gesture_counts = Counter((row.gesture or "none") for row in behavior_rows)
            result = {
                "lookback_hours": hours,
                "behavior_event_count": len(behavior_rows),
                "vision_history_event_count": vision_summary.get("total_events", 0),
                "anomaly_events": sum(1 for row in behavior_rows if row.event_type == "anomaly"),
                "top_postures": posture_counts.most_common(5),
                "top_actions": action_counts.most_common(5),
                "top_gestures": gesture_counts.most_common(5),
                "source": "behavior_events",
            }
            summary = (
                f"Behavior analytics recorded {len(behavior_rows)} event(s) in the last {hours} hour(s); "
                f"top posture is {result['top_postures'][0][0] if result['top_postures'] else 'unknown'}."
            )
        else:
            result = {
                **vision_summary,
                "source": "vision_analytics_history",
            }
            summary = (
                f"Vision history recorded {vision_summary['total_events']} pose/action event(s) "
                f"in the last {hours} hour(s)."
            )
            if vision_summary.get("top_action"):
                summary += f" Top action: {vision_summary['top_action']}."
            if vision_summary.get("top_posture"):
                summary += f" Top posture: {vision_summary['top_posture']}."

        return schemas.NLAnalyticsQueryResponse(
            query=raw_query,
            interpreted_intent="behavior_summary",
            summary=summary,
            result=result,
        )

    if "anomal" in lowered:
        anomaly_events = db.query(models.BehaviorEvent).filter(
            models.BehaviorEvent.organization_id == user.organization_id,
            models.BehaviorEvent.created_at >= since,
            models.BehaviorEvent.event_type == "anomaly",
        ).order_by(models.BehaviorEvent.created_at.desc()).limit(10000).all()
        if anomaly_events:
            severity_counts = Counter((event.severity or "info") for event in anomaly_events)
            label_counts = Counter((event.anomaly_label or "unknown") for event in anomaly_events)
            result = {
                "lookback_hours": hours,
                "anomaly_event_count": len(anomaly_events),
                "severity_breakdown": dict(severity_counts),
                "top_anomaly_labels": label_counts.most_common(5),
                "source": "behavior_events",
            }
            summary = (
                f"Detected {len(anomaly_events)} persisted anomaly event(s) in the last {hours} hour(s); "
                f"{severity_counts.get('critical', 0)} critical and {severity_counts.get('high', 0)} high severity."
            )
        else:
            anomaly_logs = base_logs.filter(
                (models.VisitorLog.identified == False) | (models.VisitorLog.confidence < 0.45),
            ).limit(100000).all()
            result = {
                "lookback_hours": hours,
                "anomaly_event_count": len(anomaly_logs),
                "rule": "unidentified_or_low_confidence",
                "source": "visitor_logs_fallback",
            }
            summary = f"Detected {len(anomaly_logs)} anomaly-like events in the last {hours} hour(s)."
        return schemas.NLAnalyticsQueryResponse(
            query=raw_query,
            interpreted_intent="anomaly_summary",
            summary=summary,
            result=result,
        )

    if "unidentified" in lowered:
        total = base_logs.count()
        unidentified = base_logs.filter(models.VisitorLog.identified == False).count()
        ratio = round((unidentified / total) * 100, 2) if total else 0.0
        result = {
            "lookback_hours": hours,
            "total_events": total,
            "unidentified_events": unidentified,
            "unidentified_ratio_pct": ratio,
        }
        summary = f"Unidentified events: {unidentified} out of {total} ({ratio}%) in the last {hours} hour(s)."
        return schemas.NLAnalyticsQueryResponse(
            query=raw_query,
            interpreted_intent="unidentified_summary",
            summary=summary,
            result=result,
        )

    if "liveness" in lowered or "spoof" in lowered:
        scores = db.query(models.LivenessScore).filter(
            models.LivenessScore.organization_id == user.organization_id,
            models.LivenessScore.created_at >= since,
        )
        total_scores = scores.count()
        live_count = scores.filter(models.LivenessScore.is_live == True).count()
        spoof_count = total_scores - live_count
        live_rate = round((live_count / total_scores) * 100, 2) if total_scores else 0.0
        result = {
            "lookback_hours": hours,
            "total_checks": total_scores,
            "live_count": live_count,
            "spoof_or_failed_count": spoof_count,
            "live_rate_pct": live_rate,
        }
        summary = f"Liveness checks: {total_scores} total, {spoof_count} failed/spoof, live-rate {live_rate}% over {hours} hour(s)."
        return schemas.NLAnalyticsQueryResponse(
            query=raw_query,
            interpreted_intent="liveness_summary",
            summary=summary,
            result=result,
        )

    if any(keyword in lowered for keyword in ("pose", "action", "gesture", "posture")):
        result = vision_analytics_service.summarize_recent_vision_activity(
            db,
            organization_id=user.organization_id,
            lookback_hours=hours,
        )
        summary = (
            f"Vision analytics in the last {hours} hour(s): {result['total_events']} events "
            f"({result['pose_event_count']} pose, {result['action_event_count']} action)."
        )
        if result.get("top_action"):
            summary += f" Top action: {result['top_action']}."
        if result.get("top_posture"):
            summary += f" Top posture: {result['top_posture']}."

        return schemas.NLAnalyticsQueryResponse(
            query=raw_query,
            interpreted_intent="vision_activity_summary",
            summary=summary,
            result=result,
        )

    total = base_logs.count()
    identified = base_logs.filter(models.VisitorLog.identified == True).count()
    unidentified = total - identified
    avg_confidence = base_logs.with_entities(func.avg(models.VisitorLog.confidence)).scalar() or 0.0

    result = {
        "lookback_hours": hours,
        "total_events": total,
        "identified_events": identified,
        "unidentified_events": unidentified,
        "average_confidence": round(float(avg_confidence), 4),
    }
    summary = (
        f"In the last {hours} hour(s): {total} events, {identified} identified, "
        f"{unidentified} unidentified, avg confidence {float(avg_confidence):.2f}."
    )

    return schemas.NLAnalyticsQueryResponse(
        query=raw_query,
        interpreted_intent="general_detection_summary",
        summary=summary,
        result=result,
    )


# ── Category-Specific Config Endpoints ───────────────────────────────────────


@router.post("/vision/pose-estimate", response_model=schemas.PoseEstimateResponse)
async def estimate_pose(
    data: schemas.VisionInferenceRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Capture a frame or use a supplied image and run pose estimation via the AI service."""
    user = _get_user(db, current_user_id)
    frame_data, camera_id, source, thumbnail = await _resolve_vision_frame_source(data=data, user=user, db=db)
    result = await _post_ai_json(
        "/realtime/pose-estimate",
        {"frame_data": frame_data},
    )

    event = vision_analytics_service.record_vision_event(
        db,
        organization_id=user.organization_id,
        event_type="pose_estimate",
        source=source,
        model=result.get("model"),
        status=result.get("status", "unknown"),
        payload=result,
        camera_id=camera_id,
        snapshot_thumbnail=thumbnail,
    )

    return schemas.PoseEstimateResponse(
        source=source,
        camera_id=camera_id,
        status=result.get("status", "unknown"),
        available=bool(result.get("available", False)),
        model=result.get("model", "unknown"),
        posture=result.get("posture", "unknown"),
        keypoint_count=int(result.get("keypoint_count", 0) or 0),
        average_visibility=float(result.get("average_visibility", 0.0) or 0.0),
        processing_time_ms=float(result.get("processing_time_ms", 0.0) or 0.0),
        message=result.get("message"),
        snapshot_thumbnail=thumbnail,
        analytics_event_id=event.id,
    )


@router.post("/vision/action-infer", response_model=schemas.ActionInferResponse)
async def infer_action(
    data: schemas.ActionInferRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Capture a frame or use a supplied image and run action/gesture inference via the AI service."""
    user = _get_user(db, current_user_id)
    frame_data, camera_id, source, thumbnail = await _resolve_vision_frame_source(data=data, user=user, db=db)
    result = await _post_ai_json(
        "/realtime/action-infer",
        {
            "frame_data": frame_data,
            "track_id": data.track_id,
        },
    )

    event = vision_analytics_service.record_vision_event(
        db,
        organization_id=user.organization_id,
        event_type="action_infer",
        source=source,
        model=result.get("model"),
        status=result.get("status", "unknown"),
        payload=result,
        camera_id=camera_id,
        snapshot_thumbnail=thumbnail,
    )

    return schemas.ActionInferResponse(
        source=source,
        camera_id=camera_id,
        status=result.get("status", "unknown"),
        available=bool(result.get("available", False)),
        model=result.get("model", "unknown"),
        action=result.get("action", "unknown"),
        gesture=result.get("gesture", "none"),
        confidence=float(result.get("confidence", 0.0) or 0.0),
        posture=result.get("posture", "unknown"),
        keypoint_count=int(result.get("keypoint_count", 0) or 0),
        processing_time_ms=float(result.get("processing_time_ms", 0.0) or 0.0),
        message=result.get("message"),
        flags=result.get("flags", {}),
        snapshot_thumbnail=thumbnail,
        analytics_event_id=event.id,
    )


@router.post("/behavior/analyze", response_model=schemas.BehaviorAnalysisResponse)
async def analyze_behavior_snapshot(
    data: schemas.BehaviorAnalyzeRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run pose + action inference, persist a behavior/anomaly event, and emit continuous-learning signals when needed."""
    user = _get_user(db, current_user_id)
    frame_data, camera_id, source, thumbnail = await _resolve_vision_frame_source(data=data, user=user, db=db)

    visitor = None
    visitor_log = None
    camera = None

    if camera_id:
        camera = db.query(models.Camera).filter(
            models.Camera.id == camera_id,
            models.Camera.organization_id == user.organization_id,
        ).first()

    if data.visitor_id:
        visitor = db.query(models.Visitor).filter(
            models.Visitor.id == data.visitor_id,
            models.Visitor.organization_id == user.organization_id,
        ).first()
        if not visitor:
            raise HTTPException(status_code=404, detail="Visitor not found")

    if data.visitor_log_id:
        visitor_log = db.query(models.VisitorLog).filter(
            models.VisitorLog.id == data.visitor_log_id,
            models.VisitorLog.organization_id == user.organization_id,
        ).first()
        if not visitor_log:
            raise HTTPException(status_code=404, detail="Visitor log not found")
        if visitor is None and visitor_log.visitor_id:
            visitor = db.query(models.Visitor).filter(
                models.Visitor.id == visitor_log.visitor_id,
                models.Visitor.organization_id == user.organization_id,
            ).first()
        if camera is None and visitor_log.camera_id:
            camera = db.query(models.Camera).filter(
                models.Camera.id == visitor_log.camera_id,
                models.Camera.organization_id == user.organization_id,
            ).first()

    pose_result = await _post_ai_json(
        "/realtime/pose-estimate",
        {"frame_data": frame_data},
    )
    action_result = await _post_ai_json(
        "/realtime/action-infer",
        {"frame_data": frame_data, "track_id": data.track_id},
    )

    pose_event = vision_analytics_service.record_vision_event(
        db,
        organization_id=user.organization_id,
        event_type="pose_estimate",
        source=source,
        model=pose_result.get("model"),
        status=pose_result.get("status", "unknown"),
        payload=pose_result,
        camera_id=camera_id,
        snapshot_thumbnail=thumbnail,
    )
    action_event = vision_analytics_service.record_vision_event(
        db,
        organization_id=user.organization_id,
        event_type="action_infer",
        source=source,
        model=action_result.get("model"),
        status=action_result.get("status", "unknown"),
        payload=action_result,
        camera_id=camera_id,
        snapshot_thumbnail=thumbnail,
    )

    pose_response = schemas.PoseEstimateResponse(
        source=source,
        camera_id=camera_id,
        status=pose_result.get("status", "unknown"),
        available=bool(pose_result.get("available", False)),
        model=pose_result.get("model", "unknown"),
        posture=pose_result.get("posture", "unknown"),
        keypoint_count=int(pose_result.get("keypoint_count", 0) or 0),
        average_visibility=float(pose_result.get("average_visibility", 0.0) or 0.0),
        processing_time_ms=float(pose_result.get("processing_time_ms", 0.0) or 0.0),
        message=pose_result.get("message"),
        snapshot_thumbnail=thumbnail,
        analytics_event_id=pose_event.id,
    )
    action_response = schemas.ActionInferResponse(
        source=source,
        camera_id=camera_id,
        status=action_result.get("status", "unknown"),
        available=bool(action_result.get("available", False)),
        model=action_result.get("model", "unknown"),
        action=action_result.get("action", "unknown"),
        gesture=action_result.get("gesture", "none"),
        confidence=float(action_result.get("confidence", 0.0) or 0.0),
        posture=action_result.get("posture", "unknown"),
        keypoint_count=int(action_result.get("keypoint_count", 0) or 0),
        processing_time_ms=float(action_result.get("processing_time_ms", 0.0) or 0.0),
        message=action_result.get("message"),
        flags=action_result.get("flags", {}),
        snapshot_thumbnail=thumbnail,
        analytics_event_id=action_event.id,
    )

    behavior_event, learning_signal, anomaly_reasons = behavior_analytics_service.persist_behavior_analysis(
        db=db,
        organization_id=user.organization_id,
        camera=camera,
        visitor=visitor,
        visitor_log=visitor_log,
        pose_estimate=pose_response,
        action_inference=action_response,
        source=data.source or source,
        initiated_by_user_id=user.id,
    )

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "analyze_behavior_snapshot",
        "behavior_event",
        str(behavior_event.id),
        details={
            "camera_id": str(behavior_event.camera_id) if behavior_event.camera_id else None,
            "anomaly_label": behavior_event.anomaly_label,
            "severity": behavior_event.severity,
            "signal_created": learning_signal is not None,
        },
    )

    return schemas.BehaviorAnalysisResponse(
        pose_estimate=pose_response,
        action_inference=action_response,
        event=behavior_event,
        signal_created=learning_signal is not None,
        learning_signal=learning_signal,
        anomaly_reasons=anomaly_reasons,
    )


@router.get("/behavior/events", response_model=schemas.BehaviorEventListResponse)
async def list_behavior_event_feed(
    limit: int = Query(25, ge=1, le=200),
    event_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    reviewed: Optional[bool] = Query(None),
    min_anomaly_score: float = Query(0.0, ge=0.0, le=1.0),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return persisted behavior and anomaly events for operations, reporting, and UAT evidence."""
    user = _get_user(db, current_user_id)
    return behavior_analytics_service.list_behavior_events(
        db=db,
        organization_id=user.organization_id,
        limit=limit,
        event_type=event_type,
        severity=severity,
        reviewed=reviewed,
        min_anomaly_score=min_anomaly_score,
    )


@router.patch("/behavior/events/{event_id}", response_model=schemas.BehaviorEventItem)
async def update_behavior_event_review(
    event_id: UUID,
    payload: schemas.BehaviorEventUpdateRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a behavior event as reviewed for operational workflows."""
    user = _get_user(db, current_user_id)
    try:
        updated = behavior_analytics_service.mark_behavior_event_reviewed(
            db=db,
            organization_id=user.organization_id,
            event_id=event_id,
            reviewed=payload.reviewed,
            notes=payload.notes,
            user_id=user.id,
        )
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "review_behavior_event",
        "behavior_event",
        str(event_id),
        details={"reviewed": payload.reviewed, "notes": payload.notes},
    )
    return updated


@router.get("/continuous-learning/signals", response_model=schemas.ContinuousLearningSignalListResponse)
async def list_continuous_learning_signals(
    limit: int = Query(25, ge=1, le=200),
    status: Optional[str] = Query(None),
    min_priority: str = Query("low"),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return anomaly and low-confidence signals queued for active learning workflows."""
    user = _get_user(db, current_user_id)
    return behavior_analytics_service.list_learning_signals(
        db=db,
        organization_id=user.organization_id,
        limit=limit,
        status=status,
        min_priority=min_priority,
    )


@router.patch("/continuous-learning/signals/{signal_id}", response_model=schemas.ContinuousLearningSignalItem)
async def update_continuous_learning_signal(
    signal_id: UUID,
    payload: schemas.ContinuousLearningSignalUpdateRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a continuous-learning signal status and resolution notes."""
    user = _get_user(db, current_user_id)
    try:
        updated = behavior_analytics_service.update_learning_signal_status(
            db=db,
            organization_id=user.organization_id,
            signal_id=signal_id,
            status=payload.status,
            resolution=payload.resolution,
            notes=payload.notes,
            user_id=user.id,
        )
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "update_learning_signal",
        "continuous_learning_signal",
        str(signal_id),
        details={"status": payload.status, "resolution": payload.resolution},
    )
    return updated


@router.post("/continuous-learning/signals/queue", response_model=schemas.ContinuousLearningQueueResponse)
async def queue_continuous_learning_signals(
    data: schemas.ContinuousLearningQueueRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Promote open behavior/anomaly signals into the active-learning queue."""
    user = _get_user(db, current_user_id)
    try:
        result = behavior_analytics_service.queue_learning_signals(
            db=db,
            organization_id=user.organization_id,
            user_id=user.id,
            request=data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "queue_continuous_learning_signals",
        "active_learning_job",
        str(result.job_id),
        details={
            "queued_signal_count": result.queued_signal_count,
            "strategy": result.strategy,
            "training_recommended": result.training_recommended,
            "selected_signal_ids": [str(item) for item in result.selected_signal_ids],
        },
    )
    return result


@router.post(
    "/continuous-learning/signals/{signal_id}/promote",
    response_model=schemas.ContinuousLearningSignalPromoteResponse,
)
async def promote_continuous_learning_signal(
    signal_id: UUID,
    payload: schemas.ContinuousLearningSignalPromoteRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Promote a learning signal into a training sample and resolve it."""
    user = _get_user(db, current_user_id)
    try:
        signal_item, sample = behavior_analytics_service.promote_learning_signal_to_sample(
            db=db,
            organization_id=user.organization_id,
            signal_id=signal_id,
            request=payload,
            user_id=user.id,
        )
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "promote_learning_signal",
        "learning_sample",
        str(sample.id),
        details={"signal_id": str(signal_id), "visitor_id": str(sample.visitor_id)},
    )

    return schemas.ContinuousLearningSignalPromoteResponse(
        signal=signal_item,
        sample_id=sample.id,
    )


@router.get("/vision/history", response_model=schemas.VisionAnalyticsHistoryResponse)
async def get_vision_history(
    event_type: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    lookback_hours: int = Query(72, ge=1, le=720),
    limit: int = Query(20, ge=1, le=200),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return persisted pose/action analytics history for ops, reporting, and UAT evidence."""
    user = _get_user(db, current_user_id)
    normalized_event_type = event_type.strip() if event_type else None
    if normalized_event_type and normalized_event_type not in vision_analytics_service.VALID_EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported event_type '{normalized_event_type}'. Use one of {sorted(vision_analytics_service.VALID_EVENT_TYPES)}",
        )

    return vision_analytics_service.list_vision_history(
        db,
        organization_id=user.organization_id,
        event_type=normalized_event_type,
        camera_id=camera_id,
        lookback_hours=lookback_hours,
        limit=limit,
    )


@router.get("/runtime/models", response_model=schemas.RuntimeModelRegistryResponse)
async def get_runtime_model_registry(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the shared runtime model registry used by backend and AI services."""
    _get_user(db, current_user_id)
    return schemas.RuntimeModelRegistryResponse(**load_runtime_registry())


@router.put("/runtime/models", response_model=schemas.RuntimeModelRegistryResponse)
async def update_runtime_model_registry(
    payload: schemas.RuntimeModelRegistryUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Persist shared runtime model configuration. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    _validate_runtime_registry_components(payload.components)
    saved_registry = save_runtime_registry(payload.model_dump(exclude_none=True))
    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "update_runtime_model_registry",
        "runtime_registry",
        None,
        details={
            "version": saved_registry.get("version"),
            "components": [item.get("component") for item in saved_registry.get("components", [])],
        },
    )
    return schemas.RuntimeModelRegistryResponse(**saved_registry)


@router.get("/benchmarks/baseline", response_model=schemas.BenchmarkSummaryResponse)
async def get_baseline_benchmark_summary(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the latest persisted baseline benchmark summary."""
    _get_user(db, current_user_id)
    return schemas.BenchmarkSummaryResponse(**load_benchmark_summary())


@router.post("/benchmarks/baseline/run", response_model=schemas.BenchmarkSummaryResponse)
async def run_baseline_benchmark_suite(
    sample_size: int = Query(30, ge=10, le=200),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Execute the baseline benchmark suite and persist its summary. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    summary = run_baseline_benchmark(sample_size=sample_size)
    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "run_baseline_benchmark",
        "benchmark",
        None,
        details={"sample_size": sample_size, "status": summary.get("status")},
    )
    return schemas.BenchmarkSummaryResponse(**summary)


@router.get("/config/augmentation", response_model=schemas.AugmentationConfigResponse)
async def get_augmentation_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 3.1: Get current data augmentation configuration."""
    user = _get_user(db, current_user_id)
    _seed_defaults(db, str(user.organization_id))

    # Read config from augmentation enhancements
    aug_enhancements = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.category == "augmentation",
    ).limit(1000).all()

    config_map = {}
    for enh in aug_enhancements:
        if enh.config:
            config_map.update(enh.config)

    default_techniques = [
        schemas.AugmentationTechniqueConfig(
            technique="cutmix", enabled=config_map.get("cutmix_enabled", False),
            description="Cuts and pastes patches between images — improves localization",
            params=config_map.get("cutmix_params", {"alpha": 1.0})),
        schemas.AugmentationTechniqueConfig(
            technique="mixup", enabled=config_map.get("mixup_enabled", False),
            description="Blends two images and labels — reduces overfitting",
            params=config_map.get("mixup_params", {"alpha": 0.2})),
        schemas.AugmentationTechniqueConfig(
            technique="adversarial", enabled=config_map.get("adversarial_enabled", False),
            description="Train with adversarial examples — improves robustness",
            params=config_map.get("adversarial_params", {"epsilon": 0.03})),
        schemas.AugmentationTechniqueConfig(
            technique="random_erasing", enabled=config_map.get("random_erasing_enabled", False),
            description="Randomly erase image regions — better occlusion handling",
            params=config_map.get("random_erasing_params", {"probability": 0.5, "scale_min": 0.02, "scale_max": 0.33})),
        schemas.AugmentationTechniqueConfig(
            technique="geometric", enabled=config_map.get("geometric_enabled", False),
            description="Rotation, scaling, flipping — angle diversity",
            params=config_map.get("geometric_params", {"rotation_range": 30, "scale_range": [0.8, 1.2], "flip_horizontal": True})),
        schemas.AugmentationTechniqueConfig(
            technique="color_jitter", enabled=config_map.get("color_jitter_enabled", False),
            description="Brightness, contrast, saturation — lighting variation",
            params=config_map.get("color_jitter_params", {"brightness": 0.3, "contrast": 0.3, "saturation": 0.3})),
    ]

    return schemas.AugmentationConfigResponse(
        techniques=default_techniques,
        quality_checks_enabled=config_map.get("quality_checks_enabled", True),
        auto_balance_demographics=config_map.get("auto_balance_demographics", False),
        data_quality_actions=[
            "Curate high-quality labeled data",
            "Remove duplicate and noisy samples",
            "Ensure balanced demographic representation",
            "Regular data quality audits",
            "Implement automated quality checks",
        ],
    )


@router.put("/config/augmentation", response_model=schemas.AugmentationConfigResponse)
async def update_augmentation_config(
    data: schemas.AugmentationConfigRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 3.1: Update data augmentation configuration. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    # Persist config into the US-FUT-008 (CutMix/MixUp) enhancement's config JSON
    enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-008",
    ).first()
    if not enh:
        raise HTTPException(status_code=404, detail="Augmentation enhancement not found — seed data missing")

    config = enh.config or {}
    for tech in data.techniques:
        config[f"{tech.technique}_enabled"] = tech.enabled
        if tech.params:
            config[f"{tech.technique}_params"] = tech.params
    config["quality_checks_enabled"] = data.quality_checks_enabled
    config["auto_balance_demographics"] = data.auto_balance_demographics
    enh.config = config
    db.commit()

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update_augmentation_config",
        "future_enhancement", "US-FUT-008",
        details={"techniques": [t.technique for t in data.techniques if t.enabled]},
    )

    return await get_augmentation_config(current_user_id=current_user_id, db=db)


@router.get("/config/model-architecture", response_model=schemas.ModelArchitectureResponse)
async def get_model_architecture_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 3.2: Get model architecture configuration."""
    user = _get_user(db, current_user_id)
    _seed_defaults(db, str(user.organization_id))

    vit_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-004",
    ).first()
    ensemble_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-005",
    ).first()

    vit_config = (vit_enh.config or {}) if vit_enh else {}
    ens_config = (ensemble_enh.config or {}) if ensemble_enh else {}

    return schemas.ModelArchitectureResponse(
        current_architecture="ArcFace (ResNet-100 backbone)",
        vit_config={
            "enabled": vit_config.get("vit_enabled", False),
            "variant": vit_config.get("vit_variant", None),
            "benefits": [
                "Better handling of long-range dependencies",
                "Improved scalability",
                "Higher accuracy on complex scenes",
                "Better contextual understanding",
            ],
        },
        hybrid_config={
            "enabled": vit_config.get("hybrid_cnn_transformer", False),
            "cnn_backbone": vit_config.get("cnn_backbone", "resnet100"),
            "description": "Combine CNN efficiency with Transformer capabilities",
        },
        ensemble_config={
            "enabled": ens_config.get("ensemble_enabled", False),
            "methods": ens_config.get("ensemble_methods", []),
            "available_methods": {
                "bagging": "Train multiple models on different subsets",
                "boosting": "Sequentially train models to fix errors",
                "stacking": "Combine predictions with meta-learner",
            },
        },
        available_backbones=["resnet50", "resnet100", "resnet152", "mobilenet_v3", "efficientnet_b0"],
        available_vit_variants=["vit_base", "vit_large", "deit_small", "deit_base"],
        available_ensemble_methods=["bagging", "boosting", "stacking"],
    )


@router.put("/config/model-architecture", response_model=schemas.ModelArchitectureResponse)
async def update_model_architecture_config(
    data: schemas.ModelArchitectureConfig,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 3.2: Update model architecture configuration. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    _seed_defaults(db, str(user.organization_id))

    vit_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-004",
    ).first()
    if vit_enh:
        config = vit_enh.config or {}
        config["vit_enabled"] = data.vit_enabled
        config["vit_variant"] = data.vit_variant
        config["hybrid_cnn_transformer"] = data.hybrid_cnn_transformer
        config["cnn_backbone"] = data.cnn_backbone
        vit_enh.config = config
        db.commit()

    ensemble_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-005",
    ).first()
    if ensemble_enh:
        config = ensemble_enh.config or {}
        config["ensemble_enabled"] = data.ensemble_enabled
        config["ensemble_methods"] = data.ensemble_methods or []
        ensemble_enh.config = config
        db.commit()

    runtime_registry = load_runtime_registry()
    components = runtime_registry.get("components", [])
    face_component = next(
        (item for item in components if item.get("component") == "face_recognition"),
        None,
    )
    if face_component is None:
        face_component = {
            "component": "face_recognition",
            "display_name": "Face recognition model",
            "current_model": "ArcFace",
            "framework": "ArcFace-compatible embedding model",
            "runtime": "ai-service",
            "status": "active",
        }
        components.append(face_component)

    selected_model, selected_artifact = _resolve_face_recognition_runtime_model(data)
    face_component["current_model"] = selected_model
    face_component["current_artifact"] = selected_artifact
    if data.vit_variant and selected_model in {"ViT", "Ensemble"}:
        face_component["notes"] = f"ViT variant: {data.vit_variant}"
    elif selected_model == "ArcFace":
        face_component["notes"] = "ArcFace baseline"

    runtime_registry["components"] = components
    save_runtime_registry(runtime_registry)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update_model_arch_config",
        "future_enhancement", "US-FUT-004",
        details={"selected_model": selected_model, "vit_variant": data.vit_variant},
    )

    return await get_model_architecture_config(current_user_id=current_user_id, db=db)


@router.get("/config/training-strategy", response_model=schemas.TrainingStrategyResponse)
async def get_training_strategy_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 3.3: Get training strategy configuration."""
    user = _get_user(db, current_user_id)
    _seed_defaults(db, str(user.organization_id))

    ssl_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-006",
    ).first()
    cl_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-007",
    ).first()
    hpo_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-010",
    ).first()

    ssl_config = (ssl_enh.config or {}) if ssl_enh else {}
    cl_config = (cl_enh.config or {}) if cl_enh else {}
    hpo_config = (hpo_enh.config or {}) if hpo_enh else {}

    return schemas.TrainingStrategyResponse(
        self_supervised={
            "enabled": ssl_config.get("ssl_enabled", False),
            "method": ssl_config.get("ssl_method", None),
            "benefits": [
                "Reduces labeled data requirements",
                "Improves feature representations",
                "Better generalization",
            ],
        },
        continual_learning={
            "enabled": cl_config.get("cl_enabled", False),
            "prevent_catastrophic_forgetting": cl_config.get("prevent_forgetting", True),
            "capabilities": [
                "Add new faces without retraining",
                "Prevent catastrophic forgetting",
                "Adapt to environment changes",
            ],
        },
        hyperparameter_optimization={
            "enabled": hpo_config.get("hpo_enabled", False),
            "method": hpo_config.get("hpo_method", None),
            "methods_detail": {
                "bayesian": "Efficient search",
                "grid": "Thorough exploration with cross-validation",
                "random": "Quick baseline",
                "automl": "End-to-end optimization",
            },
        },
        available_ssl_methods=["simclr", "moco", "mae", "jigsaw"],
        available_hpo_methods=["bayesian", "grid", "random", "automl"],
    )


@router.put("/config/training-strategy", response_model=schemas.TrainingStrategyResponse)
async def update_training_strategy_config(
    data: schemas.TrainingStrategyConfig,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 3.3: Update training strategy configuration. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    ssl_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-006",
    ).first()
    if ssl_enh:
        config = ssl_enh.config or {}
        config["ssl_enabled"] = data.self_supervised_enabled
        config["ssl_method"] = data.self_supervised_method
        ssl_enh.config = config
        db.commit()

    cl_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-007",
    ).first()
    if cl_enh:
        config = cl_enh.config or {}
        config["cl_enabled"] = data.continual_learning_enabled
        config["prevent_forgetting"] = data.prevent_catastrophic_forgetting
        cl_enh.config = config
        db.commit()

    hpo_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-010",
    ).first()
    if hpo_enh:
        config = hpo_enh.config or {}
        config["hpo_enabled"] = data.hyperparameter_optimization is not None
        config["hpo_method"] = data.hyperparameter_optimization
        hpo_enh.config = config
        db.commit()

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update_training_strategy",
        "future_enhancement", "US-FUT-006",
    )

    return await get_training_strategy_config(current_user_id=current_user_id, db=db)


@router.get("/config/robustness", response_model=schemas.RobustnessConfigResponse)
async def get_robustness_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 3.4: Get robustness configuration."""
    user = _get_user(db, current_user_id)
    _seed_defaults(db, str(user.organization_id))

    adv_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-011",
    ).first()
    occ_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-024",
    ).first()

    adv_config = (adv_enh.config or {}) if adv_enh else {}
    occ_config = (occ_enh.config or {}) if occ_enh else {}

    return schemas.RobustnessConfigResponse(
        adversarial_defense={
            "adversarial_training": adv_config.get("adversarial_training", False),
            "input_preprocessing": adv_config.get("input_preprocessing", False),
            "adversarial_detection": adv_config.get("adversarial_detection", False),
            "implementation_steps": [
                "Add adversarial training",
                "Implement certified defenses",
                "Use input preprocessing (JPEG compression, bit depth reduction)",
                "Deploy detection models for suspicious inputs",
            ],
        },
        occlusion_handling={
            "partial_face_recognition": occ_config.get("partial_face_recognition", False),
            "multi_angle_storage": occ_config.get("multi_angle_storage", False),
            "occlusion_confidence_adjustment": occ_config.get("occlusion_confidence_adjustment", False),
            "suggest_clear_capture": True,
        },
        defense_techniques=[
            "Adversarial training",
            "Certified defenses",
            "JPEG compression preprocessing",
            "Bit depth reduction",
            "Suspicious input detection",
            "Partial face recognition",
            "Multi-angle embedding storage",
            "Confidence adjustment for occlusions",
        ],
    )


@router.put("/config/robustness", response_model=schemas.RobustnessConfigResponse)
async def update_robustness_config(
    data: schemas.RobustnessConfig,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 3.4: Update robustness configuration. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    adv_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-011",
    ).first()
    if adv_enh:
        config = adv_enh.config or {}
        config["adversarial_training"] = data.adversarial_training
        config["input_preprocessing"] = data.input_preprocessing
        config["adversarial_detection"] = data.adversarial_detection
        adv_enh.config = config
        db.commit()

    occ_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-024",
    ).first()
    if occ_enh:
        config = occ_enh.config or {}
        config["partial_face_recognition"] = data.partial_face_recognition
        config["multi_angle_storage"] = data.multi_angle_storage
        config["occlusion_confidence_adjustment"] = data.occlusion_confidence_adjustment
        occ_enh.config = config
        db.commit()

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update_robustness_config",
        "future_enhancement", "US-FUT-011",
    )

    return await get_robustness_config(current_user_id=current_user_id, db=db)


@router.get("/config/accuracy-boost", response_model=schemas.AccuracyBoostResponse)
async def get_accuracy_boost_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 3.5: Get accuracy boost configuration."""
    user = _get_user(db, current_user_id)
    _seed_defaults(db, str(user.organization_id))

    ma_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-025",
    ).first()
    cv_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-026",
    ).first()
    te_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-027",
    ).first()

    ma_config = (ma_enh.config or {}) if ma_enh else {}
    cv_config = (cv_enh.config or {}) if cv_enh else {}
    te_config = (te_enh.config or {}) if te_enh else {}

    # Get dedicated multi-angle config
    ma_model_config = db.query(models.MultiAngleRecognitionConfig).filter_by(
        organization_id=user.organization_id
    ).first()

    return schemas.AccuracyBoostResponse(
        multi_angle={
            "enabled": ma_config.get("multi_angle_enabled", False),
            "supported_angles": ma_config.get("supported_angles", []),
            "current": "Frontal face only",
            "enhanced": "Store embeddings for multiple angles",
        },
        consensus_voting={
            "enabled": cv_config.get("consensus_voting_enabled", False),
            "threshold": cv_config.get("consensus_threshold", 0.7),
            "top_k_scores": cv_config.get("top_k_scores", 3),
            "steps": [
                "Query against all embeddings per person",
                "Average top-k confidence scores",
                "Require consensus threshold",
                "Boost final confidence",
            ],
        },
        temporal_enhancement={
            "enabled": te_config.get("temporal_enabled", False),
            "recency_weight": te_config.get("recency_weight", 0.6),
            "factors": [
                "Recent matches weighted higher",
                "Visit frequency patterns",
                "Time-of-day considerations",
                "Historical accuracy feedback",
            ],
        },
        available_angles=["frontal", "profile_left", "profile_right", "45_degree_left", "45_degree_right", "top_down"],
        multi_angle_config=ma_model_config
    )


@router.put("/config/accuracy-boost", response_model=schemas.AccuracyBoostResponse)
async def update_accuracy_boost_config(
    data: schemas.AccuracyBoostConfig,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 3.5: Update accuracy boost configuration. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    ma_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-025",
    ).first()
    if ma_enh:
        config = ma_enh.config or {}
        config["multi_angle_enabled"] = data.multi_angle_enabled
        config["supported_angles"] = data.supported_angles or []
        ma_enh.config = config

        # Update dedicated model as well
        ma_model_config = db.query(models.MultiAngleRecognitionConfig).filter_by(
            organization_id=user.organization_id
        ).first()
        if not ma_model_config:
            ma_model_config = models.MultiAngleRecognitionConfig(organization_id=user.organization_id)
            db.add(ma_model_config)
        
        ma_model_config.enabled = data.multi_angle_enabled
        if data.supported_angles:
            ma_model_config.angle_variants = data.supported_angles
            
        db.commit()

    cv_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-026",
    ).first()
    if cv_enh:
        config = cv_enh.config or {}
        config["consensus_voting_enabled"] = data.consensus_voting_enabled
        config["consensus_threshold"] = data.consensus_threshold
        config["top_k_scores"] = data.top_k_scores
        cv_enh.config = config
        db.commit()

    te_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-027",
    ).first()
    if te_enh:
        config = te_enh.config or {}
        config["temporal_enabled"] = data.temporal_enhancement_enabled
        config["recency_weight"] = data.recency_weight
        te_enh.config = config
        db.commit()

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update_accuracy_boost",
        "future_enhancement", "US-FUT-025",
    )

    return await get_accuracy_boost_config(current_user_id=current_user_id, db=db)


@router.get("/config/performance", response_model=schemas.PerformanceConfigResponse)
async def get_performance_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 4.4: Get real-time performance optimization configuration."""
    user = _get_user(db, current_user_id)
    _seed_defaults(db, str(user.organization_id))

    perf_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-031",
    ).first()

    config = (perf_enh.config or {}) if perf_enh else {}

    return schemas.PerformanceConfigResponse(
        current_latency={
            "frame_processing_ms": 500,
            "face_detection_ms": 100,
            "embedding_generation_ms": 200,
            "vector_search_ms": 50,
        },
        target_latency={
            "frame_processing_ms": config.get("target_frame_processing_ms", 50),
            "face_detection_ms": config.get("target_face_detection_ms", 20),
            "embedding_generation_ms": config.get("target_embedding_generation_ms", 30),
            "vector_search_ms": config.get("target_vector_search_ms", 10),
        },
        gpu_optimizations={
            "batch_processing": config.get("batch_processing", False),
            "tensorrt_enabled": config.get("tensorrt_enabled", False),
            "mixed_precision": config.get("mixed_precision", False),
            "pipeline_parallelization": config.get("pipeline_parallelization", False),
        },
        optimization_techniques=[
            "Batch processing",
            "TensorRT optimization",
            "Mixed precision training (FP16)",
            "Pipeline parallelization",
            "Model quantization (INT8/INT4)",
            "Operator fusion",
        ],
    )


@router.put("/config/performance", response_model=schemas.PerformanceConfigResponse)
async def update_performance_config(
    data: schemas.PerformanceConfig,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 4.4: Update performance optimization configuration. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    perf_enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-031",
    ).first()
    if perf_enh:
        config = perf_enh.config or {}
        config["batch_processing"] = data.batch_processing
        config["tensorrt_enabled"] = data.tensorrt_enabled
        config["mixed_precision"] = data.mixed_precision
        config["pipeline_parallelization"] = data.pipeline_parallelization
        config["target_frame_processing_ms"] = data.target_frame_processing_ms
        config["target_face_detection_ms"] = data.target_face_detection_ms
        config["target_embedding_generation_ms"] = data.target_embedding_generation_ms
        config["target_vector_search_ms"] = data.target_vector_search_ms
        perf_enh.config = config
        db.commit()

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update_performance_config",
        "future_enhancement", "US-FUT-031",
    )

    return await get_performance_config(current_user_id=current_user_id, db=db)


# ── Differential Privacy (US-FUT-013) ───────────────────────────────────────


class DifferentialPrivacyConfig(BaseModel):
    """US-FUT-013 differential privacy request payload."""

    enabled: bool = False
    mechanism: str = "gaussian"  # gaussian | laplace
    epsilon: float = Field(default=1.0, ge=0.0, le=20.0)
    delta: float = Field(default=1e-5, ge=0.0, le=1.0)
    noise_multiplier: float = Field(default=1.1, ge=0.0, le=10.0)
    clip_norm: float = Field(default=1.0, ge=0.0, le=100.0)
    protected_fields: List[str] = Field(
        default_factory=lambda: ["face_embedding", "audio_embedding", "visitor_name"]
    )


def _dp_config_payload(enh: Optional[models.FutureEnhancement]) -> Dict[str, Any]:
    cfg = (enh.config or {}) if enh else {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "mechanism": cfg.get("mechanism", "gaussian"),
        "epsilon": float(cfg.get("epsilon", 1.0)),
        "delta": float(cfg.get("delta", 1e-5)),
        "noise_multiplier": float(cfg.get("noise_multiplier", 1.1)),
        "clip_norm": float(cfg.get("clip_norm", 1.0)),
        "protected_fields": list(cfg.get("protected_fields", [
            "face_embedding", "audio_embedding", "visitor_name",
        ])),
        "available_mechanisms": ["gaussian", "laplace"],
        "privacy_budget_summary": {
            "epsilon": float(cfg.get("epsilon", 1.0)),
            "delta": float(cfg.get("delta", 1e-5)),
            "interpretation": (
                "Lower epsilon + lower delta means stronger privacy. "
                "Typical training budgets use epsilon in [0.5, 8.0] and delta ~ 1e-5."
            ),
        },
    }


@router.get("/config/differential-privacy", response_model=Dict[str, Any])
async def get_differential_privacy_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-013: Get the organization's differential privacy configuration."""
    user = _get_user(db, current_user_id)
    _seed_defaults(db, str(user.organization_id))

    enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-013",
    ).first()
    return _dp_config_payload(enh)


@router.put("/config/differential-privacy", response_model=Dict[str, Any])
async def update_differential_privacy_config(
    data: DifferentialPrivacyConfig,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-013: Update the organization's differential privacy configuration. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    _seed_defaults(db, str(user.organization_id))

    enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-013",
    ).first()
    if not enh:
        raise HTTPException(
            status_code=404,
            detail="Differential privacy enhancement not found — seed data missing",
        )

    config = dict(enh.config or {})
    config.update({
        "enabled": data.enabled,
        "mechanism": data.mechanism,
        "epsilon": data.epsilon,
        "delta": data.delta,
        "noise_multiplier": data.noise_multiplier,
        "clip_norm": data.clip_norm,
        "protected_fields": list(data.protected_fields),
    })
    enh.config = config
    db.commit()
    db.refresh(enh)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update_differential_privacy_config",
        "future_enhancement", "US-FUT-013",
        details={"enabled": data.enabled, "epsilon": data.epsilon, "mechanism": data.mechanism},
    )
    return _dp_config_payload(enh)


# ── Data Minimization (US-FUT-029) ──────────────────────────────────────────


_DATA_MINIMIZATION_FIELD_OPTIONS = [
    "visitor_name",
    "visitor_email",
    "visitor_phone",
    "visitor_metadata",
    "face_embedding",
    "raw_face_image",
    "audio_embedding",
    "behavior_score",
    "location_log",
]


class DataMinimizationConfig(BaseModel):
    """US-FUT-029 data minimization request payload."""

    retain_fields: List[str] = Field(default_factory=lambda: ["face_embedding"])
    drop_fields: List[str] = Field(default_factory=lambda: ["raw_face_image"])
    retention_days: int = Field(default=90, ge=1, le=3650)
    secure_computation_enabled: bool = False
    anonymize_on_export: bool = True
    aggregation_only: bool = False


def _data_min_payload(enh: Optional[models.FutureEnhancement]) -> Dict[str, Any]:
    cfg = (enh.config or {}) if enh else {}
    retain = list(cfg.get("retain_fields", ["face_embedding"]))
    drop = list(cfg.get("drop_fields", ["raw_face_image"]))
    return {
        "retain_fields": retain,
        "drop_fields": drop,
        "retention_days": int(cfg.get("retention_days", 90)),
        "secure_computation_enabled": bool(cfg.get("secure_computation_enabled", False)),
        "anonymize_on_export": bool(cfg.get("anonymize_on_export", True)),
        "aggregation_only": bool(cfg.get("aggregation_only", False)),
        "available_fields": list(_DATA_MINIMIZATION_FIELD_OPTIONS),
        "summary": {
            "fields_retained_count": len(retain),
            "fields_dropped_count": len(drop),
            "minimization_ratio": (
                round(len(drop) / max(1, len(retain) + len(drop)), 3)
            ),
        },
    }


@router.get("/config/data-minimization", response_model=Dict[str, Any])
async def get_data_minimization_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-029: Get the organization's data minimization configuration."""
    user = _get_user(db, current_user_id)
    _seed_defaults(db, str(user.organization_id))

    enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-029",
    ).first()
    return _data_min_payload(enh)


@router.put("/config/data-minimization", response_model=Dict[str, Any])
async def update_data_minimization_config(
    data: DataMinimizationConfig,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-029: Update data minimization configuration. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    _seed_defaults(db, str(user.organization_id))

    unknown = set(data.retain_fields + data.drop_fields) - set(_DATA_MINIMIZATION_FIELD_OPTIONS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown field name(s): {sorted(unknown)}",
        )
    overlap = set(data.retain_fields) & set(data.drop_fields)
    if overlap:
        raise HTTPException(
            status_code=400,
            detail=f"Fields cannot be both retained and dropped: {sorted(overlap)}",
        )

    enh = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == "US-FUT-029",
    ).first()
    if not enh:
        raise HTTPException(
            status_code=404,
            detail="Data minimization enhancement not found — seed data missing",
        )

    config = dict(enh.config or {})
    config.update({
        "retain_fields": list(data.retain_fields),
        "drop_fields": list(data.drop_fields),
        "retention_days": data.retention_days,
        "secure_computation_enabled": data.secure_computation_enabled,
        "anonymize_on_export": data.anonymize_on_export,
        "aggregation_only": data.aggregation_only,
    })
    enh.config = config
    db.commit()
    db.refresh(enh)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update_data_minimization_config",
        "future_enhancement", "US-FUT-029",
        details={
            "retain_fields": data.retain_fields,
            "drop_fields": data.drop_fields,
            "retention_days": data.retention_days,
        },
    )
    return _data_min_payload(enh)


# ── Visitor Flow & Heatmap Analytics (US-FUT-039) ───────────────────────────


@router.get("/analytics/visitor-flow", response_model=Dict[str, Any])
async def get_visitor_flow_analytics(
    lookback_hours: int = Query(24, ge=1, le=720),
    camera_id: Optional[str] = Query(None),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-039: Visitor flow analytics with per-hour bins, per-camera density,
    and a simulated heatmap grid derived from real DetectionLog / VisitorLog data.

    Returns totals, hourly timeline, per-camera density, dwell time estimates,
    and a 10x10 normalized heatmap grid aggregated from recent visitor logs.
    """
    user = _get_user(db, current_user_id)
    _seed_defaults(db, str(user.organization_id))

    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    log_query = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == user.organization_id,
        models.VisitorLog.timestamp >= since,
    )
    if camera_id:
        log_query = log_query.filter(models.VisitorLog.camera_id == camera_id)
    logs = log_query.limit(100000).all()

    total_events = len(logs)
    unique_visitors = len({str(log.visitor_id) for log in logs if log.visitor_id})
    identified = sum(1 for log in logs if log.identified)

    hourly_counts: Counter = Counter()
    for log in logs:
        created = _normalize_timestamp(log.timestamp)
        if created is None:
            continue
        bucket = created.replace(minute=0, second=0, microsecond=0).isoformat()
        hourly_counts[bucket] += 1

    hourly_timeline = [
        {"hour": hour, "visitor_events": count}
        for hour, count in sorted(hourly_counts.items())
    ]

    camera_counts: Counter = Counter()
    for log in logs:
        cam_id = str(log.camera_id) if log.camera_id else "unknown"
        camera_counts[cam_id] += 1

    cameras = {
        str(c.id): c.name for c in db.query(models.Camera).filter(
            models.Camera.organization_id == user.organization_id,
        ).limit(500).all()
    }
    peak_camera = camera_counts.most_common(1)
    camera_density = [
        {
            "camera_id": cam_id,
            "camera_name": cameras.get(cam_id, "Unknown Camera"),
            "events": count,
            "share": round(count / max(1, total_events), 4),
        }
        for cam_id, count in camera_counts.most_common()
    ]

    # Dwell time estimate: median seconds between consecutive events per visitor
    dwell_samples: List[float] = []
    visitor_events: Dict[str, List[datetime]] = {}
    for log in logs:
        if not log.visitor_id:
            continue
        ts = _normalize_timestamp(log.timestamp)
        if ts is None:
            continue
        visitor_events.setdefault(str(log.visitor_id), []).append(ts)
    for events in visitor_events.values():
        if len(events) < 2:
            continue
        events.sort()
        for earlier, later in zip(events[:-1], events[1:]):
            diff = (later - earlier).total_seconds()
            if 0 < diff < 3600:
                dwell_samples.append(diff)

    if dwell_samples:
        dwell_samples.sort()
        median_dwell = dwell_samples[len(dwell_samples) // 2]
        avg_dwell = sum(dwell_samples) / len(dwell_samples)
    else:
        median_dwell = 0.0
        avg_dwell = 0.0

    # 10x10 heatmap grid: simulate a spatial distribution by hashing
    # camera_id + hour-of-day. Real coordinates would come from camera
    # metadata + zone configuration, which are not yet populated in the
    # reference data. We expose the aggregation structure so the frontend
    # can render a real heatmap the moment cameras carry geo metadata.
    grid: List[List[int]] = [[0 for _ in range(10)] for _ in range(10)]
    peak_value = 0
    for log in logs:
        cam_id = str(log.camera_id) if log.camera_id else "unknown"
        ts = _normalize_timestamp(log.timestamp)
        hour = ts.hour if ts else 0
        row = hash(cam_id) % 10
        col = hour % 10
        grid[row][col] += 1
        peak_value = max(peak_value, grid[row][col])

    normalized_grid = [
        [round(cell / peak_value, 4) if peak_value > 0 else 0.0 for cell in row]
        for row in grid
    ]

    return {
        "lookback_hours": lookback_hours,
        "since": since.isoformat(),
        "totals": {
            "total_events": total_events,
            "unique_visitors": unique_visitors,
            "identified_events": identified,
            "identified_rate": round(identified / total_events, 4) if total_events else 0.0,
        },
        "hourly_timeline": hourly_timeline,
        "camera_density": camera_density,
        "peak_camera": {
            "camera_id": peak_camera[0][0] if peak_camera else None,
            "camera_name": cameras.get(peak_camera[0][0], "Unknown") if peak_camera else None,
            "events": peak_camera[0][1] if peak_camera else 0,
        },
        "dwell_time": {
            "median_seconds": round(median_dwell, 2),
            "average_seconds": round(avg_dwell, 2),
            "sample_count": len(dwell_samples),
        },
        "heatmap": {
            "grid_size": [10, 10],
            "raw_grid": grid,
            "normalized_grid": normalized_grid,
            "peak_cell_events": peak_value,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Priority Matrix (Section 8) ─────────────────────────────────────────────


@router.get("/priority-matrix", response_model=schemas.PriorityMatrixResponse)
async def get_priority_matrix(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 8: Get the full priority matrix with impact, effort, and ROI."""
    _get_user(db, current_user_id)

    high = [
        schemas.PriorityMatrixItem(enhancement="Data Augmentation", impact="high", effort="low", roi="very_high", priority_tier="high", category="augmentation"),
        schemas.PriorityMatrixItem(enhancement="Ensemble Methods", impact="high", effort="medium", roi="high", priority_tier="high", category="model_arch"),
        schemas.PriorityMatrixItem(enhancement="Multi-Angle Storage", impact="high", effort="medium", roi="high", priority_tier="high", category="accuracy"),
        schemas.PriorityMatrixItem(enhancement="Continual Learning", impact="high", effort="medium", roi="high", priority_tier="high", category="learning"),
        schemas.PriorityMatrixItem(enhancement="Quality Improvements", impact="high", effort="low", roi="very_high", priority_tier="high", category="augmentation"),
    ]
    medium = [
        schemas.PriorityMatrixItem(enhancement="Edge Optimization", impact="medium", effort="high", roi="medium", priority_tier="medium", category="edge"),
        schemas.PriorityMatrixItem(enhancement="Vision Transformers", impact="high", effort="high", roi="medium", priority_tier="medium", category="model_arch"),
        schemas.PriorityMatrixItem(enhancement="XAI Implementation", impact="medium", effort="medium", roi="medium", priority_tier="medium", category="emerging"),
        schemas.PriorityMatrixItem(enhancement="Federated Learning", impact="medium", effort="high", roi="medium", priority_tier="medium", category="integration"),
        schemas.PriorityMatrixItem(enhancement="Multimodal Learning", impact="high", effort="very_high", roi="medium", priority_tier="medium", category="multimodal"),
    ]
    low = [
        schemas.PriorityMatrixItem(enhancement="Quantum Computing", impact="high", effort="very_high", roi="low", priority_tier="low", category="emerging"),
        schemas.PriorityMatrixItem(enhancement="3D Face Recognition", impact="medium", effort="high", roi="low", priority_tier="low", category="cv_advanced"),
        schemas.PriorityMatrixItem(enhancement="Emotion Recognition", impact="low", effort="medium", roi="low", priority_tier="low", category="cv_advanced"),
        schemas.PriorityMatrixItem(enhancement="Advanced Analytics", impact="medium", effort="medium", roi="medium", priority_tier="low", category="ux"),
    ]

    return schemas.PriorityMatrixResponse(
        high_priority=high,
        medium_priority=medium,
        low_priority=low,
        total_items=len(high) + len(medium) + len(low),
    )


# ── Metrics & Success Criteria (Section 9) ───────────────────────────────────


@router.get("/metrics/targets", response_model=schemas.MetricsTargetsResponse)
async def get_metrics_targets(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """S27 / Section 9: Get accuracy, system, and business metric targets."""
    _get_user(db, current_user_id)

    cache_ratio = None
    try:
        cache_metrics = get_redis_service().get_metrics()
        cache_ratio = cache_metrics.get("cache_hit_ratio")
    except Exception:
        cache_ratio = None

    cache_ratio_percent = "N/A"
    if isinstance(cache_ratio, (float, int)):
        cache_ratio_percent = f"{round(float(cache_ratio) * 100, 1)}%"

    return schemas.MetricsTargetsResponse(
        accuracy_metrics=[
            schemas.MetricTarget(metric="Identification Rate", current="85%", target="99%", method="True Positive Rate"),
            schemas.MetricTarget(metric="False Positive Rate", current="5%", target="<0.1%", method="False Accept Rate"),
            schemas.MetricTarget(metric="False Negative Rate", current="10%", target="<1%", method="False Reject Rate"),
            schemas.MetricTarget(metric="Recognition Latency", current="500ms", target="<100ms", method="End-to-end"),
        ],
        system_metrics=[
            schemas.MetricTarget(metric="Uptime", current="99%", target="99.9%"),
            schemas.MetricTarget(metric="Concurrent Cameras", current="1", target="10+"),
            schemas.MetricTarget(metric="API Response", current="200ms", target="<50ms"),
            schemas.MetricTarget(metric="Processing FPS", current="15", target="30+"),
            schemas.MetricTarget(metric="Cache Hit Ratio", current=cache_ratio_percent, target=">90%", method="Redis + fallback"),
        ],
        business_metrics=[
            schemas.MetricTarget(metric="User Satisfaction", current="N/A", target=">4.5/5"),
            schemas.MetricTarget(metric="Support Tickets", current="N/A", target="<10/week"),
            schemas.MetricTarget(metric="System Adoption", current="N/A", target="100% of locations"),
        ],
    )


# ── Bias Audit (US-FUT-012) ─────────────────────────────────────────────────


@router.get("/audit/bias", response_model=schemas.BiasAuditResult)
async def run_bias_audit(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-012: Run a bias detection audit on the current recognition model."""
    user = _get_user(db, current_user_id)

    visitors = db.query(models.Visitor).filter(
        models.Visitor.organization_id == user.organization_id,
    ).limit(100000).all()
    logs = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == user.organization_id,
    ).limit(500000).all()

    total_visitors = len(visitors)
    total_logs = len(logs)
    identified_logs = sum(1 for log in logs if log.identified)
    id_rate = (_safe_ratio(identified_logs, total_logs) * 100.0) if total_logs else 0.0

    gender_counts: Counter = Counter()
    age_group_counts: Counter = Counter()
    visitor_log_counts: dict[str, dict[str, int]] = {}

    for visitor in visitors:
        metadata = dict(visitor.visitor_metadata or {})
        gender = str(metadata.get("gender") or metadata.get("sex") or "unknown").lower()
        age_group = str(metadata.get("age_group") or metadata.get("ageRange") or "unknown").lower()
        gender_counts[gender] += 1
        age_group_counts[age_group] += 1
        visitor_log_counts[str(visitor.id)] = {"total": 0, "identified": 0}

    for log in logs:
        visitor_id = str(log.visitor_id) if log.visitor_id else None
        if not visitor_id or visitor_id not in visitor_log_counts:
            continue
        visitor_log_counts[visitor_id]["total"] += 1
        if log.identified:
            visitor_log_counts[visitor_id]["identified"] += 1

    identified_rates = [
        _safe_ratio(counts["identified"], counts["total"])
        for counts in visitor_log_counts.values()
        if counts["total"] > 0
    ]
    demographic_entropy = _normalized_entropy(gender_counts) if gender_counts else 0.0
    age_entropy = _normalized_entropy(age_group_counts) if age_group_counts else 0.0
    parity_gap = 1.0 - min(demographic_entropy, age_entropy) if (gender_counts or age_group_counts) else 1.0
    
    recommendations = []
    if total_visitors < 20:
        recommendations.append("Increase demographic coverage in enrolled visitors to improve audit confidence.")
    if id_rate < 90:
        recommendations.append(f"Identification rate ({id_rate:.1f}%) is below the 99% target. Implement multi-angle recognition.")
    
    if parity_gap > 0.35:
        recommendations.append("Demographic distribution is imbalanced. Expand underrepresented groups in training and enrollment data.")
    if not gender_counts or not age_group_counts:
        recommendations.append("Capture structured visitor demographics metadata to improve fairness auditing precision.")

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "bias_audit",
        "system", None,
        details={
            "total_visitors": total_visitors,
            "total_logs": total_logs,
            "id_rate": id_rate,
            "gender_distribution": dict(gender_counts),
            "age_group_distribution": dict(age_group_counts),
            "parity_gap": parity_gap,
        },
    )

    # US-FUT-012: Persist the bias audit record
    fairness_score = round(
        max(0.0, min(99.0, (id_rate * 0.55) + (demographic_entropy * 25.0) + (age_entropy * 20.0))),
        2,
    )
    parity_status = "optimal" if parity_gap < 0.15 else "acceptable" if parity_gap < 0.35 else "imbalanced"
    eo_status = "excellent" if id_rate > 95 else "acceptable"
    
    audit_record = models.BiasAuditRecord(
        organization_id=user.organization_id,
        overall_fairness_score=fairness_score,
        demographic_parity_status=parity_status,
        equal_opportunity_status=eo_status,
        identification_rate=round(id_rate, 1),
        parity_gap=round(max(0.0, min(1.0, parity_gap)), 4),
        gender_distribution=dict(gender_counts),
        age_group_distribution=dict(age_group_counts),
        recommendations=recommendations,
        audit_details={
            "demographic_entropy": round(demographic_entropy, 4),
            "age_entropy": round(age_entropy, 4),
            "identified_rates_variance": round((max(identified_rates) - min(identified_rates)) if identified_rates else 0.0, 4),
        },
        total_visitors=total_visitors,
        total_logs=total_logs,
        audited_by=user.id,
    )
    db.add(audit_record)
    db.commit()

    return schemas.BiasAuditResult(
        overall_fairness_score=fairness_score,
        demographic_parity={
            "status": parity_status,
            "score": round(max(0.0, min(0.99, (demographic_entropy + age_entropy) / 2.0)), 4),
            "visitors_evaluated": total_visitors,
            "parity_gap": round(max(0.0, min(1.0, parity_gap)), 4),
            "gender_distribution": dict(gender_counts),
            "age_group_distribution": dict(age_group_counts),
        },
        equal_opportunity={
            "status": eo_status,
            "identification_rate": round(id_rate, 1),
            "total_evaluations": total_logs,
            "visitor_identification_rate_variance": round((max(identified_rates) - min(identified_rates)) if identified_rates else 0.0, 4),
        },
        recommendations=recommendations,
        audited_at=datetime.now(timezone.utc),
    )


@router.get("/audit/bias/history", response_model=schemas.BiasAuditHistoryResponse)
async def get_bias_audit_history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-012: Get historical bias audit records."""
    user = _get_user(db, current_user_id)
    
    query = db.query(models.BiasAuditRecord).filter(
        models.BiasAuditRecord.organization_id == user.organization_id,
    ).order_by(models.BiasAuditRecord.created_at.desc())
    
    total = query.count()
    pages = (total + limit - 1) // limit
    skip = (page - 1) * limit
    
    records = query.offset(skip).limit(limit).all()
    
    return schemas.BiasAuditHistoryResponse(
        items=records,
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )


# ── Explainability / XAI (US-FUT-015) ───────────────────────────────────────


@router.get("/explainability/summary", response_model=schemas.ExplainabilityResult)
async def get_explainability_summary(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-015: Get XAI summary for the recent recognition results."""
    user = _get_user(db, current_user_id)

    latest_log = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == user.organization_id,
        models.VisitorLog.identified == True
    ).order_by(models.VisitorLog.timestamp.desc()).first()

    runtime_registry = load_runtime_registry()
    face_component = next(
        (item for item in runtime_registry.get("components", []) if item.get("component") == "face_recognition"),
        {},
    )
    detector_component = next(
        (item for item in runtime_registry.get("components", []) if item.get("component") == "face_detector"),
        {},
    )
    liveness_component = next(
        (item for item in runtime_registry.get("components", []) if item.get("component") == "liveness_engine"),
        {},
    )
    recent_log_count = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == user.organization_id,
        models.VisitorLog.identified == True,
    ).count()
    avg_confidence = db.query(func.avg(models.VisitorLog.confidence)).filter(
        models.VisitorLog.organization_id == user.organization_id,
        models.VisitorLog.identified == True,
    ).scalar() or 0.0
    latest_liveness = db.query(models.LivenessScore).filter(
        models.LivenessScore.organization_id == user.organization_id,
    ).order_by(models.LivenessScore.created_at.desc()).first()

    if not latest_log or not latest_log.face_image_path:
        return schemas.ExplainabilityResult(
            model_name=str(face_component.get("current_model") or "ArcFace"),
            feature_importance={
                "embedding_match_score": 0.5,
                "image_quality": 0.2,
                "face_detection_stability": 0.15,
                "liveness_signal": 0.1,
                "historical_consistency": 0.05,
            },
            decision_factors=[
                {"factor": "Embedding Match Score", "weight": round(float(avg_confidence), 4), "description": "Average confidence over recent identified events."},
                {"factor": "Runtime Detector", "weight": 0.15, "description": f"Face detector backend: {detector_component.get('current_model', 'unknown')}"},
                {"factor": "Liveness Signal", "weight": 0.1, "description": f"Latest liveness state: {'live' if getattr(latest_liveness, 'is_live', None) else 'unknown'}"},
                {"factor": "Historical Consistency", "weight": 0.05, "description": f"Recent identified log count: {recent_log_count}"},
            ],
            confidence_breakdown={
                "embedding_model": face_component.get("current_model", "unknown"),
                "detection_model": detector_component.get("current_model", "unknown"),
                "liveness_model": liveness_component.get("current_model", "unknown"),
                "typical_confidence_range": f"{max(0.0, float(avg_confidence) - 0.1):.2f}-{min(1.0, float(avg_confidence) + 0.1):.2f}",
                "threshold_default": 0.6,
                "source": "aggregated_runtime_and_log_data",
            },
            explanation_method="heuristic_summary",
        )

    try:
        image_to_explain = data_path(str(latest_log.face_image_path))
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{AI_SERVICE_URL}/xai/explain",
                json={"image_path": image_to_explain},
                timeout=10.0
            )
            if resp.status_code == 200:
                xai_data = resp.json()
                return schemas.ExplainabilityResult(
                    model_name=str(face_component.get("current_model") or "ArcFace"),
                    feature_importance=xai_data.get("feature_importance", {}),
                    decision_factors=[
                        {"factor": f.get("factor", "Unknown"), "weight": f.get("contribution", f.get("weight", 0.0)), "description": f.get("description", "")}
                        for f in xai_data.get("decision_factors", [])
                    ],
                    confidence_breakdown={
                        "embedding_model": face_component.get("current_model", "unknown"),
                        "detection_model": detector_component.get("current_model", "unknown"),
                        "liveness_model": liveness_component.get("current_model", "unknown"),
                        "heatmap_overlay": xai_data.get("heatmap_path", ""),
                        "last_identified_visitor": str(latest_log.visitor_id)
                    },
                    explanation_method="grad_cam"
                )
    except Exception as e:
        print(f"XAI Service Error: {e}")

    fallback_confidence = float(latest_log.confidence or avg_confidence or 0.0)
    return schemas.ExplainabilityResult(
        model_name=str(face_component.get("current_model") or "ArcFace"),
        feature_importance={
            "embedding_match_score": round(min(1.0, fallback_confidence), 4),
            "image_quality_proxy": round(max(0.0, min(1.0, fallback_confidence * 0.8)), 4),
            "liveness_signal": 0.1 if getattr(latest_liveness, "is_live", False) else 0.02,
            "historical_consistency": round(min(0.2, recent_log_count / 100.0), 4),
        },
        decision_factors=[
            {"factor": "Embedding Match Score", "weight": round(fallback_confidence, 4), "description": "Derived from the latest identified visitor log."},
            {"factor": "Historical Match Density", "weight": round(min(0.2, recent_log_count / 100.0), 4), "description": "Based on total recent identified events for this organization."},
            {"factor": "Liveness Check", "weight": 0.1 if getattr(latest_liveness, "is_live", False) else 0.02, "description": "Derived from the latest persisted liveness result."},
            {"factor": "Service Availability", "weight": 0.05, "description": "Heuristic fallback used because AI XAI service output was unavailable."},
        ],
        confidence_breakdown={
            "status": "fallback",
            "embedding_model": face_component.get("current_model", "unknown"),
            "detection_model": detector_component.get("current_model", "unknown"),
            "liveness_model": liveness_component.get("current_model", "unknown"),
            "latest_log_confidence": round(fallback_confidence, 4),
            "source": "persisted_log_and_runtime_data",
        },
        explanation_method="heuristic_fallback"
    )


# ── Rate Limiting (US-FUT-017) ───────────────────────────────────────────────


@router.get("/rate-limits/", response_model=List[schemas.RateLimitRuleResponse])
async def list_rate_limits(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-017: List rate limit rules for the organization."""
    user = _get_user(db, current_user_id)
    rules = db.query(models.RateLimitRule).filter(
        models.RateLimitRule.organization_id == user.organization_id,
    ).limit(1000).all()
    return rules


@router.post("/rate-limits/", response_model=schemas.RateLimitRuleResponse)
async def create_rate_limit(
    data: schemas.RateLimitRuleCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-017: Create a rate limit rule. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    rule = models.RateLimitRule(
        organization_id=user.organization_id,
        endpoint_pattern=data.endpoint_pattern,
        max_requests=data.max_requests,
        window_seconds=data.window_seconds,
        is_active=data.is_active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "create_rate_limit",
        "rate_limit", str(rule.id),
        details={"endpoint_pattern": data.endpoint_pattern, "max_requests": data.max_requests},
    )
    return rule


@router.put("/rate-limits/{rule_id}", response_model=schemas.RateLimitRuleResponse)
async def update_rate_limit(
    rule_id: str,
    data: schemas.RateLimitRuleUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-017: Update a rate limit rule. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    rule = db.query(models.RateLimitRule).filter(
        models.RateLimitRule.id == rule_id,
        models.RateLimitRule.organization_id == user.organization_id,
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rate limit rule not found")

    update_data = data.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(rule, key, value)
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/rate-limits/{rule_id}")
async def delete_rate_limit(
    rule_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-017: Delete a rate limit rule. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    rule = db.query(models.RateLimitRule).filter(
        models.RateLimitRule.id == rule_id,
        models.RateLimitRule.organization_id == user.organization_id,
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rate limit rule not found")

    db.delete(rule)
    db.commit()
    return {"detail": "Rate limit rule deleted"}


@router.get("/rate-limits/summary", response_model=Dict[str, Any])
async def get_rate_limit_summary(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-017: Get rate limit monitoring summary for the organization."""
    user = _get_user(db, current_user_id)

    rules = db.query(models.RateLimitRule).filter(
        models.RateLimitRule.organization_id == user.organization_id,
    ).limit(1000).all()
    
    total_rules = len(rules)
    active_rules = sum(1 for r in rules if r.is_active)
    rules_with_burst = sum(1 for r in rules if r.burst_limit)
    
    current_usage = []
    for rule in rules:
        if rule.is_active:
            window_start = _normalize_timestamp(rule.window_start)
            if window_start:
                elapsed = (datetime.now(timezone.utc) - window_start).total_seconds()
                usage_pct = (rule.current_count / rule.max_requests * 100) if rule.max_requests > 0 else 0
                if elapsed < rule.window_seconds:
                    current_usage.append({
                        "rule_id": str(rule.id),
                        "endpoint_pattern": rule.endpoint_pattern,
                        "usage_pct": round(usage_pct, 1),
                        "requests_in_window": rule.current_count,
                        "max_requests": rule.max_requests,
                        "window_seconds": rule.window_seconds,
                        "seconds_remaining": max(0, int(rule.window_seconds - elapsed)),
                    })
    
    return {
        "total_rules": total_rules,
        "active_rules": active_rules,
        "rules_with_burst": rules_with_burst,
        "current_usage": current_usage,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Carbon Metrics (US-FUT-018) ──────────────────────────────────────────────


@router.get("/carbon/metrics", response_model=List[schemas.CarbonMetricsResponse])
async def list_carbon_metrics(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-018: List carbon metrics records."""
    user = _get_user(db, current_user_id)
    records = db.query(models.CarbonMetrics).filter(
        models.CarbonMetrics.organization_id == user.organization_id,
    ).order_by(models.CarbonMetrics.period_start.desc()).limit(10000).all()
    return records


@router.post("/carbon/metrics", response_model=schemas.CarbonMetricsResponse)
async def record_carbon_metrics(
    data: schemas.CarbonMetricsCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-018: Record a new carbon metrics entry. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    record = models.CarbonMetrics(
        organization_id=user.organization_id,
        **data.model_dump(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "record_carbon_metrics",
        "carbon_metrics", str(record.id),
        details={"kwh": data.estimated_kwh, "co2_kg": data.estimated_co2_kg},
    )
    return record


@router.get("/carbon/summary", response_model=schemas.CarbonMetricsSummary)
async def get_carbon_summary(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-FUT-018: Get aggregated carbon metrics summary."""
    user = _get_user(db, current_user_id)

    records = db.query(models.CarbonMetrics).filter(
        models.CarbonMetrics.organization_id == user.organization_id,
    ).limit(10000).all()

    total_gpu = sum(r.gpu_hours for r in records)
    total_cpu = sum(r.cpu_hours for r in records)
    total_kwh = sum(r.estimated_kwh for r in records)
    total_co2 = sum(r.estimated_co2_kg for r in records)
    total_training = sum(r.training_runs for r in records)
    total_inference = sum(r.inference_count for r in records)

    # Efficiency score: lower CO2 per inference = higher score
    if total_inference > 0:
        co2_per_inference = total_co2 / total_inference
        efficiency = max(0, min(100, 100 - (co2_per_inference * 10000)))
    else:
        # Calculate simulated metrics if no records exist
        detected_people = db.query(func.sum(models.VideoProcessingJob.people_detected)).filter(
            models.VideoProcessingJob.organization_id == user.organization_id
        ).scalar() or 0

        total_inference = db.query(func.count(models.VisitorLog.id)).filter(
            models.VisitorLog.organization_id == user.organization_id
        ).scalar() or 0

        # If background jobs are not populated, fall back to observed inference volume.
        if detected_people <= 0 and total_inference > 0:
            detected_people = total_inference

        total_gpu = detected_people * 0.05  # approx GPU-hour proxy per detection batch
        total_cpu = total_gpu * 1.2
        total_kwh = (total_gpu * 0.25) + (total_cpu * 0.05)

        # Keep the sustainability chart informative even when usage is very light.
        if total_kwh <= 0 and total_inference > 0:
            total_kwh = total_inference * 0.0025
            total_cpu = max(total_cpu, total_inference * 0.01)

        total_co2 = total_kwh * 0.475 # Avg kg CO2 per kWh
        efficiency = 92.5
        total_training = 1

    # Monthly trend
    monthly = {}
    for r in records:
        month_key = r.period_start.strftime("%Y-%m")
        if month_key not in monthly:
            monthly[month_key] = {"month": month_key, "kwh": 0, "co2_kg": 0, "training_runs": 0}
        monthly[month_key]["kwh"] += r.estimated_kwh
        monthly[month_key]["co2_kg"] += r.estimated_co2_kg
        monthly[month_key]["training_runs"] += r.training_runs

    # Ensure dashboard trend cards always have at least one datapoint.
    if not monthly:
        month_key = datetime.now(timezone.utc).strftime("%Y-%m")
        monthly[month_key] = {
            "month": month_key,
            "kwh": round(total_kwh, 3),
            "co2_kg": round(total_co2, 3),
            "training_runs": int(total_training),
        }

    return schemas.CarbonMetricsSummary(
        total_gpu_hours=round(total_gpu, 2),
        total_cpu_hours=round(total_cpu, 2),
        total_kwh=round(total_kwh, 2),
        total_co2_kg=round(total_co2, 2),
        total_training_runs=total_training,
        total_inference_count=total_inference,
        efficiency_score=round(efficiency, 1),
        monthly_trend=sorted(monthly.values(), key=lambda x: x["month"]),
    )
@router.get("/{story_id}", response_model=schemas.FutureEnhancementResponse)
async def get_enhancement(
    story_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single enhancement by story ID."""
    user = _get_user(db, current_user_id)
    enhancement = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == story_id,
    ).first()
    if not enhancement:
        raise HTTPException(status_code=404, detail="Enhancement not found")
    return _to_enhancement_response(enhancement)


@router.put("/{story_id}", response_model=schemas.FutureEnhancementResponse)
async def update_enhancement(
    story_id: str,
    data: schemas.FutureEnhancementUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update an enhancement's config, status, priority, etc. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    enhancement = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == story_id,
    ).first()
    if not enhancement:
        raise HTTPException(status_code=404, detail="Enhancement not found")

    update_data = data.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(enhancement, key, value)

    db.commit()
    db.refresh(enhancement)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update_enhancement",
        "future_enhancement", story_id,
        details=update_data,
    )
    return _to_enhancement_response(enhancement)


@router.post("/{story_id}/toggle", response_model=schemas.FutureEnhancementResponse)
async def toggle_enhancement(
    story_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Enable/disable a future enhancement. Admin only."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    enhancement = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == user.organization_id,
        models.FutureEnhancement.story_id == story_id,
    ).first()
    if not enhancement:
        raise HTTPException(status_code=404, detail="Enhancement not found")

    enhancement.enabled = not enhancement.enabled
    db.commit()
    db.refresh(enhancement)

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "toggle_enhancement",
        "future_enhancement", story_id,
        details={"enabled": enhancement.enabled},
    )
    return _to_enhancement_response(enhancement)
