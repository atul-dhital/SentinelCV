from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import String, cast, func, or_, text
from models import models
from schemas import schemas
from uuid import UUID
from datetime import datetime
from db.base import IS_SQLITE
from core.runtime_registry import get_runtime_component
from core.security import encrypt_embedding, decrypt_embedding, current_embedding_key_version
import json
import math
import logging
import os
import threading

from services import custom_classifier_service

logger = logging.getLogger(__name__)

# Configurable blend weight for custom classifier score (pgvector weight = 1 - this)
_CLASSIFIER_BLEND_WEIGHT = float(os.getenv("CLASSIFIER_BLEND_WEIGHT", "0.45"))

# ── Continual Learning buffer (in-process, per-org) ─────────────────────────

_CL_BUFFERS: Dict[str, Any] = {}
_CL_LOCK = threading.Lock()
_CL_AVAILABLE = False
try:
    from ai_services.continual_learning import ContinualLearning as _ContinualLearning
    _CL_AVAILABLE = True
except Exception:
    pass


def _get_cl_buffer(org_id: str) -> Optional[Any]:
    if not _CL_AVAILABLE:
        return None
    with _CL_LOCK:
        if org_id not in _CL_BUFFERS:
            _CL_BUFFERS[org_id] = _ContinualLearning()
        return _CL_BUFFERS[org_id]


def _add_to_cl_buffer(org_id: str, visitor_id: str, embedding: List[float], confidence: float) -> None:
    """Add a confirmed identification to the continual learning buffer; export at 50% capacity."""
    import numpy as _np_cl
    buffer = _get_cl_buffer(org_id)
    if buffer is None:
        return
    try:
        arr = _np_cl.array(embedding, dtype=_np_cl.float32)
        buffer.add_sample(visitor_id, arr, confidence, source="inference")
        stats = buffer.get_stats()
        if stats.get("memory_usage_percent", 0) >= 50:
            from core.paths import DATA_DIR
            from pathlib import Path as _Path
            export_path = str(_Path(DATA_DIR) / "continual_learning" / f"{org_id}_buffer.json")
            _Path(export_path).parent.mkdir(parents=True, exist_ok=True)
            buffer.export_buffer(export_path)
            logger.debug("[CL] Exported buffer for org %s (%d samples)", org_id, stats.get("total_samples", 0))
    except Exception as cl_exc:
        logger.debug("[CL] Buffer update failed: %s", cl_exc)

# ── Detection de-duplication / cooldown ─────────────────────────────────────
# The live recognition paths fire once per processed frame, so a visitor who
# lingers (or re-enters) generates a new log every frame. This cooldown collapses
# that into one log per visit, keyed by (org, visitor, camera). Unidentified
# detections are never suppressed (they may be different people). In-process and
# best-effort — survives within a running backend, resets on restart.
_DEDUP_LOCK = threading.Lock()
_RECENT_DETECTIONS: Dict[str, float] = {}
_DETECTION_COOLDOWN_SECONDS = float(os.getenv("DETECTION_COOLDOWN_SECONDS", "30"))


def should_log_detection(organization_id: Any, visitor_id: Any, camera_id: Any) -> bool:
    """Return False when an identical (org, visitor, camera) detection was logged
    within DETECTION_COOLDOWN_SECONDS. Set DETECTION_COOLDOWN_SECONDS=0 to disable.

    G7: the cooldown is held in Redis (survives backend restarts and is shared
    across workers), with an in-process fallback when Redis is unavailable."""
    if _DETECTION_COOLDOWN_SECONDS <= 0 or not visitor_id:
        return True

    key = f"sentinelcv:dedup:{organization_id}:{visitor_id}:{camera_id or 'none'}"

    # Preferred: Redis-backed cooldown (durable + cross-worker).
    try:
        from services.redis_service import get_redis_service
        svc = get_redis_service()
        if svc.cache_get(key) is not None:
            return False
        svc.cache_set(key, "1", ttl=int(_DETECTION_COOLDOWN_SECONDS))
        return True
    except Exception:
        pass

    # Fallback: in-process cooldown (single worker only).
    import time as _time
    now = _time.monotonic()
    with _DEDUP_LOCK:
        last = _RECENT_DETECTIONS.get(key)
        if last is not None and (now - last) < _DETECTION_COOLDOWN_SECONDS:
            return False
        _RECENT_DETECTIONS[key] = now
        if len(_RECENT_DETECTIONS) > 10000:
            cutoff = now - _DETECTION_COOLDOWN_SECONDS
            for stale in [k for k, v in _RECENT_DETECTIONS.items() if v < cutoff]:
                _RECENT_DETECTIONS.pop(stale, None)
    return True


