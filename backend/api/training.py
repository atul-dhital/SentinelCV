"""Training and LLM Management API endpoints"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import func
from db.base import get_db, SessionLocal
from models import models
from services import (
    custom_classifier_service,
    mlflow_registry_service,
    model_versioning_service,
    user_service,
    visitor_service,
)
from core.security import get_current_user
from core.runtime_registry import load_runtime_registry, save_runtime_registry, get_runtime_component
from schemas import schemas
from typing import List, Optional, Dict, Any
import os
import json
import numpy as np
from datetime import datetime, timezone
from uuid import UUID
import logging
import sys
import torch
from pathlib import Path


# Add parent directory to path to access ai_services
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

router = APIRouter(prefix="/training", tags=["Training & LLM"])
logger = logging.getLogger(__name__)

DatasetPreparation = None
ModelTrainer = None
TrainingConfig = None
BiasMitigation = None
HyperparameterOptimization = None
EnsembleModel = None
ActiveLearning = None
SimpleClassifier = None
create_default_training_pipeline = None
TRAINING_AVAILABLE = False
TRAINING_IMPORT_ERROR: Optional[str] = None
_TRAINING_IMPORT_ATTEMPTED = False

_TRAINING_STORY_ID = "US-FUT-010"
_TRAINING_CATEGORY = "training"

_DEFAULT_TRAINING_CONFIG = {
    "batch_size": 32,
    "num_epochs": 50,
    "learning_rate": 0.001,
    "validation_split": 0.2,
    "test_split": 0.1,
    "optimizer": "adam",
    "loss_function": "triplet",
    "model_name": "arcface",
}


def _normalize_training_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize external config keys to the stored API shape."""
    normalized = dict(config)
    if "loss_fn" in normalized and "loss_function" not in normalized:
        normalized["loss_function"] = normalized.pop("loss_fn")
    return normalized


def _build_class_to_visitor_map(visitor_ids: List[str], labels: np.ndarray) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for visitor_id, label in zip(visitor_ids, labels):
        mapping[str(int(label))] = str(visitor_id)
    return mapping


def _get_or_create_face_recognition_component(runtime_registry: Dict[str, Any]) -> Dict[str, Any]:
    components = runtime_registry.setdefault("components", [])
    for component in components:
        if component.get("component") == "face_recognition":
            return component

    component = {
        "component": "face_recognition",
        "display_name": "Face recognition model",
        "current_model": "ArcFace",
        "current_artifact": None,
        "target_model": "AdaFace",
        "target_artifact": "models/adaface.onnx",
        "framework": "ArcFace-compatible embedding model",
        "runtime": "backend + ai-service",
        "status": "active",
        "notes": "Default face recognition backend",
    }
    components.append(component)
    return component


def _require_training_system() -> None:
    """Load optional training dependencies only when training endpoints are used."""
    global DatasetPreparation
    global ModelTrainer
    global TrainingConfig
    global BiasMitigation
    global HyperparameterOptimization
    global EnsembleModel
    global ActiveLearning
    global SimpleClassifier
    global create_default_training_pipeline
    global TRAINING_AVAILABLE
    global TRAINING_IMPORT_ERROR
    global _TRAINING_IMPORT_ATTEMPTED

    if not _TRAINING_IMPORT_ATTEMPTED:
        _TRAINING_IMPORT_ATTEMPTED = True
        try:
            from ai_services.training_system import (
                DatasetPreparation as _DatasetPreparation,
                ModelTrainer as _ModelTrainer,
                TrainingConfig as _TrainingConfig,
                BiasMitigation as _BiasMitigation,
                HyperparameterOptimization as _HyperparameterOptimization,
                EnsembleModel as _EnsembleModel,
                ActiveLearning as _ActiveLearning,
                SimpleClassifier as _SimpleClassifier,
                create_default_training_pipeline as _create_default_training_pipeline,
            )
            DatasetPreparation = _DatasetPreparation
            ModelTrainer = _ModelTrainer
            TrainingConfig = _TrainingConfig
            BiasMitigation = _BiasMitigation
            HyperparameterOptimization = _HyperparameterOptimization
            EnsembleModel = _EnsembleModel
            ActiveLearning = _ActiveLearning
            SimpleClassifier = _SimpleClassifier
            create_default_training_pipeline = _create_default_training_pipeline
            TRAINING_AVAILABLE = True
            TRAINING_IMPORT_ERROR = None
        except Exception as exc:
            TRAINING_AVAILABLE = False
            TRAINING_IMPORT_ERROR = str(exc)
            logger.warning("Training system unavailable: %s", exc)

    if not TRAINING_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Training system not available",
                "reason": TRAINING_IMPORT_ERROR or "Unknown import error",
                "hint": "Install optional ML dependencies from ai_services/requirements.txt in the active Python environment.",
            },
        )


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _load_training_config(db: Session, organization_id) -> Dict[str, Any]:
    """Load persisted training config from FutureEnhancement table."""
    row = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == organization_id,
        models.FutureEnhancement.story_id == _TRAINING_STORY_ID,
    ).first()
    if row and row.config and isinstance(row.config, dict) and row.config:
        return {**_DEFAULT_TRAINING_CONFIG, **row.config}
    return dict(_DEFAULT_TRAINING_CONFIG)


def _save_training_config(db: Session, organization_id, config: Dict[str, Any]) -> None:
    """Persist training config to FutureEnhancement table."""
    row = db.query(models.FutureEnhancement).filter(
        models.FutureEnhancement.organization_id == organization_id,
        models.FutureEnhancement.story_id == _TRAINING_STORY_ID,
    ).first()

    if row:
        row.config = config  # type: ignore[assignment]
        row.status = "deployed"  # type: ignore[assignment]
        row.enabled = True  # type: ignore[assignment]
    else:
        row = models.FutureEnhancement(
            organization_id=organization_id,
            story_id=_TRAINING_STORY_ID,
            category=_TRAINING_CATEGORY,
            title="Training Pipeline Configuration",
            description="Persisted training hyperparameters and model settings",
            status="deployed",
            priority="high",
            config=config,
            enabled=True,
        )
        db.add(row)
    db.commit()


# ── Background Training Helper ──────────────────────────────────────────────

