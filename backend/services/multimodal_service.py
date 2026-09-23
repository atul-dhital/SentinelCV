"""Multimodal learning service (US-FUT-001).

Manages fusion configurations and stores multimodal embeddings across
face, audio, and text modalities.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Dict, List, Optional
from uuid import UUID

import numpy as np
from sqlalchemy.orm import Session

from models import models
from services import visitor_service

logger = logging.getLogger(__name__)

_DEFAULT_WEIGHTS: Dict[str, float] = {
    "face": 0.6,
    "audio": 0.2,
    "text": 0.1,
    "sensor": 0.1,
}


class MultimodalService:
    """Service for multimodal embedding storage and comparison."""

    def get_fusion_config(
        self, db: Session, organization_id: UUID
    ) -> Optional[models.MultimodalFusionConfig]:
        """Fetch the latest fusion config for an organization.

        Args:
            db: Database session
            organization_id: Organization UUID

        Returns:
            Latest fusion config or None if missing.
        """
        return (
            db.query(models.MultimodalFusionConfig)
            .filter(models.MultimodalFusionConfig.organization_id == organization_id)
            .order_by(models.MultimodalFusionConfig.created_at.desc())
            .first()
        )

    def upsert_fusion_config(
        self,
        db: Session,
        organization_id: UUID,
        face_weight: float,
        audio_weight: float,
        text_weight: float,
        sensor_weight: float,
        fusion_strategy: str,
        fusion_threshold: float,
        require_face: bool,
        require_audio: bool,
        require_text: bool,
    ) -> models.MultimodalFusionConfig:
        """Create or update a fusion configuration.

        Args:
            db: Database session
            organization_id: Organization UUID
            face_weight: Weight for face embeddings
            audio_weight: Weight for audio embeddings
            text_weight: Weight for text embeddings
            sensor_weight: Weight for sensor data
            fusion_strategy: Strategy name (weighted_mean, attention, mlp)
            fusion_threshold: Confidence threshold
            require_face: Whether face embeddings are required
            require_audio: Whether audio embeddings are required
            require_text: Whether text embeddings are required

        Returns:
            Persisted fusion config.
        """
        weights = self._normalize_weights(
            face_weight=face_weight,
            audio_weight=audio_weight,
            text_weight=text_weight,
            sensor_weight=sensor_weight,
        )
        config = self.get_fusion_config(db, organization_id)
        if config is None:
            config = models.MultimodalFusionConfig(
                organization_id=organization_id,
            )
            db.add(config)

        config.face_weight = weights["face"]
        config.audio_weight = weights["audio"]
        config.text_weight = weights["text"]
        config.sensor_weight = weights["sensor"]
        config.fusion_strategy = fusion_strategy
        config.fusion_threshold = fusion_threshold
        config.require_face = require_face
        config.require_audio = require_audio
        config.require_text = require_text

        db.commit()
        db.refresh(config)
        return config

    def ensure_fusion_config(
        self, db: Session, organization_id: UUID
    ) -> models.MultimodalFusionConfig:
        """Ensure a fusion config exists for the organization."""
        config = self.get_fusion_config(db, organization_id)
        if config is not None:
            return config
        return self.upsert_fusion_config(
            db,
            organization_id=organization_id,
            face_weight=_DEFAULT_WEIGHTS["face"],
            audio_weight=_DEFAULT_WEIGHTS["audio"],
            text_weight=_DEFAULT_WEIGHTS["text"],
            sensor_weight=_DEFAULT_WEIGHTS["sensor"],
            fusion_strategy="weighted_mean",
            fusion_threshold=0.7,
            require_face=True,
            require_audio=False,
            require_text=False,
        )

    def create_multimodal_embedding(
        self,
        db: Session,
        organization_id: UUID,
        visitor_id: UUID,
        detection_log_id: Optional[UUID],
        face_embedding: Optional[List[float]],
        audio_embedding: Optional[List[float]],
        text_embedding: Optional[List[float]],
        sensor_data: Optional[Dict[str, Any]],
        embedding_model_version: str,
        face_confidence: Optional[float],
        audio_confidence: Optional[float],
        text_confidence: Optional[float],
        sensor_confidence: Optional[float],
    ) -> models.MultimodalEmbedding:
        """Create a multimodal embedding record.

        Args:
            db: Database session
            organization_id: Organization UUID
            visitor_id: Visitor UUID
            detection_log_id: Optional detection log UUID
            face_embedding: Face embedding vector
            audio_embedding: Audio embedding vector
            text_embedding: Text embedding vector
            sensor_data: Optional sensor metadata
            embedding_model_version: Model version identifier
            face_confidence: Optional face confidence score
            audio_confidence: Optional audio confidence score
            text_confidence: Optional text confidence score
            sensor_confidence: Optional sensor confidence score

        Returns:
            Persisted MultimodalEmbedding.
        """
        visitor = db.query(models.Visitor).filter(
            models.Visitor.id == visitor_id,
            models.Visitor.organization_id == organization_id,
        ).first()
        if visitor is None:
            raise ValueError("Visitor not found")

        detection_log = self._get_detection_log(db, detection_log_id, organization_id)

        config = self.ensure_fusion_config(db, organization_id)
        if config.require_face and face_embedding is None:
            raise ValueError("Face embedding required by fusion policy")
        if config.require_audio and audio_embedding is None:
            raise ValueError("Audio embedding required by fusion policy")
        if config.require_text and text_embedding is None:
            raise ValueError("Text embedding required by fusion policy")

        parsed_face = self._coerce_embedding(face_embedding, "face")
        parsed_audio = self._coerce_embedding(audio_embedding, "audio")
        parsed_text = self._coerce_embedding(text_embedding, "text")

        stored_face = (
            visitor_service.serialize_embedding_for_storage(parsed_face)
            if parsed_face is not None
            else None
        )
        stored_audio = (
            visitor_service.serialize_embedding_for_storage(parsed_audio)
            if parsed_audio is not None
            else None
        )
        stored_text = (
            visitor_service.serialize_embedding_for_storage(parsed_text)
            if parsed_text is not None
            else None
        )

        fusion_score = self._calculate_fusion_score(
            config=config,
            face_present=parsed_face is not None,
            audio_present=parsed_audio is not None,
            text_present=parsed_text is not None,
            sensor_present=bool(sensor_data),
            face_confidence=face_confidence,
            audio_confidence=audio_confidence,
            text_confidence=text_confidence,
            sensor_confidence=sensor_confidence,
        )

        record = models.MultimodalEmbedding(
            visitor_id=visitor_id,
            detection_log_id=detection_log.id if detection_log else None,
            face_embedding=stored_face,
            audio_embedding=stored_audio,
            text_embedding=stored_text,
            sensor_data=sensor_data or {},
            fusion_score=fusion_score,
            embedding_model_version=embedding_model_version,
            audio_present=parsed_audio is not None,
            text_present=parsed_text is not None,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def get_multimodal_embedding(
        self, db: Session, organization_id: UUID, embedding_id: UUID
    ) -> Optional[models.MultimodalEmbedding]:
        """Fetch a multimodal embedding by ID with organization scoping."""
        return (
            db.query(models.MultimodalEmbedding)
            .join(models.Visitor, models.MultimodalEmbedding.visitor_id == models.Visitor.id)
            .filter(models.MultimodalEmbedding.id == embedding_id)
            .filter(models.Visitor.organization_id == organization_id)
            .first()
        )

    def create_audio_features(
        self,
        db: Session,
        organization_id: UUID,
        visitor_id: UUID,
        detection_log_id: Optional[UUID],
        mfcc_features: Optional[List[float]],
        spectral_energy: Optional[float],
        zero_crossing_rate: Optional[float],
        voice_confidence: float,
        pitch_frequency: Optional[float],
        audio_duration_ms: Optional[int],
    ) -> models.AudioFeature:
        """Store audio features for a visitor."""
        visitor = db.query(models.Visitor).filter(
            models.Visitor.id == visitor_id,
            models.Visitor.organization_id == organization_id,
        ).first()
        if visitor is None:
            raise ValueError("Visitor not found")

        detection_log = self._get_detection_log(db, detection_log_id, organization_id)
        parsed_mfcc = self._coerce_embedding(mfcc_features, "mfcc")

        record = models.AudioFeature(
            visitor_id=visitor_id,
            detection_log_id=detection_log.id if detection_log else None,
            mfcc_features=(
                visitor_service.serialize_embedding_for_storage(parsed_mfcc)
                if parsed_mfcc is not None
                else None
            ),
            spectral_energy=spectral_energy,
            zero_crossing_rate=zero_crossing_rate,
            voice_confidence=voice_confidence,
            pitch_frequency=pitch_frequency,
            audio_duration_ms=audio_duration_ms,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def create_text_bio_features(
        self,
        db: Session,
        organization_id: UUID,
        visitor_id: UUID,
        name: Optional[str],
        department: Optional[str],
        position: Optional[str],
        phone_number: Optional[str],
        email: Optional[str],
        notes: Optional[str],
        text_embedding: Optional[List[float]],
        embedding_confidence: float,
    ) -> models.TextBioFeature:
        """Store text/bio features for a visitor."""
        visitor = db.query(models.Visitor).filter(
            models.Visitor.id == visitor_id,
            models.Visitor.organization_id == organization_id,
        ).first()
        if visitor is None:
            raise ValueError("Visitor not found")

        parsed_text = self._coerce_embedding(text_embedding, "text")

        record = models.TextBioFeature(
            visitor_id=visitor_id,
            name=name,
            department=department,
            position=position,
            phone_number=phone_number,
            email=email,
            notes=notes,
            text_embedding=(
                visitor_service.serialize_embedding_for_storage(parsed_text)
                if parsed_text is not None
                else None
            ),
            embedding_confidence=embedding_confidence,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def build_visitor_multimodal_embedding(
        self,
        db: Session,
        organization_id: UUID,
        visitor_id: UUID,
        detection_log_id: Optional[UUID] = None,
        sensor_data: Optional[Dict[str, Any]] = None,
        embedding_model_version: str = "auto-fused-v1",
    ) -> models.MultimodalEmbedding:
        """Create a multimodal embedding from the latest stored visitor modalities."""
        visitor = db.query(models.Visitor).filter(
            models.Visitor.id == visitor_id,
            models.Visitor.organization_id == organization_id,
        ).first()
        if visitor is None:
            raise ValueError("Visitor not found")

        latest_face = db.query(models.FaceData).filter(
            models.FaceData.visitor_id == visitor_id,
        ).order_by(models.FaceData.is_primary.desc(), models.FaceData.created_at.desc()).first()
        latest_audio = db.query(models.AudioFeature).filter(
            models.AudioFeature.visitor_id == visitor_id,
        ).order_by(models.AudioFeature.created_at.desc()).first()
        latest_text = db.query(models.TextBioFeature).filter(
            models.TextBioFeature.visitor_id == visitor_id,
        ).order_by(models.TextBioFeature.updated_at.desc(), models.TextBioFeature.created_at.desc()).first()

        face_embedding = visitor_service._parse_embedding_payload(latest_face.embedding) if latest_face else None
        audio_embedding = self._derive_audio_embedding(latest_audio)
        text_embedding = self._derive_text_embedding(visitor, latest_text)

        if face_embedding is None and audio_embedding is None and text_embedding is None:
            raise ValueError("No visitor modalities available to build multimodal embedding")

        enriched_sensor_data = dict(sensor_data or {})
        enriched_sensor_data["auto_fused"] = True
        enriched_sensor_data["modalities"] = {
            "face": face_embedding is not None,
            "audio": audio_embedding is not None,
            "text": text_embedding is not None,
        }

        return self.create_multimodal_embedding(
            db=db,
            organization_id=organization_id,
            visitor_id=visitor_id,
            detection_log_id=detection_log_id,
            face_embedding=face_embedding,
            audio_embedding=audio_embedding,
            text_embedding=text_embedding,
            sensor_data=enriched_sensor_data,
            embedding_model_version=embedding_model_version,
            face_confidence=float(latest_face.quality_score or 0.8) if latest_face else None,
            audio_confidence=float(latest_audio.voice_confidence or 0.65) if latest_audio else None,
            text_confidence=float(latest_text.embedding_confidence or 0.6) if latest_text else (0.55 if text_embedding else None),
            sensor_confidence=0.65 if enriched_sensor_data else None,
        )

    def get_visitor_multimodal_profile(
        self,
        db: Session,
        organization_id: UUID,
        visitor_id: UUID,
    ) -> Dict[str, Any]:
        """Return the latest multimodal profile summary for a visitor."""
        visitor = db.query(models.Visitor).filter(
            models.Visitor.id == visitor_id,
            models.Visitor.organization_id == organization_id,
        ).first()
        if visitor is None:
            raise ValueError("Visitor not found")

        latest_embedding = db.query(models.MultimodalEmbedding).filter(
            models.MultimodalEmbedding.visitor_id == visitor_id,
        ).order_by(models.MultimodalEmbedding.created_at.desc()).first()
        latest_face = db.query(models.FaceData).filter(
            models.FaceData.visitor_id == visitor_id,
        ).order_by(models.FaceData.is_primary.desc(), models.FaceData.created_at.desc()).first()
        latest_audio = db.query(models.AudioFeature).filter(
            models.AudioFeature.visitor_id == visitor_id,
        ).order_by(models.AudioFeature.created_at.desc()).first()
        latest_text = db.query(models.TextBioFeature).filter(
            models.TextBioFeature.visitor_id == visitor_id,
        ).order_by(models.TextBioFeature.updated_at.desc(), models.TextBioFeature.created_at.desc()).first()

        return {
            "visitor_id": str(visitor.id),
            "visitor_name": visitor.name,
            "latest_embedding_id": str(latest_embedding.id) if latest_embedding else None,
            "fusion_score": float(latest_embedding.fusion_score or 0.0) if latest_embedding else 0.0,
            "modalities_present": {
                "face": latest_face is not None,
                "audio": latest_audio is not None,
                "text": latest_text is not None or bool(visitor.name or visitor.email or visitor.notes or visitor.description),
            },
            "modality_counts": {
                "face": db.query(models.FaceData).filter(models.FaceData.visitor_id == visitor_id).count(),
                "audio": db.query(models.AudioFeature).filter(models.AudioFeature.visitor_id == visitor_id).count(),
                "text": db.query(models.TextBioFeature).filter(models.TextBioFeature.visitor_id == visitor_id).count(),
                "multimodal": db.query(models.MultimodalEmbedding).filter(models.MultimodalEmbedding.visitor_id == visitor_id).count(),
            },
            "latest_modalities": {
                "face_quality": float(latest_face.quality_score or 0.0) if latest_face else None,
                "voice_confidence": float(latest_audio.voice_confidence or 0.0) if latest_audio else None,
                "text_confidence": float(latest_text.embedding_confidence or 0.0) if latest_text else None,
            },
            "derived_modalities": [
                name
                for name, present in {
                    "audio": latest_audio is None,
                    "text": latest_text is None,
                }.items()
                if present
            ],
        }

    def compare_embeddings(
        self,
        db: Session,
        organization_id: UUID,
        embedding_a_id: UUID,
        embedding_b_id: UUID,
        config_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Compare two multimodal embeddings using weighted cosine similarity."""
        embedding_a = self.get_multimodal_embedding(db, organization_id, embedding_a_id)
        embedding_b = self.get_multimodal_embedding(db, organization_id, embedding_b_id)
        if embedding_a is None or embedding_b is None:
            raise ValueError("Multimodal embedding not found")

        config = self.ensure_fusion_config(db, organization_id)
        if config_id is not None:
            config_override = db.query(models.MultimodalFusionConfig).filter(
                models.MultimodalFusionConfig.id == config_id,
                models.MultimodalFusionConfig.organization_id == organization_id,
            ).first()
            if config_override is not None:
                config = config_override

        weights = self._normalize_weights(
            face_weight=config.face_weight,
            audio_weight=config.audio_weight,
            text_weight=config.text_weight,
            sensor_weight=config.sensor_weight,
        )

        similarities: Dict[str, float] = {}
        face_sim = self._cosine_similarity(embedding_a.face_embedding, embedding_b.face_embedding)
        if face_sim is not None:
            similarities["face"] = face_sim

        audio_sim = self._cosine_similarity(embedding_a.audio_embedding, embedding_b.audio_embedding)
        if audio_sim is not None:
            similarities["audio"] = audio_sim

        text_sim = self._cosine_similarity(embedding_a.text_embedding, embedding_b.text_embedding)
        if text_sim is not None:
            similarities["text"] = text_sim

        if not similarities:
            raise ValueError("No overlapping modalities to compare")

        weighted_sum = 0.0
        weight_total = 0.0
        for modality, score in similarities.items():
            weight = weights.get(modality, 0.0)
            weighted_sum += weight * score
            weight_total += weight

        overall = weighted_sum / weight_total if weight_total > 0 else 0.0

        return {
            "overall_similarity": overall,
            "modalities": similarities,
            "weights": weights,
            "fusion_strategy": config.fusion_strategy,
        }

    def infer_identity(
        self,
        db: Session,
        organization_id: UUID,
        *,
        face_embedding: Optional[List[float]],
        audio_embedding: Optional[List[float]],
        text_embedding: Optional[List[float]],
        text_hint: Optional[str],
        sensor_data: Optional[Dict[str, Any]],
        candidate_visitor_ids: Optional[List[UUID]],
        top_k: int,
    ) -> Dict[str, Any]:
        """Infer best visitor candidates from multimodal probe signals."""
        config = self.ensure_fusion_config(db, organization_id)

        probe_face = self._coerce_embedding(face_embedding, "face")
        probe_audio = self._coerce_embedding(audio_embedding, "audio")
        probe_text = self._coerce_embedding(text_embedding, "text")
        if probe_text is None and text_hint:
            probe_text = self._normalize_vector(
                self._hash_to_vector(f"probe-text:{text_hint.lower().strip()}", 256),
                dimensions=256,
            )

        if config.require_face and probe_face is None:
            raise ValueError("Face embedding required by fusion policy")
        if config.require_audio and probe_audio is None:
            raise ValueError("Audio embedding required by fusion policy")
        if config.require_text and probe_text is None:
            raise ValueError("Text embedding required by fusion policy")

        query_modalities = [
            name
            for name, value in {
                "face": probe_face,
                "audio": probe_audio,
                "text": probe_text,
                "sensor": sensor_data if sensor_data else None,
            }.items()
            if value is not None
        ]
        if not query_modalities:
            raise ValueError("At least one probe modality is required for inference")

        weights = self._normalize_weights(
            face_weight=config.face_weight,
            audio_weight=config.audio_weight,
            text_weight=config.text_weight,
            sensor_weight=config.sensor_weight,
        )

        candidate_limit = max(
            top_k,
            min(int(os.getenv("MULTIMODAL_INFER_CANDIDATE_LIMIT", "250")), 2000),
        )
        visitors_query = db.query(models.Visitor).filter(
            models.Visitor.organization_id == organization_id,
            models.Visitor.is_active == True,
        )
        if candidate_visitor_ids:
            visitors_query = visitors_query.filter(models.Visitor.id.in_(candidate_visitor_ids))

        visitors = visitors_query.order_by(models.Visitor.created_at.desc()).limit(candidate_limit).all()

        ranked: List[Dict[str, Any]] = []
        for visitor in visitors:
            candidate = self._load_candidate_modalities(
                db=db,
                visitor=visitor,
            )
            if candidate is None:
                continue

            modality_scores: Dict[str, float] = {}
            face_similarity = self._cosine_similarity(probe_face, candidate.get("face"))
            if face_similarity is not None:
                modality_scores["face"] = face_similarity

            audio_similarity = self._cosine_similarity(probe_audio, candidate.get("audio"))
            if audio_similarity is not None:
                modality_scores["audio"] = audio_similarity

            text_similarity = self._cosine_similarity(probe_text, candidate.get("text"))
            if text_similarity is not None:
                modality_scores["text"] = text_similarity

            sensor_similarity = self._sensor_similarity(sensor_data, candidate.get("sensor"))
            if sensor_similarity is not None:
                modality_scores["sensor"] = sensor_similarity

            if not modality_scores:
                continue

            weighted_sum = 0.0
            active_weight = 0.0
            for modality, score in modality_scores.items():
                weight = float(weights.get(modality, 0.0))
                weighted_sum += weight * float(score)
                active_weight += weight
            if active_weight <= 0.0:
                continue

            weighted_similarity = weighted_sum / active_weight
            modality_coverage = float(len(modality_scores)) / float(max(len(query_modalities), 1))
            final_score = min(1.0, max(0.0, (0.82 * weighted_similarity) + (0.18 * modality_coverage)))

            ranked.append(
                {
                    "visitor_id": str(visitor.id),
                    "visitor_name": visitor.name,
                    "score": round(final_score, 4),
                    "modality_coverage": round(modality_coverage, 4),
                    "modalities": {
                        key: round(value, 4)
                        for key, value in modality_scores.items()
                    },
                    "source": candidate.get("source", "derived"),
                }
            )

        ranked.sort(key=lambda item: item["score"], reverse=True)
        top_candidates = ranked[: max(1, top_k)]
        threshold = float(config.fusion_threshold or 0.7)

        for candidate in top_candidates:
            candidate["meets_threshold"] = bool(candidate["score"] >= threshold)

        top_candidate = top_candidates[0] if top_candidates else None
        return {
            "match_found": bool(top_candidate and top_candidate["score"] >= threshold),
            "threshold": threshold,
            "fusion_strategy": config.fusion_strategy,
            "query_modalities": query_modalities,
            "top_candidate": top_candidate,
            "candidates": top_candidates,
        }

    def _load_candidate_modalities(
        self,
        db: Session,
        visitor: models.Visitor,
    ) -> Optional[Dict[str, Any]]:
        latest_embedding = db.query(models.MultimodalEmbedding).filter(
            models.MultimodalEmbedding.visitor_id == visitor.id,
        ).order_by(models.MultimodalEmbedding.created_at.desc()).first()

        face_vector = (
            visitor_service._parse_embedding_payload(latest_embedding.face_embedding)
            if latest_embedding is not None
            else None
        )
        audio_vector = (
            visitor_service._parse_embedding_payload(latest_embedding.audio_embedding)
            if latest_embedding is not None
            else None
        )
        text_vector = (
            visitor_service._parse_embedding_payload(latest_embedding.text_embedding)
            if latest_embedding is not None
            else None
        )
        sensor_payload = (
            dict(latest_embedding.sensor_data or {})
            if latest_embedding is not None and isinstance(latest_embedding.sensor_data, dict)
            else {}
        )

        source = "stored_multimodal_embedding" if latest_embedding is not None else "derived_modalities"

        if face_vector is None:
            latest_face = db.query(models.FaceData).filter(
                models.FaceData.visitor_id == visitor.id,
            ).order_by(models.FaceData.is_primary.desc(), models.FaceData.created_at.desc()).first()
            if latest_face is not None:
                face_vector = visitor_service._parse_embedding_payload(latest_face.embedding)

        if audio_vector is None:
            latest_audio = db.query(models.AudioFeature).filter(
                models.AudioFeature.visitor_id == visitor.id,
            ).order_by(models.AudioFeature.created_at.desc()).first()
            audio_vector = self._derive_audio_embedding(latest_audio)

        if text_vector is None:
            latest_text = db.query(models.TextBioFeature).filter(
                models.TextBioFeature.visitor_id == visitor.id,
            ).order_by(models.TextBioFeature.updated_at.desc(), models.TextBioFeature.created_at.desc()).first()
            text_vector = self._derive_text_embedding(visitor, latest_text)

        if face_vector is None and audio_vector is None and text_vector is None and not sensor_payload:
            return None

        return {
            "face": face_vector,
            "audio": audio_vector,
            "text": text_vector,
            "sensor": sensor_payload,
            "source": source,
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

    def _coerce_embedding(
        self, embedding: Optional[List[float]], label: str
    ) -> Optional[List[float]]:
        if embedding is None:
            return None
        parsed = visitor_service._parse_embedding_payload(embedding)
        if parsed is None:
            raise ValueError(f"Invalid {label} embedding payload")
        return parsed

    def _normalize_weights(
        self,
        face_weight: float,
        audio_weight: float,
        text_weight: float,
        sensor_weight: float,
    ) -> Dict[str, float]:
        values = {
            "face": max(0.0, float(face_weight)),
            "audio": max(0.0, float(audio_weight)),
            "text": max(0.0, float(text_weight)),
            "sensor": max(0.0, float(sensor_weight)),
        }
        total = sum(values.values())
        if total <= 0.0:
            raise ValueError("Fusion weights must sum to a positive value")
        return {key: value / total for key, value in values.items()}

    def _hash_to_vector(self, seed_text: str, dimensions: int) -> List[float]:
        digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "big", signed=False)
        rng = np.random.default_rng(seed)
        vector = rng.normal(0.0, 1.0, dimensions).astype(float)
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-12:
            return vector.tolist()
        return (vector / norm).astype(float).tolist()

    def _normalize_vector(self, values: List[float], dimensions: Optional[int] = None) -> List[float]:
        if not values:
            return []
        vector = np.asarray(values, dtype=np.float64)
        if dimensions is not None and vector.size != dimensions:
            vector = np.resize(vector, dimensions)
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-12:
            return vector.astype(float).tolist()
        return (vector / norm).astype(float).tolist()

    def _derive_audio_embedding(
        self,
        audio_feature: Optional[models.AudioFeature],
        *,
        dimensions: int = 128,
    ) -> Optional[List[float]]:
        if audio_feature is None:
            return None

        mfcc = visitor_service._parse_embedding_payload(audio_feature.mfcc_features) or []
        if mfcc:
            base = self._normalize_vector(mfcc, dimensions=dimensions)
        else:
            seed = "|".join(
                str(value or "")
                for value in (
                    audio_feature.spectral_energy,
                    audio_feature.zero_crossing_rate,
                    audio_feature.pitch_frequency,
                    audio_feature.audio_duration_ms,
                )
            )
            base = self._hash_to_vector(f"audio:{seed}", dimensions)

        if base:
            adjustments = np.asarray(base, dtype=np.float64)
            adjustments[0] = float(audio_feature.spectral_energy or 0.0)
            adjustments[1] = float(audio_feature.zero_crossing_rate or 0.0)
            adjustments[2] = float((audio_feature.pitch_frequency or 0.0) / 500.0)
            adjustments[3] = float((audio_feature.audio_duration_ms or 0.0) / 5000.0)
            return self._normalize_vector(adjustments.tolist(), dimensions=dimensions)
        return None

    def _derive_text_embedding(
        self,
        visitor: models.Visitor,
        text_feature: Optional[models.TextBioFeature],
        *,
        dimensions: int = 256,
    ) -> Optional[List[float]]:
        if text_feature and text_feature.text_embedding is not None:
            parsed = visitor_service._parse_embedding_payload(text_feature.text_embedding)
            if parsed:
                return self._normalize_vector(parsed, dimensions=dimensions)

        text_parts = [
            getattr(text_feature, "name", None) if text_feature else visitor.name,
            getattr(text_feature, "department", None) if text_feature else None,
            getattr(text_feature, "position", None) if text_feature else None,
            getattr(text_feature, "email", None) if text_feature else visitor.email,
            getattr(text_feature, "notes", None) if text_feature else visitor.notes,
            visitor.description,
        ]
        raw_text = " | ".join(part.strip() for part in text_parts if isinstance(part, str) and part.strip())
        if not raw_text:
            return None

        vector = self._hash_to_vector(f"text:{raw_text.lower()}", dimensions)
        adjustments = np.asarray(vector, dtype=np.float64)
        adjustments[0] = min(len(raw_text) / 256.0, 1.0)
        adjustments[1] = min(len(raw_text.split()) / 64.0, 1.0)
        adjustments[2] = 1.0 if visitor.is_known else 0.0
        return self._normalize_vector(adjustments.tolist(), dimensions=dimensions)

    def _calculate_fusion_score(
        self,
        config: models.MultimodalFusionConfig,
        face_present: bool,
        audio_present: bool,
        text_present: bool,
        sensor_present: bool,
        face_confidence: Optional[float],
        audio_confidence: Optional[float],
        text_confidence: Optional[float],
        sensor_confidence: Optional[float],
    ) -> float:
        weights = self._normalize_weights(
            face_weight=config.face_weight,
            audio_weight=config.audio_weight,
            text_weight=config.text_weight,
            sensor_weight=config.sensor_weight,
        )
        modalities = {
            "face": (face_present, face_confidence),
            "audio": (audio_present, audio_confidence),
            "text": (text_present, text_confidence),
            "sensor": (sensor_present, sensor_confidence),
        }

        weighted_sum = 0.0
        weight_total = 0.0
        for name, (present, confidence) in modalities.items():
            if not present:
                continue
            weight = weights.get(name, 0.0)
            conf = 1.0 if confidence is None else max(0.0, min(1.0, float(confidence)))
            weighted_sum += weight * conf
            weight_total += weight

        if weight_total <= 0.0:
            return 0.0
        return weighted_sum / weight_total

    def _sensor_similarity(
        self,
        sensor_a: Optional[Dict[str, Any]],
        sensor_b: Optional[Dict[str, Any]],
    ) -> Optional[float]:
        if not isinstance(sensor_a, dict) or not isinstance(sensor_b, dict):
            return None

        flat_a = self._flatten_sensor(sensor_a)
        flat_b = self._flatten_sensor(sensor_b)
        if not flat_a or not flat_b:
            return None

        common_keys = sorted(set(flat_a.keys()) & set(flat_b.keys()))
        if not common_keys:
            return None

        scores: List[float] = []
        for key in common_keys:
            left = flat_a[key]
            right = flat_b[key]

            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                denominator = max(abs(float(left)), abs(float(right)), 1.0)
                score = 1.0 - (abs(float(left) - float(right)) / denominator)
                scores.append(max(0.0, min(1.0, score)))
                continue

            if isinstance(left, bool) and isinstance(right, bool):
                scores.append(1.0 if left == right else 0.0)
                continue

            scores.append(
                1.0
                if str(left).strip().lower() == str(right).strip().lower()
                else 0.0
            )

        if not scores:
            return None
        return float(sum(scores) / len(scores))

    def _flatten_sensor(
        self,
        payload: Dict[str, Any],
        prefix: str = "",
    ) -> Dict[str, Any]:
        flat: Dict[str, Any] = {}
        for key, value in payload.items():
            key_name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                flat.update(self._flatten_sensor(value, key_name))
            else:
                flat[key_name] = value
        return flat

    def _cosine_similarity(
        self, embedding_a: Any, embedding_b: Any
    ) -> Optional[float]:
        vec_a = visitor_service._parse_embedding_payload(embedding_a)
        vec_b = visitor_service._parse_embedding_payload(embedding_b)
        if not vec_a or not vec_b:
            return None
        dim = min(len(vec_a), len(vec_b))
        if dim == 0:
            return None
        a = np.array(vec_a[:dim], dtype=np.float64)
        b = np.array(vec_b[:dim], dtype=np.float64)
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom == 0.0:
            return None
        similarity = float(np.dot(a, b) / denom)
        return max(0.0, min(1.0, similarity))


multimodal_service = MultimodalService()