MAX_FACE_DATA_PER_VISITOR = 5
VALID_FACE_ANGLES = {"frontal", "45_left", "45_right", "profile", "top"}
FACE_ANGLE_ALIASES = {
    "profile_left": "profile",
    "profile_right": "profile",
    "top_down": "top",
    "topdown": "top",
}


def _fire_ab_recording(org_id_str: str, confidence: float, used_classifier: bool) -> None:
    """Record an A/B inference result in the background; never blocks the hot path."""
    from db.base import SessionLocal as _SL

    def _record() -> None:
        rec_db = _SL()
        try:
            exp = rec_db.query(models.ABTestExperiment).filter(
                models.ABTestExperiment.organization_id == org_id_str,
                models.ABTestExperiment.status == "running",
            ).first()
            if exp is None:
                return
            from services import model_versioning_service as _mvs
            model_version_id = str(exp.model_b_id if used_classifier else exp.model_a_id)
            _mvs.record_ab_result(
                rec_db,
                experiment_id=str(exp.id),
                model_version_id=model_version_id,
                visitor_log_id=None,
                predicted_correctly=None,
                confidence=confidence,
                latency_ms=0.0,
            )
        except Exception as exc:
            logger.debug("[AB] Background record failed: %s", exc)
        finally:
            rec_db.close()

    threading.Thread(target=_record, daemon=True).start()


def _rollback_after_read_failure(db: Session, context: str) -> None:
    """Clear aborted PostgreSQL transactions before falling back to a safer path."""
    try:
        db.rollback()
    except Exception as rollback_exc:
        logger.debug("Session rollback failed after %s: %s", context, rollback_exc)


def normalize_face_angle(angle: Optional[Any]) -> Optional[str]:
    if angle is None:
        return None
    if hasattr(angle, "value"):
        angle = getattr(angle, "value")
    if not isinstance(angle, str):
        angle = str(angle)
    value = angle.strip().lower()
    if not value:
        return None
    value = FACE_ANGLE_ALIASES.get(value, value)
    if value in VALID_FACE_ANGLES:
        return value
    return None


def _env_int(name: str, default: int, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default

    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _apply_pgvector_session_settings(db: Session) -> Dict[str, Any]:
    if IS_SQLITE:
        return {
            "pgvector_index_type": "sqlite",
            "pgvector_ivfflat_probes": None,
            "pgvector_hnsw_ef_search": None,
        }

    index_type = os.getenv("PGVECTOR_INDEX_TYPE", "hnsw").strip().lower()
    if index_type not in {"ivfflat", "hnsw"}:
        index_type = "hnsw"

    ivfflat_probes: Optional[int] = None
    hnsw_ef_search: Optional[int] = None

    try:
        if index_type == "ivfflat":
            ivfflat_probes = _env_int("PGVECTOR_IVFFLAT_PROBES", 10, min_value=1, max_value=200)
            db.execute(text(f"SET LOCAL ivfflat.probes = {ivfflat_probes}"))
        else:
            hnsw_ef_search = _env_int("PGVECTOR_HNSW_EF_SEARCH", 64, min_value=1, max_value=1000)
            db.execute(text(f"SET LOCAL hnsw.ef_search = {hnsw_ef_search}"))
    except Exception as exc:
        _rollback_after_read_failure(db, "pgvector session tuning")
        logger.debug("pgvector tuning skipped: %s", exc)

    return {
        "pgvector_index_type": index_type,
        "pgvector_ivfflat_probes": ivfflat_probes,
        "pgvector_hnsw_ef_search": hnsw_ef_search,
    }


def _parse_embedding_payload(raw_embedding: Any) -> Optional[List[float]]:
    """Parse embedding payload from encrypted JSON, plain JSON, list, or vector-like values."""
    if raw_embedding is None:
        return None

    if isinstance(raw_embedding, (list, tuple)):
        try:
            return [float(value) for value in raw_embedding]
        except (TypeError, ValueError):
            return None

    tolist = getattr(raw_embedding, "tolist", None)
    if callable(tolist):
        try:
            values = tolist()
            if isinstance(values, list):
                return [float(value) for value in values]
        except (TypeError, ValueError):
            return None

    if isinstance(raw_embedding, str):
        # Build candidate list: try decrypt first, then use raw string as fallback
        candidate_strings: List[str] = []
        try:
            candidate_strings.append(decrypt_embedding(raw_embedding))
        except Exception:
            pass
        candidate_strings.append(raw_embedding)

        for candidate in candidate_strings:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, list):
                    return [float(value) for value in parsed]
                # SQLite stores JSON-encoded encrypted string → json.loads yields the v1:... str
                if isinstance(parsed, str):
                    try:
                        inner = decrypt_embedding(parsed)
                        inner_parsed = json.loads(inner)
                        if isinstance(inner_parsed, list):
                            return [float(value) for value in inner_parsed]
                    except Exception:
                        pass
            except Exception:
                continue

        cleaned = raw_embedding.strip()
        if cleaned.startswith("[") and cleaned.endswith("]"):
            try:
                return [float(piece.strip()) for piece in cleaned[1:-1].split(",") if piece.strip()]
            except (TypeError, ValueError):
                return None

    return None