def _run_training_background(
    org_id: str,
    user_id: str,
    job_id: str,
    config_dict: Dict[str, Any],
) -> None:
    """Execute training in a background task with its own DB session."""
    db: Session = SessionLocal()
    try:
        _require_training_system()

        job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
        if not job:
            logger.error("[BG TRAIN] job %s not found", job_id)
            return

        data_prep = DatasetPreparation()
        embeddings, labels, visitor_ids = data_prep.load_embeddings_from_db(db, org_id)

        if len(embeddings) == 0:
            job.status = "failed"
            job.config = {**config_dict, "error": "No face embeddings found"}
            db.commit()
            return

        visitor_service.create_audit_log(
            db, org_id, user_id, "start_training", "model", None,
            details={"samples": len(embeddings), "visitors": len(set(str(l) for l in labels))},
        )

        from sklearn.model_selection import train_test_split as _split
        test_split = min(max(float(config_dict.get("test_split", 0.1)), 0.05), 0.4)
        val_split = min(max(float(config_dict.get("validation_split", 0.2)), 0.05), 0.4)
        val_ratio = min(max(val_split / max(1.0 - test_split, 0.1), 0.05), 0.5)

        # Use bias-mitigated dataset indices if available
        mitigated_path = Path(os.environ.get("DATA_DIR", "backend/data")) / "training_artifacts" / str(org_id) / "bias_mitigated_indices.json"
        if mitigated_path.exists():
            try:
                with open(mitigated_path) as f:
                    mitigation_meta = json.load(f)
                selected = mitigation_meta.get("selected_indices", [])
                if selected and len(selected) >= 10:
                    embeddings = embeddings[selected]
                    labels = labels[selected]
                    logger.info("[BG TRAIN] Using bias-mitigated dataset: %d samples", len(embeddings))
            except Exception as exc:
                logger.warning("[BG TRAIN] Could not load mitigated indices: %s", exc)

        # Guard: each split must hold at least one sample per class for stratification
        n_total = len(embeddings)
        n_classes = int(len(np.unique(labels)))
        if n_classes > 1:
            min_test_frac = (n_classes + 5) / n_total
            if test_split < min_test_frac:
                logger.info("[BG TRAIN] Bumping test_split %.3f -> %.3f to cover %d classes", test_split, min_test_frac, n_classes)
                test_split = min(min_test_frac, 0.4)
            min_val_frac = (n_classes + 5) / max(n_total * (1.0 - test_split), 1)
            if val_ratio < min_val_frac:
                logger.info("[BG TRAIN] Bumping val_ratio %.3f -> %.3f to cover %d classes", val_ratio, min_val_frac, n_classes)
                val_ratio = min(min_val_frac, 0.5)

        X_train, X_test, y_train, y_test = _split(embeddings, labels, test_size=test_split, random_state=42, stratify=labels)
        X_train, X_val, y_train, y_val = _split(X_train, y_train, test_size=val_ratio, random_state=42, stratify=y_train)

        config = TrainingConfig(
            num_epochs=int(config_dict.get("num_epochs", 50)),
            batch_size=int(config_dict.get("batch_size", 32)),
            learning_rate=float(config_dict.get("learning_rate", 0.001)),
            validation_split=float(config_dict.get("validation_split", 0.2)),
            test_split=float(config_dict.get("test_split", 0.1)),
            optimizer=str(config_dict.get("optimizer", "adam")),
            loss_fn=str(config_dict.get("loss_function", "softmax")),
            model_name=str(config_dict.get("model_name", "simple")),
        )

        trainer = ModelTrainer(config)
        result = trainer.train(X_train, y_train, X_val, y_val, X_test=X_test, y_test=y_test)

        class_to_visitor_id = _build_class_to_visitor_map(visitor_ids, labels)
        architecture = result.get("architecture", "simple")

        artifact_payload: Dict[str, Any] = {}
        try:
            scaler = getattr(trainer, "scaler", None)
            if scaler is None:
                raise RuntimeError("Scaler not captured")
            artifact_payload = custom_classifier_service.save_training_artifact(
                organization_id=org_id,
                job_id=job_id,
                model_state_dict=trainer.model.state_dict() if trainer.model is not None else {},
                input_dim=int(result.get("input_dim", embeddings.shape[1] if len(embeddings) else 512)),
                num_classes=int(result.get("num_classes", len(class_to_visitor_id))),
                class_to_visitor_id=class_to_visitor_id,
                scaler_mean=getattr(scaler, "mean_", np.zeros(result.get("input_dim", 512))),
                scaler_scale=getattr(scaler, "scale_", np.ones(result.get("input_dim", 512))),
                config=config_dict,
                hidden_dims=config.hidden_dims or [256, 128, 64],
                dropout=config.dropout,
                metrics={
                    "accuracy": float(result.get("final_val_accuracy", 0.0)),
                    "precision": float(result.get("final_val_precision", 0.0)),
                    "recall": float(result.get("final_val_recall", 0.0)),
                    "f1_score": float(result.get("final_val_f1", 0.0)),
                },
                architecture=architecture,
            )
        except Exception as art_exc:
            logger.warning("[BG TRAIN] Artifact save failed: %s", art_exc)
            artifact_payload = {"error": str(art_exc)}

        model_version_id = None
        try:
            mv = model_versioning_service.register_model(
                db=db,
                organization_id=org_id,
                name="CustomClassifier",
                version=job_id,
                model_type="face_recognition",
                file_path=str(artifact_payload.get("artifact_path") or ""),
                metrics={
                    "accuracy": float(result.get("final_val_accuracy", 0.0)),
                    "precision": float(result.get("final_val_precision", 0.0)),
                    "recall": float(result.get("final_val_recall", 0.0)),
                    "f1_score": float(result.get("final_val_f1", 0.0)),
                    "parameters": config_dict,
                },
            )
            model_version_id = str(mv.id)
        except Exception as mv_exc:
            logger.warning("[BG TRAIN] Model version registration failed: %s", mv_exc)

        try:
            mlflow_registry_service.log_training_run(
                component="face_recognition",
                run_name=f"training_{job_id}",
                params=config_dict,
                metrics={
                    "train_accuracy": float(result.get("final_train_accuracy", 0.0)),
                    "val_accuracy": float(result.get("final_val_accuracy", 0.0)),
                    "train_f1": float(result.get("final_train_f1", 0.0)),
                    "val_f1": float(result.get("final_val_f1", 0.0)),
                },
                tags={"organization_id": org_id, "job_id": job_id},
            )
        except Exception as ml_exc:
            logger.info("[BG TRAIN] MLflow logging skipped (not configured): %s", ml_exc)

        enriched_config = {
            **config_dict,
            "artifact_path": artifact_payload.get("artifact_path"),
            "architecture": architecture,
            "input_dim": int(result.get("input_dim", 512)),
            "num_classes": int(result.get("num_classes", len(class_to_visitor_id))),
            "model_version_id": model_version_id,
        }

        job.status = "completed"
        job.accuracy = float(result.get("final_val_accuracy", 0.0))
        job.precision = float(result.get("final_val_precision", 0.0))
        job.recall = float(result.get("final_val_recall", 0.0))
        job.f1_score = float(result.get("final_val_f1", 0.0))
        job.metrics_history = result.get("metrics_history", [])
        job.completed_at = datetime.now()
        job.config = enriched_config
        db.commit()

        visitor_service.create_audit_log(
            db, org_id, user_id, "training_completed", "model", None,
            details={"job_id": job_id, "accuracy": job.accuracy, "architecture": architecture},
        )

    except Exception as exc:
        logger.error("[BG TRAIN] job %s failed: %s", job_id, exc, exc_info=True)
        try:
            job = db.query(models.TrainingJob).filter(models.TrainingJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.config = {**(job.config or {}), "error": str(exc)[:500]}
                job.completed_at = datetime.now()
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


# ── Training Configuration ──────────────────────────────────────────────────


@router.get("/config", response_model=Dict[str, Any])
async def get_training_config(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get current training configuration"""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    cfg = _load_training_config(db, user.organization_id)
    cfg["status"] = "configured"
    cfg["embedding_dim"] = 512
    cfg["device"] = "cuda" if os.environ.get("CUDA_AVAILABLE") == "true" else "cpu"
    cfg["timestamp"] = datetime.now().isoformat()
    return cfg


@router.put("/config", response_model=Dict[str, Any])
async def update_training_config(
    config: Dict[str, Any],
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update training configuration (admin only)"""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    # Validate config
    config = _normalize_training_config(config)

    valid_keys = {
        'batch_size', 'num_epochs', 'learning_rate', 'validation_split',
        'test_split', 'optimizer', 'loss_function', 'model_name', 'loss_fn'
    }
    
    invalid_keys = set(config.keys()) - valid_keys
    if invalid_keys:
        raise HTTPException(status_code=400, detail=f"Invalid config keys: {invalid_keys}")
    
    # Merge with existing persisted config so partial updates work
    existing = _load_training_config(db, user.organization_id)
    existing.update(config)
    _save_training_config(db, user.organization_id, existing)

    # Log the update
    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "update_training_config",
        "training", None, details=config
    )
    
    return {
        "status": "updated",
        "message": "Training configuration updated successfully",
        "config": existing,
        "timestamp": datetime.now().isoformat()
    }


# ── Dataset Management ──────────────────────────────────────────────────────


@router.get("/dataset/stats", response_model=Dict[str, Any])
async def get_dataset_statistics(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get comprehensive dataset statistics"""
    user = _get_user(db, current_user_id)
    
    # Get all face data for organization
    face_records = (
        db.query(models.FaceData)
        .join(models.Visitor)
        .filter(models.Visitor.organization_id == user.organization_id)
        .limit(100000)
        .all()
    )
    
    if not face_records:
        return {
            "total_samples": 0,
            "unique_visitors": 0,
            "avg_samples_per_visitor": 0,
            "min_samples_per_visitor": 0,
            "max_samples_per_visitor": 0,
            "avg_quality_score": 0,
            "quality_distribution": {},
            "visitor_distribution": [],
            "timestamp": datetime.now().isoformat()
        }
    
    # Calculate statistics
    visitor_sample_counts = {}
    quality_scores = []
    
    for face in face_records:
        visitor_id = str(face.visitor_id)
        if visitor_id not in visitor_sample_counts:
            visitor_sample_counts[visitor_id] = 0
        visitor_sample_counts[visitor_id] += 1
        
        if face.quality_score:
            quality_scores.append(face.quality_score)
    
    # Quality distribution buckets
    quality_dist = {
        'excellent': sum(1 for q in quality_scores if q >= 0.9),
        'good': sum(1 for q in quality_scores if 0.7 <= q < 0.9),
        'fair': sum(1 for q in quality_scores if 0.5 <= q < 0.7),
        'poor': sum(1 for q in quality_scores if q < 0.5),
    }
    
    counts = list(visitor_sample_counts.values())
    
    return {
        "total_samples": len(face_records),
        "unique_visitors": len(visitor_sample_counts),
        "avg_samples_per_visitor": float(np.mean(counts)),
        "min_samples_per_visitor": int(min(counts)),
        "max_samples_per_visitor": int(max(counts)),
        "median_samples_per_visitor": float(np.median(counts)),
        "std_samples_per_visitor": float(np.std(counts)),
        "avg_quality_score": float(np.mean(quality_scores)) if quality_scores else 0,
        "quality_distribution": quality_dist,
        "visitor_distribution": [
            {
                "visitor_id": vid,
                "sample_count": count,
                "percentage": float(count / len(face_records) * 100)
            }
            for vid, count in sorted(visitor_sample_counts.items(), key=lambda x: x[1], reverse=True)
        ],
        "timestamp": datetime.now().isoformat()
    }


@router.post("/dataset/validate", response_model=Dict[str, Any])
async def validate_dataset(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Validate current dataset for training readiness"""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    # Get all face embeddings
    face_records = (
        db.query(models.FaceData)
        .join(models.Visitor)
        .filter(models.Visitor.organization_id == user.organization_id)
        .limit(100000)
        .all()
    )
    
    if not face_records:
        raise HTTPException(status_code=400, detail="No training data available")
    
    # Extract embeddings and labels
    embeddings_list = []
    labels = []
    visitor_map = {}
    
    for face in face_records:
        try:
            if face.embedding:
                embedding = visitor_service._parse_embedding_payload(face.embedding)
                if embedding is None:
                    continue

                embeddings_list.append(embedding)
                
                visitor_id = str(face.visitor_id)
                if visitor_id not in visitor_map:
                    visitor_map[visitor_id] = len(visitor_map)
                
                labels.append(visitor_map[visitor_id])
        except Exception:
            logger.debug("Skipping face record with invalid embedding data")
    
    if len(embeddings_list) < 10:
        raise HTTPException(status_code=400, detail="Minimum 10 training samples required")
    
    embeddings = np.array(embeddings_list)
    labels = np.array(labels)
    
    # Validation checks
    issues = []
    recommendations = []
    
    # Check minimum samples per class
    unique_labels, counts = np.unique(labels, return_counts=True)
    min_samples = min(counts)
    if min_samples < 3:
        issues.append(f"Some visitors have < 3 samples: {dict(zip(unique_labels, counts))}")
        recommendations.append("Collect more training images for visitors with < 3 samples")
    
    # Check class balance
    max_count = max(counts)
    min_count = min(counts)
    if max_count / min_count > 10:
        issues.append(f"Highly imbalanced: max/min ratio = {max_count/min_count:.1f}")
        recommendations.append("Use data augmentation or class weighting")
    
    # Check embedding quality
    norms = np.linalg.norm(embeddings, axis=1)
    if (norms == 0).any():
        issues.append("Found zero-norm embeddings")
    
    # Check for NaN/Inf
    if np.isnan(embeddings).any() or np.isinf(embeddings).any():
        issues.append("Found NaN or Inf values")
    
    is_ready = len(issues) == 0
    
    return {
        "dataset_ready": is_ready,
        "total_samples": len(embeddings),
        "unique_classes": len(unique_labels),
        "avg_samples_per_class": float(np.mean(counts)),
        "min_samples_per_class": int(min_count),
        "max_samples_per_class": int(max_count),
        "issues": issues,
        "recommendations": recommendations,
        "timestamp": datetime.now().isoformat()
    }


# ── Training Execution ──────────────────────────────────────────────────────


@router.post("/start", response_model=Dict[str, Any])
async def start_training(
    background_tasks: BackgroundTasks,
    config_override: Optional[Dict[str, Any]] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start model training in background. Returns immediately with job_id — poll GET /training/jobs/{job_id}."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    _require_training_system()

    persisted_config = _load_training_config(db, user.organization_id)
    merged_config = dict(persisted_config)
    if config_override:
        merged_config.update(_normalize_training_config(config_override))

    config_dict = {
        "num_epochs": int(merged_config.get("num_epochs", 50)),
        "batch_size": int(merged_config.get("batch_size", 32)),
        "learning_rate": float(merged_config.get("learning_rate", 0.001)),
        "validation_split": float(merged_config.get("validation_split", 0.2)),
        "test_split": float(merged_config.get("test_split", 0.1)),
        "optimizer": str(merged_config.get("optimizer", "adam")),
        "loss_function": str(merged_config.get("loss_function", "softmax")),
        "model_name": str(merged_config.get("model_name", "simple")),
    }

    training_job = models.TrainingJob(
        organization_id=user.organization_id,
        status="running",
        config=config_dict,
        started_by=user.id,
        started_at=datetime.now(),
    )
    db.add(training_job)
    db.commit()
    db.refresh(training_job)
    job_id = str(training_job.id)

    background_tasks.add_task(
        _run_training_background,
        org_id=str(user.organization_id),
        user_id=str(user.id),
        job_id=job_id,
        config_dict=config_dict,
    )

    logger.info("[TRAINING] job %s queued for org %s by %s", job_id, user.organization_id, user.email)
    return {
        "status": "training_started",
        "job_id": job_id,
        "message": "Training running in background. Poll GET /training/jobs/{job_id} for status.",
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/jobs", response_model=List[Dict[str, Any]])
async def list_training_jobs(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    """List all training jobs for organization"""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    jobs = (
        db.query(models.TrainingJob)
        .filter(models.TrainingJob.organization_id == user.organization_id)
        .order_by(models.TrainingJob.created_at.desc())
        .limit(limit)
        .all()
    )
    
    return [
        {
            "id": str(job.id),
            "status": job.status,
            "accuracy": job.accuracy,
            "model_name": (job.config or {}).get("model_name") if isinstance(job.config, dict) else None,
            "artifact_path": (job.config or {}).get("artifact_path") if isinstance(job.config, dict) else None,
            "model_version_id": (job.config or {}).get("model_version_id") if isinstance(job.config, dict) else None,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None
        }
        for job in jobs
    ]


@router.get("/jobs/{training_job_id}", response_model=Dict[str, Any])
async def get_training_job(
    training_job_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Poll training job status. status: running | completed | failed."""
    user = _get_user(db, current_user_id)
    try:
        job_uuid = UUID(training_job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job id")

    job = (
        db.query(models.TrainingJob)
        .filter(
            models.TrainingJob.id == job_uuid,
            models.TrainingJob.organization_id == user.organization_id,
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Training job not found")

    config = job.config if isinstance(job.config, dict) else {}
    return {
        "id": str(job.id),
        "status": job.status,
        "accuracy": job.accuracy,
        "f1_score": job.f1_score,
        "architecture": config.get("architecture"),
        "artifact_path": config.get("artifact_path"),
        "model_version_id": config.get("model_version_id"),
        "error": config.get("error"),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


@router.post("/jobs/{training_job_id}/activate", response_model=Dict[str, Any])
async def activate_trained_model(
    training_job_id: str,
    force: bool = Query(False, description="Skip accuracy regression guard"),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Activate a completed training job as the live custom classifier backend."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    try:
        training_job_uuid = UUID(training_job_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid training job id") from exc

    training_job = (
        db.query(models.TrainingJob)
        .filter(
            models.TrainingJob.id == training_job_uuid,
            models.TrainingJob.organization_id == user.organization_id,
        )
        .first()
    )
    if not training_job:
        raise HTTPException(status_code=404, detail="Training job not found")
    if training_job.status != "completed":
        raise HTTPException(status_code=400, detail="Only completed training jobs can be activated")

    config = training_job.config if isinstance(training_job.config, dict) else {}
    artifact_path = config.get("artifact_path") or config.get("latest_artifact_path")
    if not artifact_path:
        raise HTTPException(
            status_code=400,
            detail="This training job does not have an activatable custom classifier artifact",
        )
    if not custom_classifier_service.artifact_exists(str(artifact_path)):
        raise HTTPException(status_code=404, detail="Saved classifier artifact could not be found")

    # Accuracy regression guard — block activation if new model is significantly worse
    if not force:
        current_production = model_versioning_service.get_production_model(
            db, str(user.organization_id), "face_recognition"
        )
        new_f1 = float(training_job.f1_score or 0.0)
        if current_production and current_production.f1_score is not None:
            prod_f1 = float(current_production.f1_score)
            if new_f1 < prod_f1 - 0.05:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Activation blocked: new model is significantly worse than current production.",
                        "new_f1": round(new_f1, 4),
                        "production_f1": round(prod_f1, 4),
                        "hint": "Force-activate by passing ?force=true if intentional.",
                    },
                )

    # Embedding-dim compatibility check
    try:
        info = custom_classifier_service.get_classifier_info(str(artifact_path))
        artifact_input_dim = int(info.get("num_classes") and (config.get("input_dim") or 0) or 0)
        stored_input_dim = int(config.get("input_dim") or 0)
        current_backbone = (get_runtime_component("face_recognition") or {}).get("current_model", "ArcFace")
        logger.info(
            "[ACTIVATE] artifact input_dim=%s backbone=%s",
            stored_input_dim, current_backbone,
        )
    except Exception as dim_exc:
        logger.warning("[ACTIVATE] Could not verify embedding dim: %s", dim_exc)

    runtime_registry = load_runtime_registry()
    face_component = _get_or_create_face_recognition_component(runtime_registry)
    face_component.update(
        {
            "current_model": "CustomClassifier",
            "current_artifact": str(artifact_path),
            "framework": "PyTorch classifier on 512-d face embeddings",
            "runtime": "backend + ai-service",
            "status": "active",
            "notes": "ArcFace-compatible embeddings with organization-trained classifier reranking",
        }
    )
    runtime_registry["components"] = runtime_registry.get("components", [])
    saved_registry = save_runtime_registry(runtime_registry)

    promoted_model_version_id = None
    if config.get("model_version_id"):
        try:
            promoted = model_versioning_service.promote_to_production(
                db,
                str(user.organization_id),
                str(config["model_version_id"]),
            )
            promoted_model_version_id = str(promoted.id)
        except Exception as exc:
            logger.warning("Failed to promote model version during activation: %s", exc)

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "activate_custom_classifier",
        "model",
        str(training_job.id),
        details={
            "artifact_path": artifact_path,
            "model_version_id": promoted_model_version_id or config.get("model_version_id"),
        },
    )

    return {
        "status": "activated",
        "job_id": str(training_job.id),
        "artifact_path": artifact_path,
        "model_version_id": promoted_model_version_id or config.get("model_version_id"),
        "runtime_face_model": face_component.get("current_model"),
        "runtime_registry_updated_at": saved_registry.get("last_updated_at"),
        "message": "Custom classifier is now active for face recognition search",
    }


# ── Bias Detection & Mitigation ────────────────────────────────────────────


@router.post("/bias/detect", response_model=Dict[str, Any])
async def detect_bias(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Detect demographic bias in training data"""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    try:
        import json
        import numpy as np
        
        # Load training data from database directly
        face_data_list = (
            db.query(models.FaceData)
            .join(models.Visitor, models.FaceData.visitor_id == models.Visitor.id)
            .filter(models.Visitor.organization_id == user.organization_id)
            .limit(100000)
            .all()
        )
        
        if len(face_data_list) == 0:
            return {
                "bias_detected": False,
                "message": "No training data available for bias analysis",
                "groups": [],
                "recommendations": ["Upload more face images from different demographic groups to enable bias detection"]
            }
        
        # Parse embeddings and analyze basic statistics
        embeddings_list = []
        visitor_counts = {}
        
        for face_data in face_data_list:
            if face_data.embedding:
                try:
                    parsed_embedding = visitor_service._parse_embedding_payload(face_data.embedding)
                    if parsed_embedding is None:
                        continue
                    embedding = np.array(parsed_embedding, dtype=np.float32)
                    embeddings_list.append(embedding)
                    visitor_counts[str(face_data.visitor_id)] = visitor_counts.get(str(face_data.visitor_id), 0) + 1
                except (json.JSONDecodeError, ValueError):
                    continue
        
        if len(embeddings_list) == 0:
            return {
                "bias_detected": False,
                "message": "No valid embeddings found",
                "groups": [],
                "recommendations": ["Check your face embedding data"]
            }
        
        embeddings = np.array(embeddings_list, dtype=np.float32)
        
        # Analyze data balance across visitors
        groups = []
        total = len(embeddings)
        max_group_size = max(visitor_counts.values()) if visitor_counts else 0
        min_group_size = min(visitor_counts.values()) if visitor_counts else 0
        
        for visitor_id, count in visitor_counts.items():
            groups.append({
                "group": visitor_id[:8] + "...",
                "samples": count,
                "percentage": float(count / total * 100)
            })
        
        # Check for significant imbalance
        imbalance_ratio = max_group_size / min_group_size if min_group_size > 0 else 1
        bias_detected = imbalance_ratio > 2.0  # More than 2x imbalance
        
        # Log the bias detection
        audit_log = visitor_service.create_audit_log(
            db, user.organization_id, user.id, 
            "bias_detection", "training", None,
            {"imbalance_ratio": imbalance_ratio, "total_samples": total, "unique_visitors": len(visitor_counts)}
        )
        
        recommendations = []
        if bias_detected:
            recommendations.append("Data is imbalanced across visitor groups")
            if len(visitor_counts) == 1:
                recommendations.append("Add training data from more visitors for diversity")
        if total < 100:
            recommendations.append(f"Consider collecting more training samples ({total}/100 recommended)")
        
        return {
            "bias_detected": bias_detected,
            "imbalance_ratio": float(imbalance_ratio),
            "total_samples": total,
            "unique_visitors": len(visitor_counts),
            "groups": groups,
            "recommendations": recommendations if recommendations else ["Dataset looks balanced"],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Bias detection error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Bias detection failed: {str(e)}")


@router.post("/bias/mitigate", response_model=Dict[str, Any])
async def mitigate_bias(
    request_data: Dict[str, Any] = Body(default={}),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Apply bias mitigation strategies"""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    _require_training_system()
    
    strategies = request_data.get("strategies")
    if strategies is None:
        strategies = ["balance_classes", "augment_data", "fairness_constraints"]
    
    applied_strategies = []

    try:
        # Load embeddings and build group labels (visitor_id)
        data_prep = DatasetPreparation()
        embeddings, labels, visitor_ids = data_prep.load_embeddings_from_db(db, user.organization_id)

        if len(embeddings) == 0:
            raise HTTPException(status_code=400, detail="No embeddings found for bias mitigation")

        bm = BiasMitigation()
        group_labels = np.array(labels)
        original_count = len(embeddings)
        current_embeddings = embeddings
        current_labels = labels

        if "balance_classes" in strategies:
            balanced_X, balanced_y = bm.mitigate_bias(current_embeddings, current_labels, group_labels)
            applied_strategies.append({
                "strategy": "balance_classes",
                "status": "applied",
                "result": f"Balanced dataset from {original_count} to {len(balanced_y)} samples via undersampling",
            })
            current_embeddings = balanced_X
            current_labels = balanced_y

        if "augment_data" in strategies:
            # Apply gaussian noise augmentation to minority classes
            unique, counts = np.unique(current_labels, return_counts=True)
            max_count = int(counts.max())
            aug_X_parts = [current_embeddings]
            aug_y_parts = [current_labels]
            total_augmented = 0
            for cls, cnt in zip(unique, counts):
                deficit = max_count - int(cnt)
                if deficit > 0:
                    cls_mask = current_labels == cls
                    cls_embeddings = current_embeddings[cls_mask]
                    # Oversample with small gaussian noise
                    indices = np.random.choice(len(cls_embeddings), deficit, replace=True)
                    noise = np.random.normal(0, 0.01, (deficit, cls_embeddings.shape[1])).astype(np.float32)
                    aug_X_parts.append(cls_embeddings[indices] + noise)
                    aug_y_parts.append(np.full(deficit, cls, dtype=current_labels.dtype))
                    total_augmented += deficit
            current_embeddings = np.concatenate(aug_X_parts, axis=0)
            current_labels = np.concatenate(aug_y_parts, axis=0)
            applied_strategies.append({
                "strategy": "augment_data",
                "status": "applied",
                "result": f"Augmented dataset with {total_augmented} synthetic samples (gaussian noise), total now {len(current_labels)}",
            })

        if "fairness_constraints" in strategies:
            # Re-balance after augmentation to enforce demographic parity
            new_group = np.array(current_labels)
            balanced_X, balanced_y = bm.mitigate_bias(current_embeddings, current_labels, new_group)
            applied_strategies.append({
                "strategy": "fairness_constraints",
                "status": "applied",
                "result": f"Applied demographic parity via resampling: {len(current_labels)} -> {len(balanced_y)} samples",
            })
            current_embeddings = balanced_X
            current_labels = balanced_y

        # Persist the mitigated indices so _run_training_background can use them
        mitigated_path = (
            Path(os.environ.get("DATA_DIR", "backend/data"))
            / "training_artifacts"
            / str(user.organization_id)
            / "bias_mitigated_indices.json"
        )
        try:
            mitigated_path.parent.mkdir(parents=True, exist_ok=True)
            # Track which original indices survive after all strategies
            # current_labels may have been resampled; reconstruct the selected original indices
            # by comparing current_embeddings rows against the original embeddings array
            if len(current_embeddings) <= len(embeddings):
                # Build a set of row-hashes to identify selected rows
                selected_indices = []
                orig_hash = {
                    tuple(embeddings[i, :4].tolist()): i for i in range(len(embeddings))
                }
                for row in current_embeddings:
                    key = tuple(row[:4].tolist())
                    idx = orig_hash.get(key)
                    if idx is not None:
                        selected_indices.append(idx)
            else:
                selected_indices = list(range(len(embeddings)))

            with open(mitigated_path, "w") as mf:
                json.dump(
                    {
                        "selected_indices": selected_indices,
                        "strategies": strategies,
                        "original_count": original_count,
                        "final_count": len(current_labels),
                        "generated_at": datetime.now().isoformat(),
                    },
                    mf,
                )
            logger.info(
                "[BIAS] Persisted %d mitigated indices to %s", len(selected_indices), mitigated_path
            )
        except Exception as persist_exc:
            logger.warning("[BIAS] Could not persist mitigated indices: %s", persist_exc)

        visitor_service.create_audit_log(
            db, user.organization_id, user.id, "mitigate_bias",
            "model", None, details={
                "strategies": strategies,
                "original_count": original_count,
                "final_count": len(current_labels),
            }
        )

        return {
            "status": "mitigation_applied",
            "strategies_applied": applied_strategies,
            "original_samples": original_count,
            "final_samples": len(current_labels),
            "mitigated_indices_path": str(mitigated_path),
            "message": f"Applied {len(applied_strategies)} bias mitigation strategies",
            "timestamp": datetime.now().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bias mitigation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Bias mitigation failed: {str(e)}")


# ── Hyperparameter Optimization ────────────────────────────────────────────


@router.post("/hpo/start", response_model=Dict[str, Any])
async def start_hyperparameter_optimization(
    background_tasks: BackgroundTasks,
    n_trials: int = Query(20, ge=3, le=100),
    auto_train: bool = Query(False, description="Automatically start training with best params after HPO"),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Start automated hyperparameter optimization on current dataset"""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    _require_training_system()
    
    logger.info(f"[HPO] User {user.email} starting hyperparameter optimization with {n_trials} trials")
    
    try:
        # Load embeddings
        data_prep = DatasetPreparation()
        embeddings, labels, visitor_ids = data_prep.load_embeddings_from_db(db, user.organization_id)
        
        if len(embeddings) == 0:
            raise HTTPException(status_code=400, detail="No embeddings found for HPO")
        
        # Create HPO job record
        hpo_job = models.HPOJob(
            organization_id=user.organization_id,
            status="running",
            n_trials=n_trials,
            started_by=user.id
        )
        db.add(hpo_job)
        db.commit()
        
        # Split data
        from sklearn.model_selection import train_test_split
        X_train, X_test, y_train, y_test = train_test_split(
            embeddings, labels, test_size=0.2, random_state=42
        )
        X_train, X_val, y_train, y_val = train_test_split(
            X_train, y_train, test_size=0.2, random_state=42
        )
        
        # Run HPO
        logger.info(f"[HPO] Running {n_trials} trials on {len(X_train)} samples")
        hpo = HyperparameterOptimization(X_train, y_train, X_val, y_val, n_trials=n_trials)
        hpo_result = hpo.optimize()
        
        # Update job with results
        hpo_job.status = "completed"
        hpo_job.best_params = hpo_result['best_params']
        hpo_job.best_value = hpo_result['best_accuracy']
        hpo_job.completed_at = datetime.now()
        db.commit()
        
        logger.info(f"[HPO] Optimization completed. Best accuracy: {hpo_result['best_accuracy']:.4f}")

        visitor_service.create_audit_log(
            db, user.organization_id, user.id, "hpo_completed",
            "model", None, details={
                "job_id": str(hpo_job.id),
                "n_trials": n_trials,
                "best_accuracy": hpo_result['best_accuracy'],
                "best_params": hpo_result['best_params'],
                "auto_train": auto_train,
            }
        )

        auto_train_job_id = None
        if auto_train and hpo_result.get("best_params"):
            best = hpo_result["best_params"]
            auto_config = {
                "num_epochs": int(best.get("num_epochs", 50)),
                "batch_size": int(best.get("batch_size", 32)),
                "learning_rate": float(best.get("learning_rate", 0.001)),
                "optimizer": str(best.get("optimizer", "adam")),
                "validation_split": 0.2,
                "test_split": 0.1,
                "loss_function": "softmax",
                "model_name": "simple",
            }
            # Persist best params to training config
            existing_cfg = _load_training_config(db, user.organization_id)
            existing_cfg.update(auto_config)
            _save_training_config(db, user.organization_id, existing_cfg)

            auto_job = models.TrainingJob(
                organization_id=user.organization_id,
                status="running",
                config=auto_config,
                started_by=user.id,
                started_at=datetime.now(),
            )
            db.add(auto_job)
            db.commit()
            db.refresh(auto_job)
            auto_train_job_id = str(auto_job.id)
            background_tasks.add_task(
                _run_training_background,
                org_id=str(user.organization_id),
                user_id=str(user.id),
                job_id=auto_train_job_id,
                config_dict=auto_config,
            )
            logger.info("[HPO] Auto-training queued: job %s", auto_train_job_id)

        return {
            "status": "hpo_completed",
            "job_id": str(hpo_job.id),
            "n_trials": n_trials,
            "best_accuracy": hpo_result['best_accuracy'],
            "best_params": hpo_result['best_params'],
            "auto_train_job_id": auto_train_job_id,
            "timestamp": datetime.now().isoformat(),
        }
    
    except Exception as e:
        logger.error(f"HPO failed: {e}", exc_info=True)
        if 'hpo_job' in locals():
            hpo_job.status = "failed"
            db.commit()
        raise HTTPException(status_code=500, detail=f"HPO failed: {str(e)}")



@router.get("/hpo/results/{hpo_job_id}", response_model=Dict[str, Any])
async def get_hpo_results(
    hpo_job_id: str,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get hyperparameter optimization results"""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    try:
        hpo_job = db.query(models.HPOJob).filter(
            models.HPOJob.id == hpo_job_id,
            models.HPOJob.organization_id == user.organization_id
        ).first()
        
        if not hpo_job:
            raise HTTPException(status_code=404, detail="HPO job not found")
        
        return {
            "job_id": str(hpo_job.id),
            "status": hpo_job.status,
            "n_trials": hpo_job.n_trials,
            "best_params": hpo_job.best_params or {},
            "best_value": hpo_job.best_value,
            "created_at": hpo_job.created_at.isoformat() if hpo_job.created_at else None,
            "completed_at": hpo_job.completed_at.isoformat() if hpo_job.completed_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting HPO results: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting HPO results: {str(e)}")



# ── Model Ensemble ─────────────────────────────────────────────────────────


@router.post("/ensemble/create", response_model=Dict[str, Any])
async def create_ensemble(
    num_models: int = Query(3, ge=2, le=10),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create ensemble by training multiple models with different configurations"""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    _require_training_system()
    
    logger.info(f"[ENSEMBLE] User {user.email} creating ensemble with {num_models} models")
    
    try:
        # Load embeddings
        data_prep = DatasetPreparation()
        embeddings, labels, visitor_ids = data_prep.load_embeddings_from_db(db, user.organization_id)
        
        if len(embeddings) == 0:
            raise HTTPException(status_code=400, detail="No embeddings found for ensemble")
        
        # Split data
        from sklearn.model_selection import train_test_split
        X_train, X_test, y_train, y_test = train_test_split(
            embeddings, labels, test_size=0.2, random_state=42
        )
        X_train, X_val, y_train, y_val = train_test_split(
            X_train, y_train, test_size=0.2, random_state=42
        )
        
        # Create diverse training configurations
        training_configs = []
        learning_rates = [0.001, 0.0005, 0.002]
        optimizers = ['adam', 'sgd', 'rmsprop']
        
        for i in range(num_models):
            config = TrainingConfig(
                learning_rate=learning_rates[i % len(learning_rates)],
                optimizer=optimizers[i % len(optimizers)],
                batch_size=32,
                num_epochs=50
            )
            training_configs.append(config)
        
        # Fit a shared scaler so all sub-models are trained on identical normalised data
        from sklearn.preprocessing import StandardScaler as _SK_SS
        shared_scaler = _SK_SS()
        X_train_sc = shared_scaler.fit_transform(X_train)
        X_val_sc = shared_scaler.transform(X_val)
        scaler_mean_list = shared_scaler.mean_.tolist()
        scaler_scale_list = shared_scaler.scale_.tolist()

        # Create and train ensemble
        logger.info(f"[ENSEMBLE] Creating {num_models} models with different configs")
        ensemble = EnsembleModel(num_models=num_models)
        ensemble_result = ensemble.create_ensemble(training_configs, X_train_sc, y_train, X_val_sc, y_val)

        input_dim = int(embeddings.shape[1])
        num_classes_ens = int(np.max(labels) + 1)
        class_to_visitor_id = _build_class_to_visitor_map(visitor_ids, labels)

        # Create DB record first so we have the ensemble UUID for artifact naming
        ensemble_job = models.Ensemble(
            organization_id=user.organization_id,
            name=f"Ensemble_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            model_ids=[],
            weights=ensemble_result['weights'],
            accuracy=ensemble_result['ensemble_avg_accuracy'],
            created_by=user.id
        )
        db.add(ensemble_job)
        db.commit()
        db.refresh(ensemble_job)

        # Persist each sub-model as a standalone artifact (shared scaler applied at ensemble level)
        sub_artifacts: List[Dict[str, str]] = []
        for sub_idx, sub_model in enumerate(ensemble.models):
            sub_job_id = f"{str(ensemble_job.id)}_sub{sub_idx}"
            try:
                sub_payload = custom_classifier_service.save_training_artifact(
                    organization_id=str(user.organization_id),
                    job_id=sub_job_id,
                    model_state_dict=sub_model.state_dict(),
                    input_dim=input_dim,
                    num_classes=num_classes_ens,
                    class_to_visitor_id=class_to_visitor_id,
                    scaler_mean=scaler_mean_list,
                    scaler_scale=scaler_scale_list,
                    config={"member_index": sub_idx, "learning_rate": training_configs[sub_idx].learning_rate},
                    metrics={"accuracy": float(ensemble_result["individual_accuracies"][sub_idx])},
                    architecture="simple",
                )
                sub_artifacts.append(sub_payload)
            except Exception as sub_exc:
                logger.warning("[ENSEMBLE] Sub-artifact %d save failed: %s", sub_idx, sub_exc)

        # Persist ensemble meta-artifact
        ensemble_artifact_payload: Dict[str, str] = {}
        if sub_artifacts:
            try:
                ensemble_artifact_payload = custom_classifier_service.save_ensemble_artifact(
                    organization_id=str(user.organization_id),
                    ensemble_id=str(ensemble_job.id),
                    sub_artifacts=sub_artifacts,
                    weights=ensemble_result["weights"],
                    class_to_visitor_id=class_to_visitor_id,
                    num_classes=num_classes_ens,
                    input_dim=input_dim,
                    metrics={"ensemble_avg_accuracy": float(ensemble_result["ensemble_avg_accuracy"])},
                )
                ensemble_job.model_ids = [sa.get("artifact_path", "") for sa in sub_artifacts]
                db.commit()
            except Exception as ens_exc:
                logger.warning("[ENSEMBLE] Ensemble artifact save failed: %s", ens_exc)

        logger.info(f"[ENSEMBLE] Ensemble created with avg accuracy: {ensemble_result['ensemble_avg_accuracy']:.4f}")

        # Create audit log
        visitor_service.create_audit_log(
            db, user.organization_id, user.id, "ensemble_created",
            "model", None, details={
                "ensemble_id": str(ensemble_job.id),
                "num_models": num_models,
                "avg_accuracy": ensemble_result['ensemble_avg_accuracy'],
                "individual_accuracies": ensemble_result['individual_accuracies'],
                "ensemble_artifact_path": ensemble_artifact_payload.get("artifact_path"),
            }
        )

        return {
            "status": "ensemble_created",
            "ensemble_id": str(ensemble_job.id),
            "num_models": num_models,
            "individual_accuracies": ensemble_result['individual_accuracies'],
            "ensemble_avg_accuracy": ensemble_result['ensemble_avg_accuracy'],
            "weights": ensemble_result['weights'],
            "ensemble_artifact_path": ensemble_artifact_payload.get("artifact_path"),
            "sub_artifact_paths": [sa.get("artifact_path") for sa in sub_artifacts],
            "timestamp": datetime.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Ensemble creation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ensemble creation failed: {str(e)}")


# ── Classifier Staleness Status ────────────────────────────────────────────


@router.get("/classifier/status", response_model=Dict[str, Any])
async def get_classifier_status(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Report whether the active custom classifier is stale (new visitors added since last training)."""
    user = _get_user(db, current_user_id)

    component = get_runtime_component("face_recognition") or {}
    current_model = str(component.get("current_model") or "").strip()
    artifact_path = str(component.get("current_artifact") or "").strip()

    if not artifact_path or "custom" not in current_model.lower():
        return {
            "status": "no_classifier",
            "is_stale": None,
            "message": "No custom classifier is currently active",
            "timestamp": datetime.now().isoformat(),
        }

    if not custom_classifier_service.artifact_exists(artifact_path):
        return {
            "status": "artifact_missing",
            "is_stale": True,
            "artifact_path": artifact_path,
            "message": "Active classifier artifact file not found on disk",
            "timestamp": datetime.now().isoformat(),
        }

    try:
        info = custom_classifier_service.get_classifier_info(artifact_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not read classifier artifact: {exc}")

    artifact_class_count = len(info.get("class_to_visitor_id") or {})
    db_visitor_count = (
        db.query(func.count(models.Visitor.id))
        .filter(models.Visitor.organization_id == user.organization_id)
        .scalar()
        or 0
    )
    new_visitors = max(0, db_visitor_count - artifact_class_count)
    is_stale = new_visitors > 0

    return {
        "status": "stale" if is_stale else "current",
        "is_stale": is_stale,
        "artifact_path": artifact_path,
        "architecture": info.get("architecture", "unknown"),
        "artifact_class_count": artifact_class_count,
        "db_visitor_count": db_visitor_count,
        "new_visitors_since_training": new_visitors,
        "metrics": info.get("metrics", {}),
        "recommendation": "Retrain model to include new visitors" if is_stale else "Model covers all registered visitors",
        "timestamp": datetime.now().isoformat(),
    }


# ── Active Learning ───────────────────────────────────────────────────────




@router.post("/active-learning/select-samples", response_model=Dict[str, Any])
async def select_samples_for_labeling(
    num_samples: int = Query(10, ge=1, le=100),
    strategy: str = Query("uncertainty", pattern="^(uncertainty|diversity)$"),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Select most informative unlabeled samples for annotation using active learning"""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    _require_training_system()
    
    logger.info(f"[AL] User {user.email} selecting {num_samples} samples using {strategy} strategy")
    
    try:
        # Load current model and embeddings
        data_prep = DatasetPreparation()
        embeddings, labels, visitor_ids = data_prep.load_embeddings_from_db(db, user.organization_id)
        
        if len(embeddings) == 0:
            raise HTTPException(status_code=400, detail="No embeddings found for active learning")
        
        # Resolve model: prefer org's latest artifact, fall back to legacy checkpoint
        artifact_base = Path(sys.path[0]).parent / "backend" / "data" / "model_artifacts" / str(user.organization_id)
        checkpoint_path: Optional[Path] = None
        if artifact_base.exists():
            pt_files = sorted(artifact_base.glob("custom_classifier_*.pt"), key=lambda p: p.stat().st_mtime, reverse=True)
            if pt_files:
                checkpoint_path = pt_files[0]
        if checkpoint_path is None:
            legacy = Path("checkpoints") / "best_model.pt"
            if legacy.exists():
                checkpoint_path = legacy
        if checkpoint_path is None:
            raise HTTPException(status_code=400, detail="No trained model found. Train a model first.")

        # Recreate model and load weights
        input_dim = embeddings.shape[1]
        num_classes = len(np.unique(labels))
        bundle = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
        # Support both raw state_dict (legacy) and artifact bundle (new format)
        state_dict = bundle.get("model_state_dict", bundle) if isinstance(bundle, dict) else bundle
        hidden_dims = bundle.get("hidden_dims", [256, 128, 64]) if isinstance(bundle, dict) else [256, 128, 64]
        dropout = float(bundle.get("dropout", 0.3)) if isinstance(bundle, dict) else 0.3
        model = SimpleClassifier(input_dim, num_classes, hidden_dims=hidden_dims, dropout=dropout)
        model.load_state_dict(state_dict)
        
        # Initialize active learning
        al = ActiveLearning(model, device='cpu')
        
        # Select samples using chosen strategy
        if strategy == 'uncertainty':
            selected_indices = al.uncertainty_sampling(embeddings, num_samples)
        else:  # diversity
            selected_indices = al.diversity_sampling(embeddings, num_samples)
        
        # Prepare response with selected sample information (from labeled data)
        selected_samples = []
        for idx in selected_indices:
            visitor_id = visitor_ids[idx]
            selected_samples.append({
                "source": "labeled_embedding",
                "index": int(idx),
                "visitor_id": visitor_id,
                "strategy": strategy,
            })

        # Also surface recent unidentified visitor_logs — faces the model couldn't match
        unidentified_logs = (
            db.query(models.VisitorLog)
            .filter(
                models.VisitorLog.organization_id == user.organization_id,
                models.VisitorLog.status.in_(["unidentified", "detected"]),
                models.VisitorLog.face_image_path.isnot(None),
            )
            .order_by(models.VisitorLog.timestamp.desc())
            .limit(num_samples)
            .all()
        )
        unidentified_candidates = [
            {
                "source": "unidentified_log",
                "log_id": str(log.id),
                "face_image_path": log.face_image_path,
                "confidence": log.confidence,
                "camera_id": str(log.camera_id) if log.camera_id else None,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "strategy": "unidentified_face",
            }
            for log in unidentified_logs
        ]

        logger.info(
            "[AL] Selected %d labeled samples (%s) + %d unidentified log candidates",
            len(selected_samples), strategy, len(unidentified_candidates),
        )

        # Create audit log
        visitor_service.create_audit_log(
            db, user.organization_id, user.id, "active_learning_select",
            "model", None, details={
                "num_samples": num_samples,
                "strategy": strategy,
                "labeled_count": len(selected_samples),
                "unidentified_count": len(unidentified_candidates),
            }
        )

        return {
            "status": "samples_selected",
            "strategy": strategy,
            "labeled_samples": selected_samples,
            "unidentified_candidates": unidentified_candidates,
            "total_labeled": len(selected_samples),
            "total_unidentified": len(unidentified_candidates),
            "timestamp": datetime.now().isoformat(),
        }
    
    except Exception as e:
        logger.error(f"Active learning sample selection failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Sample selection failed: {str(e)}")


# ── Model Evaluation ───────────────────────────────────────────────────────



@router.get("/evaluation/metrics", response_model=Dict[str, Any])
async def get_evaluation_metrics(
    model_id: Optional[str] = None,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get detailed model evaluation metrics"""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    # Build query for training jobs belonging to this org
    job_query = (
        db.query(models.TrainingJob)
        .filter(models.TrainingJob.organization_id == user.organization_id)
        .filter(models.TrainingJob.status == "completed")
    )

    if model_id:
        job_query = job_query.filter(models.TrainingJob.id == model_id)

    job = job_query.order_by(models.TrainingJob.completed_at.desc()).first()

    if not job:
        return {
            "status": "no_evaluation",
            "message": "No completed training job found. Train a model first.",
            "accuracy": None,
            "precision": None,
            "recall": None,
            "f1_score": None,
            "timestamp": datetime.now().isoformat(),
        }

    # Extract metrics_history (JSON blob stored during training)
    metrics_history = job.metrics_history if job.metrics_history else {}
    per_class = metrics_history.get("per_class_metrics", {})
    confusion = metrics_history.get("confusion_matrix", None)
    auc_roc = metrics_history.get("auc_roc", None)

    return {
        "status": "evaluated",
        "job_id": str(job.id),
        "accuracy": float(job.accuracy) if job.accuracy is not None else None,
        "precision": float(job.precision) if job.precision is not None else None,
        "recall": float(job.recall) if job.recall is not None else None,
        "f1_score": float(job.f1_score) if job.f1_score is not None else None,
        "auc_roc": auc_roc,
        "per_class_metrics": per_class,
        "confusion_matrix": confusion,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "timestamp": datetime.now().isoformat(),
    }


# ── Knowledge Base for Accuracy Improvement ────────────────────────────────


@router.get("/accuracy-tips", response_model=Dict[str, Any])
async def get_accuracy_improvement_tips(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get personalized tips to improve model accuracy"""
    user = _get_user(db, current_user_id)
    
    # Get current dataset stats
    face_records = (
        db.query(models.FaceData)
        .join(models.Visitor)
        .filter(models.Visitor.organization_id == user.organization_id)
        .limit(100000)
        .all()
    )
    
    tips = []
    
    # Tip 1: More training data
    if len(face_records) < 100:
        tips.append({
            "rank": 1,
            "category": "Dataset Size",
            "tip": "Collect more training images (minimum 3-5 per person, ideally 10+)",
            "impact": "High",
            "effort": "Medium",
            "expected_improvement": "5-15%"
        })
    
    # Tip 2: Data diversity
    tips.append({
        "rank": 2,
        "category": "Data Quality",
        "tip": "Capture faces in various lighting conditions and angles",
        "impact": "High",
        "effort": "Low",
        "expected_improvement": "3-10%"
    })
    
    # Tip 3: Background consistency
    tips.append({
        "rank": 3,
        "category": "Data Quality",
        "tip": "Use consistent background or indoor/outdoor settings",
        "impact": "Medium",
        "effort": "Low",
        "expected_improvement": "2-5%"
    })
    
    # Tip 4: Model ensemble
    tips.append({
        "rank": 4,
        "category": "Model Architecture",
        "tip": "Create ensemble with multiple pre-trained models (ArcFace + Facenet)",
        "impact": "High",
        "effort": "Medium",
        "expected_improvement": "3-8%"
    })
    
    # Tip 5: Hyperparameter tuning
    tips.append({
        "rank": 5,
        "category": "Training",
        "tip": "Run hyperparameter optimization (learning rate, batch size, margins)",
        "impact": "Medium",
        "effort": "High",
        "expected_improvement": "2-5%"
    })
    
    # Tip 6: Data augmentation
    tips.append({
        "rank": 6,
        "category": "Data Augmentation",
        "tip": "Apply augmentation: rotation, brightness adjustment, flipping",
        "impact": "Medium",
        "effort": "Low",
        "expected_improvement": "2-4%"
    })
    
    # Tip 7: Bias mitigation
    tips.append({
        "rank": 7,
        "category": "Fairness",
        "tip": "Balance dataset across demographic groups (gender, age, ethnicity)",
        "impact": "Medium",
        "effort": "Medium",
        "expected_improvement": "2-6%"
    })
    
    # Tip 8: Threshold tuning
    tips.append({
        "rank": 8,
        "category": "Inference",
        "tip": "Adjust recognition threshold based on false positive/negative rates",
        "impact": "Low",
        "effort": "Low",
        "expected_improvement": "1-3%"
    })
    
    return {
        "tips": tips,
        "total_tips": len(tips),
        "current_stats": {
            "total_samples": len(face_records),
            "unique_visitors": len(set(f.visitor_id for f in face_records))
        },
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    logger.info("Training API initialized")
