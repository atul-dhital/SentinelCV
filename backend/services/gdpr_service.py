"""GDPR compliance workflows for export, deletion, consent, and retention."""

import json
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.orm import Session

from core.storage import storage
from models.models import (
    DataRetentionPolicy,
    DetectionLog,
    FaceData,
    GDPRRequest,
    Visitor,
    VisitorConsent,
    VisitorLog,
)
from schemas.schemas import GDPRRequestCreate, VisitorConsentCreate, DataRetentionPolicyCreate


DEFAULT_RETENTION_DAYS: Dict[str, int] = {
    "face_embeddings": 0,
    "face_images": 30,
    "logs": 90,
}
GDPR_EXPORT_DIR = "gdpr_exports"


class GDPRService:
    """Service for managing GDPR requests and retention-driven cleanup."""

    def get_visitor_for_org(
        self,
        db: Session,
        visitor_id: UUID,
        organization_id: UUID,
    ) -> Optional[Visitor]:
        return db.query(Visitor).filter(
            Visitor.id == visitor_id,
            Visitor.organization_id == organization_id,
        ).first()

    def gdpr_request_belongs_to_org(
        self,
        gdpr_request: GDPRRequest,
        organization_id: UUID,
    ) -> bool:
        visitor = gdpr_request.visitor
        # Use str() comparison to handle both SQLite StringUUID (str) and
        # PostgreSQL UUID (uuid.UUID) without a type mismatch.
        return bool(visitor and str(visitor.organization_id) == str(organization_id))

    def create_gdpr_request(
        self,
        db: Session,
        visitor_id: UUID,
        request_data: GDPRRequestCreate,
    ) -> GDPRRequest:
        """Create a GDPR request record."""
        gdpr_request = GDPRRequest(
            visitor_id=visitor_id,
            **request_data.model_dump(),
        )
        db.add(gdpr_request)
        db.commit()
        db.refresh(gdpr_request)
        return gdpr_request

    def get_gdpr_request(
        self,
        db: Session,
        request_id: UUID,
    ) -> Optional[GDPRRequest]:
        """Get GDPR request by ID."""
        return db.query(GDPRRequest).filter(GDPRRequest.id == request_id).first()

    def list_visitor_gdpr_requests(
        self,
        db: Session,
        visitor_id: UUID,
    ) -> List[GDPRRequest]:
        """Get all GDPR requests for a visitor."""
        return db.query(GDPRRequest).filter(
            GDPRRequest.visitor_id == visitor_id,
        ).order_by(GDPRRequest.request_date.desc()).all()

    def list_pending_gdpr_requests(
        self,
        db: Session,
        organization_id: UUID,
    ) -> List[GDPRRequest]:
        """Get pending GDPR requests for an organization."""
        return db.query(GDPRRequest).join(Visitor).filter(
            and_(
                Visitor.organization_id == organization_id,
                GDPRRequest.status.in_(("pending", "processing")),
            )
        ).order_by(GDPRRequest.request_date.desc()).all()

    async def process_data_export(
        self,
        db: Session,
        visitor_id: UUID,
    ) -> Optional[BytesIO]:
        """Generate an in-memory ZIP export for a visitor."""
        visitor = db.query(Visitor).filter(Visitor.id == visitor_id).first()
        if not visitor:
            return None

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            profile_data = {
                "id": str(visitor.id),
                "name": visitor.name,
                "email": visitor.email,
                "phone": visitor.phone,
                "created_at": visitor.created_at.isoformat() if visitor.created_at else None,
                "updated_at": visitor.updated_at.isoformat() if visitor.updated_at else None,
                "visitor_metadata": visitor.visitor_metadata or {},
                "is_known": bool(visitor.is_known),
                "is_active": bool(visitor.is_active),
            }
            zf.writestr("visitor_profile.json", json.dumps(profile_data, indent=2))

            face_data = db.query(FaceData).filter(
                FaceData.visitor_id == visitor_id,
            ).all()
            faces = [{
                "id": str(face.id),
                "image_url": face.image_url,
                "quality_score": face.quality_score,
                "face_angle": face.face_angle,
                "has_embedding": face.embedding is not None,
                "created_at": face.created_at.isoformat() if face.created_at else None,
            } for face in face_data]
            zf.writestr("face_data.json", json.dumps(faces, indent=2))

            # Include actual face image files so data subjects receive their
            # biometric data in a portable format (GDPR Art. 20).
            images_dir = "face_images/"
            for face in face_data:
                if not face.image_url:
                    continue
                try:
                    local_path = storage.ensure_local_file(face.image_url)
                    import os as _os
                    archive_name = images_dir + _os.path.basename(str(local_path))
                    with open(str(local_path), "rb") as img_f:
                        zf.writestr(archive_name, img_f.read())
                except (FileNotFoundError, RuntimeError, OSError):
                    # Image file missing — include a note but don't fail the export
                    pass

            detection_logs = db.query(DetectionLog).filter(
                DetectionLog.visitor_id == visitor_id,
            ).order_by(DetectionLog.timestamp.desc()).limit(250).all()
            detection_payload = [{
                "id": str(log.id),
                "confidence": log.confidence,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "identified": bool(log.identified),
                "face_image_path": log.face_image_path,
            } for log in detection_logs]
            zf.writestr("detection_logs.json", json.dumps(detection_payload, indent=2))

            visit_logs = db.query(VisitorLog).filter(
                VisitorLog.visitor_id == visitor_id,
            ).order_by(VisitorLog.timestamp.desc()).limit(250).all()
            visit_payload = [{
                "id": str(log.id),
                "camera_id": str(log.camera_id) if log.camera_id else None,
                "confidence": log.confidence,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "identified": bool(log.identified),
                "status": log.status,
                "face_image_path": log.face_image_path,
                "video_snippet_path": log.video_snippet_path,
            } for log in visit_logs]
            zf.writestr("visitor_logs.json", json.dumps(visit_payload, indent=2))

            consents = db.query(VisitorConsent).filter(
                VisitorConsent.visitor_id == visitor_id,
            ).all()
            consent_payload = [{
                "consent_type": consent.consent_type,
                "consent_given": consent.consent_given,
                "consent_date": consent.consent_date.isoformat() if consent.consent_date else None,
                "consent_withdrawn_date": (
                    consent.consent_withdrawn_date.isoformat()
                    if consent.consent_withdrawn_date else None
                ),
            } for consent in consents]
            zf.writestr("consent_records.json", json.dumps(consent_payload, indent=2))

        zip_buffer.seek(0)
        return zip_buffer

    async def complete_data_export_request(
        self,
        db: Session,
        gdpr_request: GDPRRequest,
        org_id: Optional[str] = None,
    ) -> Optional[GDPRRequest]:
        """Generate an export archive and mark the request completed.

        Archives are stored under ``gdpr_exports/{org_id}/{request_id}.zip``
        so that even an authenticated user from a different organization cannot
        access another org's archive via the UUID alone.
        """
        archive = await self.process_data_export(db, gdpr_request.visitor_id)
        if archive is None:
            return None

        if org_id is None:
            visitor = db.query(Visitor).filter(Visitor.id == gdpr_request.visitor_id).first()
            org_id = str(visitor.organization_id) if visitor else "orphaned"

        relative_path = f"{GDPR_EXPORT_DIR}/{org_id}/{gdpr_request.id}.zip"
        storage.save_file(
            relative_path,
            archive.getvalue(),
            content_type="application/zip",
        )

        now = datetime.now(timezone.utc)
        gdpr_request.status = "completed"
        gdpr_request.response_file_url = relative_path
        gdpr_request.completion_date = now
        gdpr_request.notes = self._append_note(
            gdpr_request.notes,
            f"{now.isoformat()} export archive generated at {relative_path}",
        )
        db.commit()
        db.refresh(gdpr_request)
        return gdpr_request

    async def process_data_deletion(
        self,
        db: Session,
        visitor_id: UUID,
    ) -> bool:
        """Start deletion workflow by immediately removing stored embeddings."""
        visitor = db.query(Visitor).filter(Visitor.id == visitor_id).first()
        if not visitor:
            return False

        now = datetime.now(timezone.utc)
        cleared_embeddings = self._clear_face_embeddings_for_visitor(db, visitor_id)
        visitor.is_active = False
        visitor.is_known = False
        visitor.last_detected_at = None

        requests = db.query(GDPRRequest).filter(
            and_(
                GDPRRequest.visitor_id == visitor_id,
                GDPRRequest.request_type == "data_deletion",
                GDPRRequest.status.in_(("pending", "processing")),
            )
        ).all()
        for gdpr_request in requests:
            gdpr_request.status = "processing"
            gdpr_request.completion_date = None
            gdpr_request.notes = self._append_note(
                gdpr_request.notes,
                (
                    f"{now.isoformat()} deletion workflow started; "
                    f"{cleared_embeddings} face embedding record(s) cleared immediately."
                ),
            )

        db.commit()
        return True

    def create_consent(
        self,
        db: Session,
        visitor_id: UUID,
        consent_data: VisitorConsentCreate,
    ) -> VisitorConsent:
        """Record visitor consent."""
        consent = VisitorConsent(
            visitor_id=visitor_id,
            **consent_data.model_dump(),
        )
        db.add(consent)
        db.commit()
        db.refresh(consent)
        return consent

    def get_visitor_consent(
        self,
        db: Session,
        visitor_id: UUID,
        consent_type: str,
    ) -> Optional[VisitorConsent]:
        """Get the latest consent record for a visitor and type."""
        return db.query(VisitorConsent).filter(
            and_(
                VisitorConsent.visitor_id == visitor_id,
                VisitorConsent.consent_type == consent_type,
            )
        ).order_by(VisitorConsent.consent_date.desc()).first()

    def withdraw_consent(
        self,
        db: Session,
        visitor_id: UUID,
        consent_type: str,
    ) -> bool:
        """Withdraw visitor consent for a type."""
        consent = self.get_visitor_consent(db, visitor_id, consent_type)
        if not consent:
            return False

        consent.consent_given = False
        consent.consent_withdrawn_date = datetime.now(timezone.utc)
        db.commit()
        return True

    def create_retention_policy(
        self,
        db: Session,
        organization_id: UUID,
        policy_data: DataRetentionPolicyCreate,
    ) -> DataRetentionPolicy:
        """Create or update a retention policy for an organization."""
        existing = db.query(DataRetentionPolicy).filter(
            DataRetentionPolicy.organization_id == organization_id,
            DataRetentionPolicy.data_type == policy_data.data_type,
        ).first()
        if existing:
            existing.retention_days = policy_data.retention_days
            existing.auto_delete_enabled = policy_data.auto_delete_enabled
            db.commit()
            db.refresh(existing)
            return existing

        policy = DataRetentionPolicy(
            organization_id=organization_id,
            **policy_data.model_dump(),
        )
        db.add(policy)
        db.commit()
        db.refresh(policy)
        return policy

    def get_retention_policy(
        self,
        db: Session,
        organization_id: UUID,
        data_type: str,
    ) -> Optional[DataRetentionPolicy]:
        """Get retention policy for a data type."""
        return db.query(DataRetentionPolicy).filter(
            and_(
                DataRetentionPolicy.organization_id == organization_id,
                DataRetentionPolicy.data_type == data_type,
            )
        ).first()

    def list_retention_policies(
        self,
        db: Session,
        organization_id: UUID,
    ) -> List[DataRetentionPolicy]:
        """List all retention policies for an organization."""
        return db.query(DataRetentionPolicy).filter(
            DataRetentionPolicy.organization_id == organization_id,
        ).all()

    async def cleanup_expired_data(
        self,
        db: Session,
        organization_id: UUID,
    ) -> Dict[str, int]:
        """Complete matured deletion requests using retention windows."""
        retention_days = self._retention_days_by_type(db, organization_id)
        now = datetime.now(timezone.utc)
        stats = {
            "face_embeddings": 0,
            "face_images": 0,
            "visitor_logs_anonymized": 0,
            "detection_logs_anonymized": 0,
            "face_data_deleted": 0,
            "consents_deleted": 0,
            "visitors_scrubbed": 0,
            "requests_completed": 0,
        }

        requests = db.query(GDPRRequest).join(Visitor).filter(
            Visitor.organization_id == organization_id,
            GDPRRequest.request_type == "data_deletion",
            GDPRRequest.status.in_(("pending", "processing")),
        ).order_by(GDPRRequest.request_date.asc()).all()

        for gdpr_request in requests:
            visitor = gdpr_request.visitor
            if visitor is None:
                gdpr_request.status = "completed"
                gdpr_request.completion_date = now
                gdpr_request.notes = self._append_note(
                    gdpr_request.notes,
                    f"{now.isoformat()} request completed after visitor record became unavailable.",
                )
                stats["requests_completed"] += 1
                continue

            request_date = self._normalize_timestamp(gdpr_request.request_date)
            request_age_days = max(
                0.0,
                (now - request_date).total_seconds() / 86400.0,
            )

            if request_age_days >= retention_days["face_embeddings"]:
                stats["face_embeddings"] += self._clear_face_embeddings_for_visitor(db, visitor.id)

            if request_age_days >= retention_days["face_images"]:
                stats["face_images"] += self._remove_face_images_for_visitor(db, visitor.id)

            if request_age_days >= retention_days["logs"]:
                stats["visitor_logs_anonymized"] += self._anonymize_visitor_logs_for_visitor(db, visitor.id)
                stats["detection_logs_anonymized"] += self._anonymize_detection_logs_for_visitor(db, visitor.id)
                stats["consents_deleted"] += db.query(VisitorConsent).filter(
                    VisitorConsent.visitor_id == visitor.id,
                ).delete(synchronize_session=False)

                face_records = db.query(FaceData).filter(
                    FaceData.visitor_id == visitor.id,
                ).all()
                for face in face_records:
                    if face.image_url:
                        stats["face_images"] += self._remove_data_file(face.image_url)
                    db.delete(face)
                stats["face_data_deleted"] += len(face_records)

                self._scrub_visitor_profile(visitor, now)
                stats["visitors_scrubbed"] += 1
                gdpr_request.status = "completed"
                gdpr_request.completion_date = now
                gdpr_request.notes = self._append_note(
                    gdpr_request.notes,
                    f"{now.isoformat()} deletion workflow completed after retention windows elapsed.",
                )
                stats["requests_completed"] += 1
            else:
                gdpr_request.status = "processing"

        db.commit()
        return stats

    def purge_expired_logs(self, db: Session, organization_id: UUID) -> Dict[str, int]:
        """Blanket time-based retention purge (independent of deletion requests):
        delete detection logs and strip visitor-log biometric media older than the
        organization's ``log_retention_days``. Returns counts."""
        from models.models import Organization, DetectionLog, CameraSession, VisitorLog

        org = db.query(Organization).filter(Organization.id == organization_id).first()
        retention_days = int(getattr(org, "log_retention_days", 90) or 90)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

        stats = {
            "retention_days": retention_days,
            "detection_logs_deleted": 0,
            "visitor_log_media_removed": 0,
            "files_removed": 0,
        }

        # Detection logs are ephemeral live-session data — delete rows + image files.
        det_rows = (
            db.query(DetectionLog)
            .join(CameraSession, DetectionLog.session_id == CameraSession.id)
            .filter(
                CameraSession.organization_id == organization_id,
                DetectionLog.timestamp < cutoff,
            )
            .all()
        )
        for det in det_rows:
            if det.face_image_path:
                stats["files_removed"] += self._remove_data_file(det.face_image_path)
            db.delete(det)
        stats["detection_logs_deleted"] = len(det_rows)

        # Visitor logs are retained for audit, but their biometric media is stripped.
        vl_rows = (
            db.query(VisitorLog)
            .filter(
                VisitorLog.organization_id == organization_id,
                VisitorLog.timestamp < cutoff,
                VisitorLog.face_image_path.isnot(None),
            )
            .all()
        )
        for vl in vl_rows:
            stats["files_removed"] += self._remove_data_file(vl.face_image_path)
            vl.face_image_path = None
            stats["visitor_log_media_removed"] += 1

        db.commit()
        return stats

    def _retention_days_by_type(
        self,
        db: Session,
        organization_id: UUID,
    ) -> Dict[str, int]:
        retention_days = dict(DEFAULT_RETENTION_DAYS)
        policies = db.query(DataRetentionPolicy).filter(
            DataRetentionPolicy.organization_id == organization_id,
        ).all()
        for policy in policies:
            if policy.auto_delete_enabled:
                retention_days[policy.data_type] = max(0, int(policy.retention_days))
        return retention_days

    def _clear_face_embeddings_for_visitor(
        self,
        db: Session,
        visitor_id: UUID,
    ) -> int:
        faces = db.query(FaceData).filter(
            FaceData.visitor_id == visitor_id,
            FaceData.embedding.isnot(None),
        ).all()
        for face in faces:
            face.embedding = None
        return len(faces)

    def _remove_face_images_for_visitor(
        self,
        db: Session,
        visitor_id: UUID,
    ) -> int:
        faces = db.query(FaceData).filter(
            FaceData.visitor_id == visitor_id,
            FaceData.image_url.isnot(None),
        ).all()
        removed = 0
        for face in faces:
            removed += self._remove_data_file(face.image_url)
            face.image_url = None
        return removed

    def _anonymize_visitor_logs_for_visitor(
        self,
        db: Session,
        visitor_id: UUID,
    ) -> int:
        logs = db.query(VisitorLog).filter(
            VisitorLog.visitor_id == visitor_id,
        ).all()
        for log in logs:
            # Delete media files from storage before nulling the path references.
            # Not deleting files here was a GDPR gap — biometric crops and video
            # snippets remained on disk/object-storage after the DB path was cleared.
            if log.face_image_path:
                storage.delete_file(log.face_image_path)
            if log.video_snippet_path:
                storage.delete_file(log.video_snippet_path)
            log.visitor_id = None
            log.face_data_id = None
            log.face_image_path = None
            log.video_snippet_path = None
            log.identified = False
            log.status = "unidentified"
        return len(logs)

    def _anonymize_detection_logs_for_visitor(
        self,
        db: Session,
        visitor_id: UUID,
    ) -> int:
        logs = db.query(DetectionLog).filter(
            DetectionLog.visitor_id == visitor_id,
        ).all()
        for log in logs:
            # Delete face crop from storage before clearing the path.
            if log.face_image_path:
                storage.delete_file(log.face_image_path)
            log.visitor_id = None
            log.identified = False
            log.face_image_path = None
            log.embedding_snapshot = None
        return len(logs)

    def _scrub_visitor_profile(
        self,
        visitor: Visitor,
        deleted_at: datetime,
    ) -> None:
        visitor.name = None
        visitor.email = None
        visitor.phone = None
        visitor.description = None
        visitor.notes = None
        visitor.visitor_metadata = {
            "gdpr_deleted": True,
            "deleted_at": deleted_at.isoformat(),
        }
        visitor.is_known = False
        visitor.is_active = False
        visitor.custom_threshold = None
        visitor.auto_learn = False
        visitor.last_detected_at = None
        visitor.detection_count = 0

    def _remove_data_file(self, relative_path: Optional[str]) -> int:
        if not relative_path:
            return 0
        try:
            storage.ensure_local_file(relative_path)
        except (FileNotFoundError, RuntimeError):
            return 0
        storage.delete_file(relative_path)
        return 1

    def _append_note(self, existing: Optional[str], message: str) -> str:
        if not existing:
            return message
        if message in existing:
            return existing
        return f"{existing}\n{message}"

    def _normalize_timestamp(self, value: Optional[datetime]) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