def parse_embedding_payload(raw_embedding: Any) -> Optional[List[float]]:
    """Public wrapper for parsing embedding payloads from DB fields."""
    return _parse_embedding_payload(raw_embedding)


def serialize_embedding_for_storage(embedding: List[float]) -> Any:
    """Serialize embeddings for storage based on DB backend capabilities."""
    values = [float(value) for value in embedding]
    if IS_SQLITE:
        return encrypt_embedding(json.dumps(values))
    return values


def _get_custom_classifier_scores(
    organization_id: UUID,
    embedding: List[float],
) -> Optional[Dict[str, float]]:
    component = get_runtime_component("face_recognition") or {}
    current_model = str(component.get("current_model") or "").strip().lower()
    artifact_path = str(component.get("current_artifact") or "").strip()

    is_custom_mode = "custom" in current_model or "custom_classifier" in artifact_path.lower()
    if not is_custom_mode or not artifact_path:
        return None

    try:
        scores = custom_classifier_service.predict_probabilities(
            artifact_path,
            embedding,
            organization_id=str(organization_id),
        )
        return scores or None
    except FileNotFoundError:
        logger.warning("Configured custom classifier artifact was not found: %s", artifact_path)
    except Exception as exc:
        logger.warning("Custom classifier inference failed; falling back to similarity search: %s", exc)
    return None


def _search_postgres_by_vector_distance(
    db: Session,
    organization_id: UUID,
    embedding: List[float],
    threshold: float,
    angle: Optional[str],
    angle_only: bool = False,
    classifier_scores: Optional[Dict[str, float]] = None,
) -> Optional[Tuple[models.Visitor, float, Optional[UUID], Dict[str, Any]]]:
    """Use pgvector cosine distance when the PostgreSQL vector comparator is available."""
    if len(embedding) != 512:
        logger.warning(
            "pgvector similarity query skipped: expected 512-dim embedding, got %s; falling back.",
            len(embedding),
        )
        return None

    candidate_limit = _env_int("PGVECTOR_CANDIDATE_LIMIT", 300, min_value=50, max_value=1200)
    pgvector_settings = _apply_pgvector_session_settings(db)

    try:
        distance_expr = models.FaceData.embedding.cosine_distance([float(value) for value in embedding])
        query = (
            db.query(
                models.FaceData,
                models.Visitor,
                distance_expr.label("distance"),
            )
            .join(models.Visitor, models.FaceData.visitor_id == models.Visitor.id)
            .filter(models.Visitor.organization_id == organization_id)
            .filter(models.FaceData.embedding.isnot(None))
        )
        if angle_only and angle:
            query = query.filter(models.FaceData.face_angle == angle)
        candidate_rows = (
            query.order_by(distance_expr.asc())
            .limit(candidate_limit)
            .all()
        )
    except Exception as exc:
        _rollback_after_read_failure(db, "pgvector similarity query")
        logger.warning("pgvector similarity query unavailable; falling back to Python cosine scan: %s", exc)
        return None

    visitor_scores: Dict[str, List[Tuple[float, models.FaceData, models.Visitor]]] = {}
    for face, visitor, distance in candidate_rows:
        if distance is None:
            continue
        similarity = max(0.0, min(1.0, 1.0 - float(distance)))
        visitor_scores.setdefault(str(visitor.id), []).append((similarity, face, visitor))

    best_visitor: Optional[models.Visitor] = None
    best_confidence = 0.0
    best_face_data_id = None
    best_angle_scores: Dict[str, Any] = {}

    for scores in visitor_scores.values():
        ranked = sorted(scores, key=lambda item: item[0], reverse=True)
        top_score, top_face, visitor_obj = ranked[0]

        effective_threshold = threshold
        if getattr(visitor_obj, "custom_threshold", None) is not None:
            effective_threshold = float(visitor_obj.custom_threshold)

        if len(ranked) > 1:
            top_k = [score for score, *_rest in ranked[: min(3, len(ranked))]]
            consensus_score = sum(top_k) / len(top_k)
            # No artificial boost — earlier code added +0.05 here, biasing
            # toward false positives for visitors with multiple stored
            # embeddings. For a security/identification system that is the
            # wrong direction (a misidentified person is worse than an
            # uncertain match). Take the higher of (top single match) and
            # (top-k consensus average) instead.
            final_score = max(top_score, consensus_score)
            metadata = {
                "method": "pgvector_top_k_consensus",
                "sample_count": len(ranked),
                "top_k": len(top_k),
                "consensus_score": float(consensus_score),
            }
        else:
            final_score = top_score
            metadata = {
                "method": "pgvector_single_embedding",
                "sample_count": 1,
            }

        metadata["detected_angle"] = angle or "unknown"
        metadata["match_similarity"] = float(final_score)
        metadata["search_backend"] = "pgvector_cosine_distance"
        metadata["candidate_limit"] = candidate_limit
        metadata.update(pgvector_settings)

        if classifier_scores:
            visitor_key = str(visitor_obj.id)
            classifier_confidence = classifier_scores.get(visitor_key)
            if classifier_confidence is not None:
                classifier_confidence = float(classifier_confidence)
                metadata["custom_classifier_confidence"] = classifier_confidence
                blended_score = min(0.999, ((1.0 - _CLASSIFIER_BLEND_WEIGHT) * float(final_score)) + (_CLASSIFIER_BLEND_WEIGHT * classifier_confidence))
                metadata["blended_score"] = float(blended_score)
                metadata["search_backend"] = "pgvector_plus_custom_classifier"
                final_score = float(blended_score)

        if final_score >= effective_threshold and final_score > best_confidence:
            best_confidence = float(final_score)
            best_visitor = visitor_obj
            best_face_data_id = top_face.id
            best_angle_scores = metadata

    if best_visitor:
        return best_visitor, best_confidence, best_face_data_id, best_angle_scores
    return None


