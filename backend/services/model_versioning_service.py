"""
Model Versioning & A/B Testing Service

Provides model version management, promotion, rollback,
and A/B testing framework for face recognition models.
"""

import logging
import math
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── Model Versioning ────────────────────────────────────────────────────

def register_model(
    db: Session,
    organization_id: str,
    name: str,
    version: str,
    model_type: str,
    file_path: str,
    metrics: Dict[str, float],
) -> Any:
    """Register a new model version."""
    from models.models import ModelVersion

    model = ModelVersion(
        organization_id=organization_id,
        name=name,
        version=version,
        model_type=model_type,
        file_path=file_path,
        accuracy=metrics.get("accuracy"),
        precision=metrics.get("precision"),
        recall=metrics.get("recall"),
        f1_score=metrics.get("f1_score"),
        parameters=metrics.get("parameters", {}),
        is_active=True,
        is_production=False,
    )
    db.add(model)
    db.commit()
    db.refresh(model)
    logger.info(f"Registered model {name} v{version} (id={model.id})")
    return model


def promote_to_production(
    db: Session, organization_id: str, model_version_id: str
) -> Any:
    """Promote a model version to production, deactivating previous production model."""
    from models.models import ModelVersion

    # Deactivate current production model of same type
    target = db.query(ModelVersion).filter(
        ModelVersion.id == model_version_id,
        ModelVersion.organization_id == organization_id,
    ).first()

    if not target:
        raise ValueError("Model version not found")

    # Unset previous production
    db.query(ModelVersion).filter(
        ModelVersion.organization_id == organization_id,
        ModelVersion.model_type == target.model_type,
        ModelVersion.is_production == True,
    ).update({"is_production": False})

    target.is_production = True
    target.is_active = True
    db.commit()
    db.refresh(target)
    logger.info(f"Promoted model {target.name} v{target.version} to production")
    return target


def rollback_model(
    db: Session, organization_id: str, model_version_id: str
) -> Any:
    """Rollback to a specific model version."""
    return promote_to_production(db, organization_id, model_version_id)


def list_versions(
    db: Session,
    organization_id: str,
    model_type: Optional[str] = None,
    limit: int = 50,
) -> List[Any]:
    """List model versions with optional type filter."""
    from models.models import ModelVersion

    query = db.query(ModelVersion).filter(
        ModelVersion.organization_id == organization_id
    )
    if model_type:
        query = query.filter(ModelVersion.model_type == model_type)
    return query.order_by(ModelVersion.created_at.desc()).limit(limit).all()


def get_production_model(
    db: Session, organization_id: str, model_type: str
) -> Optional[Any]:
    """Get the current production model for a type."""
    from models.models import ModelVersion

    return db.query(ModelVersion).filter(
        ModelVersion.organization_id == organization_id,
        ModelVersion.model_type == model_type,
        ModelVersion.is_production == True,
    ).first()


def compare_versions(
    db: Session,
    organization_id: str,
    version_a_id: str,
    version_b_id: str,
) -> Dict:
    """Compare metrics between two model versions."""
    from models.models import ModelVersion

    a = db.query(ModelVersion).filter(
        ModelVersion.id == version_a_id,
        ModelVersion.organization_id == organization_id,
    ).first()
    b = db.query(ModelVersion).filter(
        ModelVersion.id == version_b_id,
        ModelVersion.organization_id == organization_id,
    ).first()

    if not a or not b:
        raise ValueError("One or both model versions not found")

    def _diff(va, vb):
        if va is None or vb is None:
            return None
        return round(vb - va, 6)

    return {
        "model_a": {"id": str(a.id), "name": a.name, "version": a.version},
        "model_b": {"id": str(b.id), "name": b.name, "version": b.version},
        "comparison": {
            "accuracy": {"a": a.accuracy, "b": b.accuracy, "diff": _diff(a.accuracy, b.accuracy)},
            "precision": {"a": a.precision, "b": b.precision, "diff": _diff(a.precision, b.precision)},
            "recall": {"a": a.recall, "b": b.recall, "diff": _diff(a.recall, b.recall)},
            "f1_score": {"a": a.f1_score, "b": b.f1_score, "diff": _diff(a.f1_score, b.f1_score)},
        },
        "recommendation": "b" if (b.f1_score or 0) > (a.f1_score or 0) else "a",
    }


# ── A/B Testing ─────────────────────────────────────────────────────────

def create_experiment(
    db: Session,
    organization_id: str,
    name: str,
    description: str,
    model_a_id: str,
    model_b_id: str,
    traffic_split_percent: int = 50,
) -> Any:
    """Create a new A/B test experiment."""
    from models.models import ABTestExperiment

    experiment = ABTestExperiment(
        organization_id=organization_id,
        name=name,
        description=description,
        model_a_id=model_a_id,
        model_b_id=model_b_id,
        traffic_split_percent=traffic_split_percent,
        status="draft",
    )
    db.add(experiment)
    db.commit()
    db.refresh(experiment)
    logger.info(f"Created A/B experiment: {name}")
    return experiment


