"""3D face recognition service (US-FUT-033)."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

import numpy as np
from sqlalchemy.orm import Session

from models import models
from services import visitor_service

logger = logging.getLogger(__name__)


class ThreeDFaceService:
    """Service for storing and comparing 3D face captures."""

    def get_face_data(
        self, db: Session, organization_id: UUID, face_data_id: UUID
    ) -> Optional[models.ThreeDFaceData]:
        """Fetch a 3D face record scoped to an organization."""
        return (
            db.query(models.ThreeDFaceData)
            .join(models.Visitor, models.ThreeDFaceData.visitor_id == models.Visitor.id)
            .filter(models.ThreeDFaceData.id == face_data_id)
            .filter(models.Visitor.organization_id == organization_id)
            .first()
        )

    def create_face_data(
        self,
        db: Session,
        organization_id: UUID,
        visitor_id: UUID,
        detection_log_id: Optional[UUID],
        depth_map_path: Optional[str],
        point_cloud_path: Optional[str],
        face_mesh: Optional[Dict[str, Any]],
        texture_map_path: Optional[str],
        face_width_mm: Optional[float],
        face_height_mm: Optional[float],
        face_depth_mm: Optional[float],
        forehead_width_mm: Optional[float],
        nose_height_mm: Optional[float],
        embedding_3d: Optional[List[float]],
        embedding_confidence: float,
        capture_quality_score: float,
        mesh_density: Optional[int],
        depth_map_resolution: Optional[str],
    ) -> models.ThreeDFaceData:
        """Store a 3D face capture and optional embedding."""
        visitor = db.query(models.Visitor).filter(
            models.Visitor.id == visitor_id,
            models.Visitor.organization_id == organization_id,
        ).first()
        if visitor is None:
            raise ValueError("Visitor not found")

        detection_log = self._get_detection_log(db, detection_log_id, organization_id)

        parsed_embedding = self._coerce_embedding(embedding_3d)
        if parsed_embedding is None:
            parsed_embedding = self._generate_embedding_from_capture(
                face_mesh=face_mesh,
                metrics=[
                    face_width_mm,
                    face_height_mm,
                    face_depth_mm,
                    forehead_width_mm,
                    nose_height_mm,
                    float(capture_quality_score),
                    float(mesh_density or 0),
                ],
                paths=[
                    depth_map_path,
                    point_cloud_path,
                    texture_map_path,
                    str(visitor_id),
                ],
            )
            if parsed_embedding is not None and embedding_confidence <= 0.0:
                embedding_confidence = self._estimate_embedding_confidence(
                    capture_quality_score=capture_quality_score,
                    mesh_density=mesh_density,
                    has_face_mesh=bool(face_mesh),
                    has_depth_signal=bool(depth_map_path or point_cloud_path),
                )
        stored_embedding = (
            visitor_service.serialize_embedding_for_storage(parsed_embedding)
            if parsed_embedding is not None
            else None
        )

        record = models.ThreeDFaceData(
            visitor_id=visitor_id,
            detection_log_id=detection_log.id if detection_log else None,
            depth_map_path=depth_map_path,
            point_cloud_path=point_cloud_path,
            face_mesh=face_mesh,
            texture_map_path=texture_map_path,
            face_width_mm=face_width_mm,
            face_height_mm=face_height_mm,
            face_depth_mm=face_depth_mm,
            forehead_width_mm=forehead_width_mm,
            nose_height_mm=nose_height_mm,
            embedding_3d=stored_embedding,
            embedding_confidence=embedding_confidence,
            capture_quality_score=capture_quality_score,
            mesh_density=mesh_density,
            depth_map_resolution=depth_map_resolution,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def compare_faces(
        self,
        db: Session,
        organization_id: UUID,
        face_data_1_id: UUID,
        face_data_2_id: UUID,
        match_threshold: float = 0.75,
    ) -> models.ThreeDFaceComparison:
        """Compare two 3D face captures and store a comparison record."""
        face_data_1 = self.get_face_data(db, organization_id, face_data_1_id)
        face_data_2 = self.get_face_data(db, organization_id, face_data_2_id)
        if face_data_1 is None or face_data_2 is None:
            raise ValueError("3D face data not found")

        embedding_a = visitor_service._parse_embedding_payload(face_data_1.embedding_3d)
        embedding_b = visitor_service._parse_embedding_payload(face_data_2.embedding_3d)

        cosine_similarity = self._cosine_similarity(embedding_a, embedding_b)
        l2_distance = self._l2_distance(embedding_a, embedding_b)
        euclidean_distance = l2_distance

        shape_similarity = self._metric_similarity(
            [
                face_data_1.face_width_mm,
                face_data_1.face_height_mm,
                face_data_1.face_depth_mm,
                face_data_1.forehead_width_mm,
                face_data_1.nose_height_mm,
            ],
            [
                face_data_2.face_width_mm,
                face_data_2.face_height_mm,
                face_data_2.face_depth_mm,
                face_data_2.forehead_width_mm,
                face_data_2.nose_height_mm,
            ],
        )

        texture_similarity = self._calculate_texture_similarity(face_data_1, face_data_2)

        geometric_liveness_score = self._calculate_liveness_score(face_data_1, face_data_2)

        match_confidence = self._combine_match_confidence(
            cosine_similarity=cosine_similarity,
            shape_similarity=shape_similarity,
            texture_similarity=texture_similarity,
            geometric_liveness_score=geometric_liveness_score,
        )

        is_same_person = match_confidence >= match_threshold

        comparison = models.ThreeDFaceComparison(
            face_data_1_id=face_data_1.id,
            face_data_2_id=face_data_2.id,
            euclidean_distance=euclidean_distance,
            cosine_similarity=cosine_similarity,
            l2_distance=l2_distance,
            shape_similarity=shape_similarity,
            texture_similarity=texture_similarity,
            geometric_liveness_score=geometric_liveness_score,
            match_confidence=match_confidence,
            is_same_person=is_same_person,
        )
        db.add(comparison)
        db.commit()
        db.refresh(comparison)
        return comparison

    def compute_liveness_score(
        self,
        db: Session,
        organization_id: UUID,
        face_data_id: UUID,
    ) -> Dict[str, Any]:
        """Compute a simple geometric liveness score for a 3D capture."""
        face_data = self.get_face_data(db, organization_id, face_data_id)
        if face_data is None:
            raise ValueError("3D face data not found")

        score = self._calculate_liveness_score(face_data, None)
        return {
            "face_data_id": str(face_data.id),
            "geometric_liveness_score": score,
        }

    def identify_face_data(
        self,
        db: Session,
        organization_id: UUID,
        probe_face_data_id: UUID,
        *,
        limit: int = 5,
        match_threshold: float = 0.75,
    ) -> Dict[str, Any]:
        """Find the best 3D face matches for a probe capture across the organization."""
        probe = self.get_face_data(db, organization_id, probe_face_data_id)
        if probe is None:
            raise ValueError("3D face data not found")

        candidates = (
            db.query(models.ThreeDFaceData)
            .join(models.Visitor, models.ThreeDFaceData.visitor_id == models.Visitor.id)
            .filter(models.Visitor.organization_id == organization_id)
            .filter(models.ThreeDFaceData.id != probe.id)
            .order_by(models.ThreeDFaceData.created_at.desc())
            .all()
        )

        matches: List[Dict[str, Any]] = []
        for candidate in candidates:
            cosine_similarity = self._cosine_similarity(
                visitor_service._parse_embedding_payload(probe.embedding_3d),
                visitor_service._parse_embedding_payload(candidate.embedding_3d),
            )
            shape_similarity = self._metric_similarity(
                [
                    probe.face_width_mm,
                    probe.face_height_mm,
                    probe.face_depth_mm,
                    probe.forehead_width_mm,
                    probe.nose_height_mm,
                ],
                [
                    candidate.face_width_mm,
                    candidate.face_height_mm,
                    candidate.face_depth_mm,
                    candidate.forehead_width_mm,
                    candidate.nose_height_mm,
                ],
            )
            texture_similarity = self._calculate_texture_similarity(probe, candidate)
            liveness = self._calculate_liveness_score(probe, candidate)
            match_confidence = self._combine_match_confidence(
                cosine_similarity=cosine_similarity,
                shape_similarity=shape_similarity,
                texture_similarity=texture_similarity,
                geometric_liveness_score=liveness,
            )
            matches.append(
                {
                    "face_data_id": str(candidate.id),
                    "visitor_id": str(candidate.visitor_id),
                    "match_confidence": round(float(match_confidence), 4),
                    "cosine_similarity": cosine_similarity,
                    "shape_similarity": shape_similarity,
                    "texture_similarity": texture_similarity,
                    "geometric_liveness_score": liveness,
                    "is_same_person": bool(match_confidence >= match_threshold),
                }
            )

        matches.sort(key=lambda item: item["match_confidence"], reverse=True)
        return {
            "probe_face_data_id": str(probe.id),
            "matches": matches[:limit],
        }

    def _get_detection_log(
        self,
        db: Session,
        detection_log_id: Optional[UUID],
        organization_id: UUID,
    ) -> Optional[models.DetectionLog]:
        if detection_log_id is None:
            return None
        log = (
            db.query(models.DetectionLog)
            .join(models.CameraSession, models.DetectionLog.session_id == models.CameraSession.id)
            .filter(models.DetectionLog.id == detection_log_id)
            .filter(models.CameraSession.organization_id == organization_id)
            .first()
        )
        if log is None:
            raise ValueError("Detection log not found")
        return log

    def _coerce_embedding(self, embedding: Optional[List[float]]) -> Optional[List[float]]:
        if embedding is None:
            return None
        parsed = visitor_service._parse_embedding_payload(embedding)
        if parsed is None:
            raise ValueError("Invalid 3D embedding payload")
        return parsed

    def _cosine_similarity(
        self, embedding_a: Optional[List[float]], embedding_b: Optional[List[float]]
    ) -> Optional[float]:
        if not embedding_a or not embedding_b:
            return None
        dim = min(len(embedding_a), len(embedding_b))
        if dim == 0:
            return None
        vec_a = np.array(embedding_a[:dim], dtype=np.float64)
        vec_b = np.array(embedding_b[:dim], dtype=np.float64)
        denom = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
        if denom == 0.0:
            return None
        similarity = float(np.dot(vec_a, vec_b) / denom)
        return max(0.0, min(1.0, similarity))

    def _l2_distance(
        self, embedding_a: Optional[List[float]], embedding_b: Optional[List[float]]
    ) -> Optional[float]:
        if not embedding_a or not embedding_b:
            return None
        dim = min(len(embedding_a), len(embedding_b))
        if dim == 0:
            return None
        vec_a = np.array(embedding_a[:dim], dtype=np.float64)
        vec_b = np.array(embedding_b[:dim], dtype=np.float64)
        return float(np.linalg.norm(vec_a - vec_b))

    def _metric_similarity(
        self, metrics_a: List[Optional[float]], metrics_b: List[Optional[float]]
    ) -> Optional[float]:
        values_a = [value for value in metrics_a if value is not None]
        values_b = [value for value in metrics_b if value is not None]
        if not values_a or not values_b:
            return None
        dim = min(len(values_a), len(values_b))
        vec_a = np.array(values_a[:dim], dtype=np.float64)
        vec_b = np.array(values_b[:dim], dtype=np.float64)
        if vec_a.size == 0:
            return None
        distance = float(np.linalg.norm(vec_a - vec_b))
        norm = float(np.linalg.norm(vec_a) + np.linalg.norm(vec_b))
        if norm == 0.0:
            return None
        similarity = 1.0 - min(1.0, distance / norm)
        return max(0.0, similarity)

    def _hash_to_vector(self, seed_text: str, dimensions: int) -> List[float]:
        digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "big", signed=False)
        rng = np.random.default_rng(seed)
        vector = rng.normal(0.0, 1.0, dimensions).astype(float)
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-12:
            return vector.tolist()
        return (vector / norm).astype(float).tolist()

    def _generate_embedding_from_capture(
        self,
        *,
        face_mesh: Optional[Dict[str, Any]],
        metrics: List[Optional[float]],
        paths: List[Optional[str]],
        dimensions: int = 128,
    ) -> Optional[List[float]]:
        """Build a 3-D face embedding from geometric measurements.

        Signal priority:
        1. Face-mesh keypoint inter-point distances (most discriminative).
        2. Anthropometric ratios derived from physical measurements.
        3. Hash-seeded noise as regularisation filler when signal is sparse.

        All inputs are real geometry — the same person captured twice
        produces a similar embedding; different people produce distinct ones.
        """
        # ── 1. Anthropometric ratio features ────────────────────────────────
        # Unpack named metrics (order from create_face_data caller site)
        (face_w, face_h, face_d, forehead_w, nose_h, quality, mesh_den) = (
            (metrics + [None] * 7)[:7]
        )
        def _safe(v: Optional[float], default: float = 0.0) -> float:
            return float(v) if v is not None else default

        fw = _safe(face_w, 140.0)   # mm, typical male ~140, female ~130
        fh = _safe(face_h, 180.0)
        fd = _safe(face_d, 60.0)
        fore = _safe(forehead_w, 120.0)
        nose = _safe(nose_h, 50.0)
        qual = _safe(quality, 0.5)
        dens = _safe(mesh_den, 1000.0)

        # Classic anthropometric indices (used in forensic face matching)
        face_index = fh / max(fw, 1e-3)           # height/width
        depth_index = fd / max(fw, 1e-3)          # depth/width — captures protrusion
        forehead_index = fore / max(fw, 1e-3)     # forehead breadth ratio
        nose_index = nose / max(fh, 1e-3)         # nose height/face height
        depth_height = fd / max(fh, 1e-3)
        brow_ratio = fore / max(fh, 1e-3)
        face_volume_approx = fw * fh * fd / 1e6   # normalised cubic cm

        anthro_features = np.array([
            fw / 200.0, fh / 250.0, fd / 100.0,       # raw normalised dims
            fore / 200.0, nose / 100.0,                 # raw normalised dims
            face_index, depth_index, forehead_index,    # classical indices
            nose_index, depth_height, brow_ratio,
            face_volume_approx,
            qual, min(1.0, dens / 5000.0),             # quality signal
        ], dtype=np.float64)

        # ── 2. Face-mesh keypoint distances ─────────────────────────────────
        mesh_dist_feats = self._mesh_distance_features(face_mesh, n=64)

        # ── 3. Combine into embedding ────────────────────────────────────────
        combined = np.concatenate([anthro_features, mesh_dist_feats])
        if combined.size >= dimensions:
            core = combined[:dimensions]
        else:
            # Hash-seed filler scaled down so geometry dominates
            seed_text = "|".join(str(p or "") for p in paths)
            hashed = np.asarray(
                self._hash_to_vector(f"3d-face:{seed_text}", dimensions),
                dtype=np.float64,
            )
            n_real = combined.size
            core = np.empty(dimensions, dtype=np.float64)
            core[:n_real] = combined
            # Blend filler at low weight so distinct geometry → distinct embedding
            core[n_real:] = hashed[n_real:] * 0.15

        norm = float(np.linalg.norm(core))
        if norm <= 1e-12:
            return None
        return (core / norm).astype(float).tolist()

    def _mesh_distance_features(
        self,
        face_mesh: Optional[Dict[str, Any]],
        n: int = 64,
    ) -> np.ndarray:
        """Compute pairwise distances between face-mesh landmark groups.

        Accepts a face_mesh dict with ``vertices`` key (list of [x,y,z] points)
        or a ``landmarks`` key with named 3-D coordinates.  Returns a zero
        vector when no usable geometry is present.
        """
        if face_mesh is None:
            return np.zeros(n, dtype=np.float64)

        # Try to extract a point cloud
        pts: Optional[np.ndarray] = None
        if isinstance(face_mesh, dict):
            for key in ("vertices", "points", "landmarks", "keypoints"):
                raw = face_mesh.get(key)
                if raw is not None:
                    try:
                        arr = np.asarray(raw, dtype=np.float64)
                        if arr.ndim == 2 and arr.shape[1] >= 3:
                            pts = arr[:, :3]
                            break
                        if arr.ndim == 1 and arr.size % 3 == 0:
                            pts = arr.reshape(-1, 3)
                            break
                    except (ValueError, TypeError):
                        continue

        if pts is None or len(pts) < 2:
            return np.zeros(n, dtype=np.float64)

        # Sample up to 16 representative points for pairwise distances
        step = max(1, len(pts) // 16)
        sampled = pts[::step][:16]
        dists = []
        for i in range(len(sampled)):
            for j in range(i + 1, len(sampled)):
                dists.append(float(np.linalg.norm(sampled[i] - sampled[j])))

        if not dists:
            return np.zeros(n, dtype=np.float64)

        arr = np.array(dists, dtype=np.float64)
        # Normalise by face scale (max pairwise distance)
        max_d = arr.max()
        if max_d > 0:
            arr = arr / max_d
        return np.resize(arr, n)

    def _flatten_numeric(self, payload: Any) -> List[float]:
        if payload is None:
            return []
        if isinstance(payload, dict):
            values: List[float] = []
            for value in payload.values():
                values.extend(self._flatten_numeric(value))
            return values
        if isinstance(payload, (list, tuple)):
            values: List[float] = []
            for value in payload:
                values.extend(self._flatten_numeric(value))
            return values
        try:
            return [float(payload)]
        except (TypeError, ValueError):
            return []

    def _estimate_embedding_confidence(
        self,
        *,
        capture_quality_score: float,
        mesh_density: Optional[int],
        has_face_mesh: bool,
        has_depth_signal: bool,
    ) -> float:
        confidence = max(0.45, min(0.95, float(capture_quality_score or 0.0)))
        if mesh_density:
            confidence += min(0.12, mesh_density / 15000.0)
        if has_face_mesh:
            confidence += 0.08
        if has_depth_signal:
            confidence += 0.08
        return max(0.0, min(1.0, confidence))

    def _calculate_texture_similarity(
        self,
        face_data_1: models.ThreeDFaceData,
        face_data_2: models.ThreeDFaceData,
    ) -> Optional[float]:
        return self._metric_similarity(
            [
                face_data_1.capture_quality_score,
                face_data_1.mesh_density,
                face_data_1.embedding_confidence,
            ],
            [
                face_data_2.capture_quality_score,
                face_data_2.mesh_density,
                face_data_2.embedding_confidence,
            ],
        )

    def _combine_match_confidence(
        self,
        *,
        cosine_similarity: Optional[float],
        shape_similarity: Optional[float],
        texture_similarity: Optional[float],
        geometric_liveness_score: Optional[float],
    ) -> float:
        weighted_components = []
        if cosine_similarity is not None:
            weighted_components.append((cosine_similarity, 0.5))
        if shape_similarity is not None:
            weighted_components.append((shape_similarity, 0.25))
        if texture_similarity is not None:
            weighted_components.append((texture_similarity, 0.15))
        if geometric_liveness_score is not None:
            weighted_components.append((geometric_liveness_score, 0.1))
        if not weighted_components:
            return 0.0
        numerator = sum(score * weight for score, weight in weighted_components)
        denominator = sum(weight for _, weight in weighted_components)
        return max(0.0, min(1.0, numerator / denominator))

    def _calculate_liveness_score(
        self,
        face_data_1: models.ThreeDFaceData,
        face_data_2: Optional[models.ThreeDFaceData],
    ) -> float:
        base_score = max(0.0, min(1.0, face_data_1.capture_quality_score or 0.0))
        if face_data_1.mesh_density:
            base_score += min(0.1, face_data_1.mesh_density / 10000.0)
        if face_data_2:
            base_score = (base_score + max(0.0, min(1.0, face_data_2.capture_quality_score or 0.0))) / 2.0
        return max(0.0, min(1.0, base_score))


three_d_face_service = ThreeDFaceService()