def get_visitor(db: Session, visitor_id: UUID) -> Optional[models.Visitor]:
    return db.query(models.Visitor).filter(models.Visitor.id == visitor_id).first()


def get_visitors_by_org(
    db: Session,
    organization_id: UUID,
    skip: int = 0,
    limit: int = 20,
    search: Optional[str] = None,
    created_before=None,
) -> Tuple[List[models.Visitor], int]:
    """Return (visitors, total_count) for pagination.

    When ``created_before`` is provided (a datetime), cursor-based pagination
    is used: visitors created before that timestamp are returned ordered by
    ``created_at DESC``, skipping the offset scan.
    """
    query = db.query(models.Visitor).filter(
        models.Visitor.organization_id == organization_id
    )
    if search:
        like_pattern = f"%{search}%"
        query = query.filter(
            models.Visitor.name.ilike(like_pattern)
            | models.Visitor.email.ilike(like_pattern)
            | models.Visitor.phone.ilike(like_pattern)
        )
    if created_before is not None:
        query = query.filter(models.Visitor.created_at < created_before)
    total = query.count()
    visitors = (
        query.order_by(models.Visitor.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return visitors, total


def create_visitor(db: Session, visitor: schemas.VisitorCreate) -> models.Visitor:
    data = visitor.model_dump()
    # Schema uses "metadata" but model column is "visitor_metadata"
    if "metadata" in data:
        data["visitor_metadata"] = data.pop("metadata")
    db_visitor = models.Visitor(**data)
    db.add(db_visitor)
    db.commit()
    db.refresh(db_visitor)
    return db_visitor


def update_visitor(
    db: Session, visitor: models.Visitor, update_data: schemas.VisitorUpdate
) -> models.Visitor:
    update_dict = update_data.model_dump(exclude_unset=True)
    # Schema uses "metadata" but model column is "visitor_metadata"
    if "metadata" in update_dict:
        update_dict["visitor_metadata"] = update_dict.pop("metadata")
    for key, value in update_dict.items():
        setattr(visitor, key, value)
    db.commit()
    db.refresh(visitor)
    return visitor


def delete_visitor(db: Session, visitor: models.Visitor):
    # Preserve immutable logs while removing both references that would block
    # cascading deletion of the visitor's FaceData rows.
    db.query(models.VisitorLog).filter(
        models.VisitorLog.visitor_id == visitor.id
    ).update(
        {
            "visitor_id": None,
            "face_data_id": None,
            "identified": False,
            "status": "unidentified",
        },
        synchronize_session=False,
    )
    # Other tables FK'd to visitors.id aren't covered by an ORM delete-orphan
    # cascade on Visitor. Null out the nullable ones (preserve the row, drop
    # the reference) and delete the non-nullable ones (visitor-scoped
    # analytics with no meaning once the visitor is gone) — otherwise the
    # DELETE below hits ForeignKeyViolation whenever any of these exist.
    for referencing_model in (
        models.VisitorAlert,
        models.BehaviorEvent,
        models.ContinuousLearningSignal,
        models.UserSession,
    ):
        db.query(referencing_model).filter(
            referencing_model.visitor_id == visitor.id
        ).update({"visitor_id": None}, synchronize_session=False)

    # Watchlist flags and cross-camera movement summaries are meaningless
    # without the visitor they're about (unlike the log-style tables above,
    # which read fine as anonymized history) — delete rather than null.
    for owned_model in (models.Watchlist, models.CrossCameraMovementSummary):
        db.query(owned_model).filter(
            owned_model.visitor_id == visitor.id
        ).delete(synchronize_session=False)

    db.delete(visitor)
    db.commit()


def _search_records_by_embedding(
    face_records: List[models.FaceData],
    embedding: List[float],
    threshold: float,
    angle: Optional[str],
    classifier_scores: Optional[Dict[str, float]] = None,
) -> Optional[Tuple[models.Visitor, float, Optional[UUID], Dict[str, Any]]]:
    visitor_scores: Dict[str, List[Tuple[float, models.FaceData]]] = {}
    for face in face_records:
        stored = _parse_embedding_payload(face.embedding)
        if not stored:
            continue

        dimensions = min(len(embedding), len(stored))
        if dimensions == 0:
            continue

        query_vec = embedding[:dimensions]
        stored_vec = stored[:dimensions]

        dot = sum(a * b for a, b in zip(query_vec, stored_vec))
        norm_a = math.sqrt(sum(a * a for a in query_vec))
        norm_b = math.sqrt(sum(b * b for b in stored_vec))
        if norm_a == 0 or norm_b == 0:
            continue

        similarity = dot / (norm_a * norm_b)
        visitor_scores.setdefault(str(face.visitor_id), []).append((float(similarity), face))

    best_visitor: Optional[models.Visitor] = None
    best_confidence = 0.0
    best_face_data_id = None
    best_angle_scores: Dict[str, Any] = {}

    for scores in visitor_scores.values():
        if not scores:
            continue

        visitor_obj = scores[0][1].visitor

        effective_threshold = threshold
        if hasattr(visitor_obj, "custom_threshold") and visitor_obj.custom_threshold is not None:
            effective_threshold = float(visitor_obj.custom_threshold)

        ranked = sorted(scores, key=lambda item: item[0], reverse=True)
        top_score, top_face = ranked[0]

        metadata: Dict[str, Any]
        if len(ranked) > 1:
            top_k = [score for score, _face in ranked[: min(3, len(ranked))]]
            consensus_score = sum(top_k) / len(top_k)
            # See note in pgvector path above — the +0.05 boost was removed
            # because it biased the system toward false positives.
            final_score = max(top_score, consensus_score)
            metadata = {
                "method": "top_k_consensus",
                "sample_count": len(ranked),
                "top_k": len(top_k),
                "consensus_score": float(consensus_score),
            }
        else:
            final_score = top_score
            metadata = {
                "method": "single_embedding",
                "sample_count": 1,
            }

        metadata["detected_angle"] = angle or "unknown"
        metadata["match_similarity"] = float(final_score)
        metadata["search_backend"] = "python_cosine_similarity"

        if classifier_scores:
            visitor_key = str(visitor_obj.id)
            classifier_confidence = classifier_scores.get(visitor_key)
            if classifier_confidence is not None:
                classifier_confidence = float(classifier_confidence)
                metadata["custom_classifier_confidence"] = classifier_confidence
                blended_score = min(0.999, ((1.0 - _CLASSIFIER_BLEND_WEIGHT) * float(final_score)) + (_CLASSIFIER_BLEND_WEIGHT * classifier_confidence))
                metadata["blended_score"] = float(blended_score)
                metadata["search_backend"] = "python_cosine_plus_custom_classifier"
                final_score = float(blended_score)

        if final_score >= effective_threshold and final_score > best_confidence:
            best_confidence = float(final_score)
            best_visitor = visitor_obj
            best_face_data_id = top_face.id
            best_angle_scores = metadata

    if best_visitor:
        return best_visitor, best_confidence, best_face_data_id, best_angle_scores
    return None


def search_visitor_by_embedding(
    db: Session,
    organization_id: UUID,
    embedding: List[float],
    threshold: float = 0.6,
    angle: Optional[str] = None,
) -> Optional[Tuple[models.Visitor, float, Optional[UUID], Dict]]:
    """
    Search for a visitor by face embedding.
    Uses pgvector cosine distance on PostgreSQL, or brute-force on SQLite.
    
    S16-ACC-002: Adaptive per-visitor thresholds.
    S16-ACC-007: Confidence boost for multiple embeddings.
    S16-ACC-008: Temporal enhancement.
    Multi-Angle: If angle is provided, uses consensus matching.
    
    Returns (visitor, confidence, face_data_id, angle_scores) or None.
    """
    normalized_angle = normalize_face_angle(angle)
    classifier_scores = _get_custom_classifier_scores(organization_id, embedding)
    used_classifier = classifier_scores is not None

    if not IS_SQLITE:
        if normalized_angle:
            pgvector_match = _search_postgres_by_vector_distance(
                db=db,
                organization_id=organization_id,
                embedding=embedding,
                threshold=threshold,
                angle=normalized_angle,
                angle_only=True,
                classifier_scores=classifier_scores,
            )
            if pgvector_match is not None:
                _v, _c, _f, _m = pgvector_match
                _org = str(organization_id)
                threading.Thread(target=_add_to_cl_buffer, args=(_org, str(_v.id), embedding, _c), daemon=True).start()
                _fire_ab_recording(_org, _c, used_classifier)
                return pgvector_match

        pgvector_match = _search_postgres_by_vector_distance(
            db=db,
            organization_id=organization_id,
            embedding=embedding,
            threshold=threshold,
            angle=normalized_angle,
            classifier_scores=classifier_scores,
        )
        if pgvector_match is not None:
            _v, _c, _f, _m = pgvector_match
            _org = str(organization_id)
            threading.Thread(target=_add_to_cl_buffer, args=(_org, str(_v.id), embedding, _c), daemon=True).start()
            _fire_ab_recording(_org, _c, used_classifier)
            return pgvector_match

    face_records = (
        db.query(models.FaceData)
        .join(models.Visitor)
        .filter(models.Visitor.organization_id == organization_id)
        .all()
    )

    if normalized_angle:
        filtered_records = [
            face for face in face_records
            if normalize_face_angle(face.face_angle) == normalized_angle
        ]
        angle_match = _search_records_by_embedding(
            filtered_records,
            embedding,
            threshold,
            normalized_angle,
            classifier_scores=classifier_scores,
        )
        if angle_match is not None:
            _v, _c, _f, _m = angle_match
            _org = str(organization_id)
            threading.Thread(target=_add_to_cl_buffer, args=(_org, str(_v.id), embedding, _c), daemon=True).start()
            _fire_ab_recording(_org, _c, used_classifier)
            return angle_match

    result = _search_records_by_embedding(
        face_records,
        embedding,
        threshold,
        normalized_angle,
        classifier_scores=classifier_scores,
    )

    if result is not None:
        matched_visitor, confidence, _face_id, _meta = result
        org_id_str = str(organization_id)
        # Wire continual learning — add confirmed match to per-org buffer
        threading.Thread(
            target=_add_to_cl_buffer,
            args=(org_id_str, str(matched_visitor.id), embedding, confidence),
            daemon=True,
        ).start()
        # Wire A/B test recording
        _fire_ab_recording(org_id_str, confidence, used_classifier)

    return result


def create_face_data(
    db: Session,
    visitor_id: UUID,
    embedding: List[float],
    image_url: Optional[str] = None,
    quality_score: float = 0.0,
    face_angle: Optional[str] = None,
    is_primary: bool = False,
) -> models.FaceData:
    stored_embedding = serialize_embedding_for_storage(embedding)
    normalized_angle = normalize_face_angle(face_angle)
    # Tag the row with the key version that wrapped this embedding so we can
    # rotate the encryption key in the future without an eager re-wrap of
    # every row. Only meaningful when ciphertext is stored (SQLite path);
    # PostgreSQL keeps the value for forward-compat / observability.
    key_version = current_embedding_key_version() if IS_SQLITE else None
    db_face = models.FaceData(
        visitor_id=visitor_id,
        embedding=stored_embedding,
        embedding_key_version=key_version,
        image_url=image_url,
        quality_score=quality_score,
        face_angle=normalized_angle,
        is_primary=is_primary,
    )
    db.add(db_face)
    db.commit()
    db.refresh(db_face)
    return db_face


def get_face_data_count(db: Session, visitor_id: UUID) -> int:
    return (
        db.query(func.count(models.FaceData.id))
        .filter(models.FaceData.visitor_id == visitor_id)
        .scalar()
        or 0
    )


def get_face_data_for_visitor(
    db: Session, visitor_id: UUID
) -> List[models.FaceData]:
    return (
        db.query(models.FaceData)
        .filter(models.FaceData.visitor_id == visitor_id)
        .order_by(models.FaceData.created_at.desc())
        .all()
    )


def get_face_summary_for_visitors(
    db: Session, visitor_ids: List[UUID]
) -> Dict[str, Dict[str, Any]]:
    """Return the face count and primary image URL for a set of visitors."""
    if not visitor_ids:
        return {}

    faces = (
        db.query(models.FaceData)
        .filter(models.FaceData.visitor_id.in_(visitor_ids))
        .order_by(models.FaceData.is_primary.desc(), models.FaceData.created_at.desc())
        .all()
    )

    summary: Dict[str, Dict[str, Any]] = {}
    for face in faces:
        key = str(face.visitor_id)
        entry = summary.setdefault(
            key,
            {
                "face_count": 0,
                "primary_face_image_url": None,
            },
        )
        entry["face_count"] += 1
        if entry["primary_face_image_url"] is None and face.image_url:
            entry["primary_face_image_url"] = face.image_url

    return summary


def get_face_summary_for_visitor(
    db: Session, visitor_id: UUID
) -> Dict[str, Any]:
    """Convenience wrapper for a single visitor."""
    summary = get_face_summary_for_visitors(db, [visitor_id])
    return summary.get(str(visitor_id), {"face_count": 0, "primary_face_image_url": None})


def delete_face_data(db: Session, face_data_id: UUID) -> bool:
    face = db.query(models.FaceData).filter(models.FaceData.id == face_data_id).first()
    if not face:
        return False
    # Visitor logs are immutable, so retain them and detach the deleted
    # embedding reference instead of attempting to cascade-delete history.
    db.query(models.VisitorLog).filter(
        models.VisitorLog.face_data_id == face_data_id
    ).update({"face_data_id": None}, synchronize_session=False)
    db.delete(face)
    db.commit()
    return True


def set_primary_face_data(
    db: Session,
    visitor_id: UUID,
    face_data_id: UUID,
) -> Optional[models.FaceData]:
    """Mark one face record as the primary reference for a visitor."""
    faces = get_face_data_for_visitor(db, visitor_id)
    target = next((face for face in faces if face.id == face_data_id), None)
    if not target:
        return None

    for face in faces:
        face.is_primary = face.id == face_data_id

    db.commit()
    db.refresh(target)
    return target


# --- Visitor Logs ---


def log_visitor_event(db: Session, log: schemas.VisitorLogCreate) -> models.VisitorLog:
    payload = log.model_dump()

    visitor_id = payload.get("visitor_id")
    if visitor_id:
        visitor = db.query(models.Visitor).filter(
            models.Visitor.id == visitor_id,
            models.Visitor.organization_id == payload.get("organization_id"),
        ).first()
        if visitor is None:
            payload["visitor_id"] = None

    is_identified = bool(payload.get("visitor_id"))
    payload["identified"] = is_identified
    payload["status"] = "identified" if is_identified else "unidentified"

    db_log = models.VisitorLog(**payload)
    db.add(db_log)
    db.commit()
    db.refresh(db_log)

    # Dispatch webhooks in a background thread so detection flow is non-blocking
    _dispatch_detection_webhooks_async(db, db_log)

    return db_log


def _dispatch_detection_webhooks_async(db: Session, log: models.VisitorLog) -> None:
    """Fire-and-forget webhook dispatch for visitor.detected / visitor.identified events."""
    from services.webhook_delivery_service import build_payload, deliver_webhook, record_delivery_log
    from db.base import SessionLocal

    event = "visitor.identified" if log.identified else "visitor.detected"
    org_id = log.organization_id
    log_id = str(log.id)
    log_data = {
        "log_id": log_id,
        "visitor_id": str(log.visitor_id) if log.visitor_id else None,
        "camera_id": str(log.camera_id) if log.camera_id else None,
        "confidence": log.confidence,
        "status": log.status,
        "timestamp": log.timestamp.isoformat() if log.timestamp else None,
    }

    def _dispatch() -> None:
        thread_db = SessionLocal()
        try:
            webhooks = thread_db.query(models.Webhook).filter(
                models.Webhook.organization_id == org_id,
                models.Webhook.is_active == True,
            ).all()
            for webhook in webhooks:
                subscribed = webhook.events or []
                if subscribed and event not in subscribed:
                    continue
                payload = build_payload(webhook, event, log_data)
                result = deliver_webhook(webhook, payload)
                record_delivery_log(thread_db, webhook, event=event, payload=payload, delivery=result)
        except Exception as exc:
            logger.error("Webhook dispatch failed for log %s: %s", log_id, exc)
        finally:
            thread_db.close()

    threading.Thread(target=_dispatch, daemon=True).start()


def get_logs(
    db: Session,
    organization_id: UUID,
    status: Optional[str] = None,
    camera_id: Optional[UUID] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> Tuple[List[models.VisitorLog], int]:
    """Return (logs, total_count) for pagination with filters."""
    query = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == organization_id
    )

    if search and search.strip():
        term = search.strip()
        pattern = f"%{term}%"
        query = query.outerjoin(
            models.Visitor,
            models.VisitorLog.visitor_id == models.Visitor.id,
        ).filter(
            or_(
                models.Visitor.name.ilike(pattern),
                cast(models.VisitorLog.visitor_id, String).ilike(pattern),
                cast(models.VisitorLog.id, String).ilike(pattern),
                cast(models.VisitorLog.track_id, String).ilike(pattern),
                models.VisitorLog.status.ilike(pattern),
            )
        )

    if status:
        query = query.filter(models.VisitorLog.status == status)
    if camera_id:
        query = query.filter(models.VisitorLog.camera_id == camera_id)
    if date_from:
        query = query.filter(models.VisitorLog.timestamp >= date_from)
    if date_to:
        query = query.filter(models.VisitorLog.timestamp <= date_to)

    total = query.count()
    logs = (
        query.order_by(models.VisitorLog.timestamp.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return logs, total


def get_log(db: Session, log_id: UUID) -> Optional[models.VisitorLog]:
    return db.query(models.VisitorLog).filter(models.VisitorLog.id == log_id).first()


def get_unidentified_logs(
    db: Session, organization_id: UUID, skip: int = 0, limit: int = 20
) -> Tuple[List[models.VisitorLog], int]:
    """Get logs that need manual review."""
    query = db.query(models.VisitorLog).filter(
        models.VisitorLog.organization_id == organization_id,
        models.VisitorLog.status.in_(["unidentified", "detected"]),
    )
    total = query.count()
    logs = (
        query.order_by(models.VisitorLog.timestamp.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return logs, total


def assign_log_to_visitor(
    db: Session, log: models.VisitorLog, visitor_id: UUID
) -> models.VisitorLog:
    log.visitor_id = visitor_id
    log.status = "reviewed"
    log.identified = True
    db.commit()
    db.refresh(log)
    return log


def get_dashboard_stats(db: Session, organization_id: UUID) -> schemas.DashboardStats:
    """Compute dashboard statistics for an organization."""
    total_events = (
        db.query(func.count(models.VisitorLog.id))
        .filter(models.VisitorLog.organization_id == organization_id)
        .scalar()
        or 0
    )
    identified_count = (
        db.query(func.count(models.VisitorLog.id))
        .filter(
            models.VisitorLog.organization_id == organization_id,
            models.VisitorLog.status.in_(["identified", "reviewed"]),
        )
        .scalar()
        or 0
    )
    unidentified_count = (
        db.query(func.count(models.VisitorLog.id))
        .filter(
            models.VisitorLog.organization_id == organization_id,
            models.VisitorLog.status == "unidentified",
        )
        .scalar()
        or 0
    )
    pending_review = (
        db.query(func.count(models.VisitorLog.id))
        .filter(
            models.VisitorLog.organization_id == organization_id,
            models.VisitorLog.status.in_(["unidentified", "detected"]),
        )
        .scalar()
        or 0
    )
    total_visitors = (
        db.query(func.count(models.Visitor.id))
        .filter(models.Visitor.organization_id == organization_id)
        .scalar()
        or 0
    )
    cameras_online = (
        db.query(func.count(models.Camera.id))
        .filter(
            models.Camera.organization_id == organization_id,
            models.Camera.status == "online",
        )
        .scalar()
        or 0
    )
    return schemas.DashboardStats(
        identified_count=identified_count,
        unidentified_count=unidentified_count,
        total_events=total_events,
        total_visitors=total_visitors,
        pending_review=pending_review,
        cameras_online=cameras_online,
    )


# --- Audit Logs ---


def create_audit_log(
    db: Session,
    organization_id: UUID,
    user_id: Optional[UUID],
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    details: Optional[dict] = None,
    *,
    commit: bool = True,
) -> models.AuditLog:
    audit = models.AuditLog(
        organization_id=organization_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or {},
    )
    db.add(audit)
    if commit:
        db.commit()
        db.refresh(audit)
    else:
        db.flush()
    return audit


def get_audit_logs(
    db: Session,
    organization_id: UUID,
    skip: int = 0,
    limit: int = 50,
    search: Optional[str] = None,
    action: Optional[str] = None,
    user_id: Optional[UUID] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> Tuple[List[models.AuditLog], int]:
    query = db.query(models.AuditLog).filter(
        models.AuditLog.organization_id == organization_id
    )

    if action:
        query = query.filter(models.AuditLog.action == action)
    if user_id:
        query = query.filter(models.AuditLog.user_id == user_id)
    if date_from:
        query = query.filter(models.AuditLog.timestamp >= date_from)
    if date_to:
        query = query.filter(models.AuditLog.timestamp <= date_to)

    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (models.AuditLog.action.ilike(search_filter))
            | (models.AuditLog.entity_type.ilike(search_filter))
            | (models.AuditLog.entity_id.ilike(search_filter))
        )
    total = query.count()
    logs = (
        query.order_by(models.AuditLog.timestamp.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return logs, total