def start_experiment(db: Session, experiment_id: str) -> Any:
    """Start an A/B test experiment."""
    from models.models import ABTestExperiment

    exp = db.query(ABTestExperiment).filter(
        ABTestExperiment.id == experiment_id
    ).first()
    if not exp:
        raise ValueError("Experiment not found")
    if exp.status not in ("draft", "cancelled"):
        raise ValueError(f"Cannot start experiment in {exp.status} state")

    exp.status = "running"
    exp.start_date = datetime.now(timezone.utc)
    db.commit()
    db.refresh(exp)
    return exp


def record_ab_result(
    db: Session,
    experiment_id: str,
    model_version_id: str,
    visitor_log_id: str,
    predicted_correctly: bool,
    confidence: float,
    latency_ms: float,
) -> Any:
    """Record an individual A/B test result."""
    from models.models import ABTestResult

    result = ABTestResult(
        experiment_id=experiment_id,
        model_version_id=model_version_id,
        visitor_log_id=visitor_log_id,
        predicted_correctly=predicted_correctly,
        confidence=confidence,
        latency_ms=latency_ms,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def get_experiment_results(db: Session, experiment_id: str) -> Dict:
    """Get aggregated A/B test results with statistical significance."""
    from models.models import ABTestExperiment, ABTestResult

    exp = db.query(ABTestExperiment).filter(
        ABTestExperiment.id == experiment_id
    ).first()
    if not exp:
        raise ValueError("Experiment not found")

    results = db.query(ABTestResult).filter(
        ABTestResult.experiment_id == experiment_id
    ).all()

    # Split by model
    a_results = [r for r in results if str(r.model_version_id) == str(exp.model_a_id)]
    b_results = [r for r in results if str(r.model_version_id) == str(exp.model_b_id)]

    def _aggregate(rs):
        if not rs:
            return {"count": 0, "accuracy": 0, "avg_confidence": 0, "avg_latency": 0}
        correct = sum(1 for r in rs if r.predicted_correctly)
        return {
            "count": len(rs),
            "accuracy": correct / len(rs) if rs else 0,
            "avg_confidence": sum(r.confidence for r in rs) / len(rs),
            "avg_latency": sum(r.latency_ms for r in rs) / len(rs),
        }

    stats_a = _aggregate(a_results)
    stats_b = _aggregate(b_results)

    # Simple z-test for statistical significance
    significance = _calculate_significance(stats_a, stats_b)

    return {
        "experiment": {"id": str(exp.id), "name": exp.name, "status": exp.status},
        "model_a": stats_a,
        "model_b": stats_b,
        "total_samples": len(results),
        "statistical_significance": significance,
        "recommended_winner": "b" if stats_b["accuracy"] > stats_a["accuracy"] else "a",
    }


def _calculate_significance(stats_a: Dict, stats_b: Dict) -> Dict:
    """Calculate statistical significance using z-test for proportions."""
    n_a = stats_a["count"]
    n_b = stats_b["count"]

    if n_a < 30 or n_b < 30:
        return {"significant": False, "p_value": None, "note": "Insufficient samples (need 30+ per group)"}

    p_a = stats_a["accuracy"]
    p_b = stats_b["accuracy"]
    p_pool = (p_a * n_a + p_b * n_b) / (n_a + n_b)

    if p_pool == 0 or p_pool == 1:
        return {"significant": False, "p_value": None, "note": "No variance in results"}

    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    if se == 0:
        return {"significant": False, "p_value": None, "note": "Zero standard error"}

    z = abs(p_a - p_b) / se
    # Approximate p-value from z-score
    p_value = 2 * (1 - _normal_cdf(z))

    return {
        "significant": p_value < 0.05,
        "p_value": round(p_value, 6),
        "z_score": round(z, 4),
        "confidence_level": "95%" if p_value < 0.05 else "not significant",
    }


def _normal_cdf(x: float) -> float:
    """Approximate standard normal CDF using Abramowitz & Stegun."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def conclude_experiment(db: Session, experiment_id: str) -> Any:
    """Conclude an experiment and determine the winner."""
    from models.models import ABTestExperiment

    results = get_experiment_results(db, experiment_id)
    exp = db.query(ABTestExperiment).filter(
        ABTestExperiment.id == experiment_id
    ).first()

    if not exp:
        raise ValueError("Experiment not found")

    winner_id = exp.model_a_id if results["recommended_winner"] == "a" else exp.model_b_id
    exp.status = "completed"
    exp.winner_model_id = winner_id
    exp.end_date = datetime.now(timezone.utc)
    db.commit()
    db.refresh(exp)

    logger.info(f"Concluded experiment {exp.name}: winner = {results['recommended_winner']}")
    return {**results, "winner_model_id": str(winner_id)}
