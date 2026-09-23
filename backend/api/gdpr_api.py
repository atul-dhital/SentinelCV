"""GDPR API routes for data export, deletion, consent, and retention."""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
from typing import Dict, List, Literal

logger = logging.getLogger("sentinelcv.gdpr")
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.base import get_db
from core.security import get_current_user, require_role
from services.gdpr_service import GDPRService
from services import user_service, visitor_service
from models.models import Visitor
from schemas.schemas import (
    GDPRRequestCreate, GDPRRequestResponse,
    VisitorConsentCreate, VisitorConsentResponse,
    DataRetentionPolicyCreate, DataRetentionPolicyResponse
)

router = APIRouter(prefix="/api/v1/gdpr", tags=["GDPR"])
gdpr_service = GDPRService()


def _get_current_org_id(current_user_id: str = Depends(get_current_user), db: Session = Depends(get_db)) -> UUID:
    """Extract organization ID from current user."""
    user = user_service.get_user_by_id(db, current_user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return UUID(str(user.organization_id))


def _get_org_visitor_or_404(db: Session, visitor_id: UUID, org_id: UUID) -> Visitor:
    visitor = gdpr_service.get_visitor_for_org(db, visitor_id, org_id)
    if not visitor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visitor not found",
        )
    return visitor


@router.post("/export", response_model=GDPRRequestResponse, status_code=status.HTTP_201_CREATED)
async def request_data_export(
    visitor_id: UUID,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db)
):
    """Request GDPR data export for a visitor. Admin only."""
    user_id = UUID(str(current_user.id))
    org_id = UUID(str(current_user.organization_id))
    _get_org_visitor_or_404(db, visitor_id, org_id)

    request_data = GDPRRequestCreate(
        request_type="data_export",
        notes="Data export requested via API"
    )

    gdpr_request = gdpr_service.create_gdpr_request(db, visitor_id, request_data)
    completed = await gdpr_service.complete_data_export_request(db, gdpr_request, org_id=str(org_id))
    if not completed:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate GDPR export archive",
        )
    visitor_service.create_audit_log(
        db, org_id, user_id, "gdpr_data_export", "visitor", str(visitor_id),
        details={"gdpr_request_id": str(gdpr_request.id)},
    )
    return completed


@router.post("/delete", response_model=GDPRRequestResponse, status_code=status.HTTP_201_CREATED)
async def request_data_deletion(
    visitor_id: UUID,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db)
):
    """Request GDPR data deletion for a visitor. Admin only."""
    user_id = UUID(str(current_user.id))
    org_id = UUID(str(current_user.organization_id))
    _get_org_visitor_or_404(db, visitor_id, org_id)

    request_data = GDPRRequestCreate(
        request_type="data_deletion",
        notes="Data deletion requested via API"
    )

    gdpr_request = gdpr_service.create_gdpr_request(db, visitor_id, request_data)
    visitor_service.create_audit_log(
        db, org_id, user_id, "gdpr_data_deletion_initiated", "visitor", str(visitor_id),
        details={"gdpr_request_id": str(gdpr_request.id)},
    )
    started = await gdpr_service.process_data_deletion(db, visitor_id)
    if not started:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Visitor not found",
        )
    db.refresh(gdpr_request)
    return gdpr_request


class _ProcessRequestBody(BaseModel):
    action: Literal["approve", "reject"]


@router.post("/requests/{request_id}/process", response_model=GDPRRequestResponse)
async def process_gdpr_request(
    request_id: UUID,
    body: _ProcessRequestBody,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Approve or reject a pending GDPR deletion request. Admin only.

    approve — triggers the deletion workflow and marks the request as processing.
    reject  — marks the request as completed with a rejection note; no data is removed.
    """
    from datetime import datetime, timezone

    user_id = UUID(str(current_user.id))
    org_id = UUID(str(current_user.organization_id))

    gdpr_request = gdpr_service.get_gdpr_request(db, request_id)
    if not gdpr_request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GDPR request not found")

    if not gdpr_service.gdpr_request_belongs_to_org(gdpr_request, org_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GDPR request not found")

    if gdpr_request.status not in ("pending", "processing"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Request is already {gdpr_request.status} and cannot be re-processed",
        )

    now = datetime.now(timezone.utc)

    if body.action == "approve":
        started = await gdpr_service.process_data_deletion(db, gdpr_request.visitor_id)
        if not started:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visitor record not found for this request",
            )
        visitor_service.create_audit_log(
            db, org_id, user_id, "gdpr_deletion_approved", "gdpr_request", str(request_id),
            details={"action": "approve"},
        )
    else:
        gdpr_request.status = "completed"
        gdpr_request.completion_date = now
        gdpr_request.notes = (
            f"{(gdpr_request.notes or '').strip()}\n"
            f"{now.isoformat()} request rejected by admin."
        ).strip()
        db.commit()
        visitor_service.create_audit_log(
            db, org_id, user_id, "gdpr_deletion_rejected", "gdpr_request", str(request_id),
            details={"action": "reject"},
        )

    db.refresh(gdpr_request)
    return gdpr_request


@router.get("/requests/{request_id}", response_model=GDPRRequestResponse)
async def get_gdpr_request_status(
    request_id: UUID,
    org_id: UUID = Depends(_get_current_org_id),
    db: Session = Depends(get_db)
):
    """Get status of GDPR request.
    
    Args:
        request_id: GDPR request UUID
        org_id: Organization UUID
        db: Database session
        
    Returns:
        Request details and status
    """
    request = gdpr_service.get_gdpr_request(db, request_id)
    if not request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GDPR request not found"
        )
    
    if not gdpr_service.gdpr_request_belongs_to_org(request, org_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GDPR request not found",
        )
    return request


@router.get("/pending", response_model=List[GDPRRequestResponse])
async def list_pending_requests(
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db)
):
    """List all pending GDPR requests for organization. Admin only."""
    org_id = UUID(str(current_user.organization_id))
    requests = gdpr_service.list_pending_gdpr_requests(db, org_id)
    return requests


@router.post("/consent", response_model=VisitorConsentResponse, status_code=status.HTTP_201_CREATED)
async def set_visitor_consent(
    visitor_id: UUID,
    consent_data: VisitorConsentCreate,
    org_id: UUID = Depends(_get_current_org_id),
    db: Session = Depends(get_db)
):
    """Record visitor consent for data processing.
    
    Consent types:
    - face_recognition: recognize visitor in cameras
    - tracking: track movements across cameras
    - analytics: use data for aggregate analytics
    
    Args:
        visitor_id: Visitor UUID
        consent_data: Consent details
        db: Database session
        
    Returns:
        Consent record
    """
    _get_org_visitor_or_404(db, visitor_id, org_id)
    consent = gdpr_service.create_consent(db, visitor_id, consent_data)
    return consent


@router.get("/consent/{consent_type}", response_model=VisitorConsentResponse)
async def get_visitor_consent(
    visitor_id: UUID,
    consent_type: str,
    org_id: UUID = Depends(_get_current_org_id),
    db: Session = Depends(get_db)
):
    """Get visitor's current consent status.
    
    Args:
        visitor_id: Visitor UUID
        consent_type: Type of consent (face_recognition, tracking, analytics)
        db: Database session
        
    Returns:
        Consent record or HTTP 404
    """
    _get_org_visitor_or_404(db, visitor_id, org_id)
    consent = gdpr_service.get_visitor_consent(db, visitor_id, consent_type)
    if not consent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No consent record found"
        )
    return consent


@router.post("/consent/{consent_type}/withdraw", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_consent(
    visitor_id: UUID,
    consent_type: str,
    org_id: UUID = Depends(_get_current_org_id),
    db: Session = Depends(get_db)
):
    """Withdraw visitor consent for a data type.
    
    Args:
        visitor_id: Visitor UUID
        consent_type: Type of consent to withdraw
        db: Database session
    """
    _get_org_visitor_or_404(db, visitor_id, org_id)
    success = gdpr_service.withdraw_consent(db, visitor_id, consent_type)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No consent record found"
        )
    return None


@router.put("/policies/{org_id}", status_code=status.HTTP_201_CREATED)
async def update_retention_policies(
    org_id: UUID,
    policies: List[DataRetentionPolicyCreate],
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db)
):
    """Configure data retention policies for organization. Admin only."""
    admin_org_id = UUID(str(current_user.organization_id))
    if org_id != admin_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify other organization's policies"
        )

    created_policies = []
    for policy_data in policies:
        policy = gdpr_service.create_retention_policy(db, org_id, policy_data)
        created_policies.append(policy)

    return created_policies


@router.get("/policies/{org_id}", response_model=List[DataRetentionPolicyResponse])
async def get_retention_policies(
    org_id: UUID,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db)
):
    """Get data retention policies for organization. Admin only."""
    admin_org_id = UUID(str(current_user.organization_id))
    if org_id != admin_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view other organization's policies"
        )

    policies = gdpr_service.list_retention_policies(db, org_id)
    return policies


class _BulkProcessBody(BaseModel):
    request_ids: List[UUID]
    action: Literal["approve", "reject"]


@router.post("/retention/purge")
async def run_retention_purge(
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Admin: run the blanket time-based retention purge for this org now.

    Deletes detection logs and strips visitor-log biometric media older than the
    org's ``log_retention_days``. The same purge also runs automatically via the
    GDPR cleanup scheduler.
    """
    org_id = UUID(str(current_user.organization_id))
    stats = gdpr_service.purge_expired_logs(db, org_id)
    return {"status": "completed", **stats}


@router.post("/requests/bulk-process", status_code=status.HTTP_200_OK)
async def bulk_process_gdpr_requests(
    body: _BulkProcessBody,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Approve or reject multiple pending GDPR requests in one call. Admin only.

    Returns a summary dict: {request_id: "approved" | "rejected" | "skipped" | "error"}.
    """
    from datetime import datetime, timezone

    user_id = UUID(str(current_user.id))
    org_id = UUID(str(current_user.organization_id))

    results: Dict[str, str] = {}
    now = datetime.now(timezone.utc)

    for request_id in body.request_ids:
        rid_str = str(request_id)
        try:
            gdpr_request = gdpr_service.get_gdpr_request(db, request_id)
            if not gdpr_request:
                results[rid_str] = "not_found"
                continue
            if not gdpr_service.gdpr_request_belongs_to_org(gdpr_request, org_id):
                results[rid_str] = "not_found"
                continue
            if gdpr_request.status not in ("pending", "processing"):
                results[rid_str] = "skipped"
                continue

            if body.action == "approve":
                started = await gdpr_service.process_data_deletion(db, gdpr_request.visitor_id)
                results[rid_str] = "approved" if started else "error"
            else:
                gdpr_request.status = "completed"
                gdpr_request.completion_date = now
                gdpr_request.notes = (
                    f"{(gdpr_request.notes or '').strip()}\n"
                    f"{now.isoformat()} bulk-rejected by admin."
                ).strip()
                db.commit()
                results[rid_str] = "rejected"

            visitor_service.create_audit_log(
                db, org_id, user_id,
                f"gdpr_bulk_{body.action}",
                "gdpr_request", rid_str,
            )
        except Exception as _err:
            logger.warning("Bulk GDPR %s failed for request %s: %s", body.action, rid_str, _err)
            results[rid_str] = "error"

    return {"action": body.action, "results": results, "processed": len(results)}


@router.post("/cleanup/{org_id}", status_code=status.HTTP_200_OK)
async def cleanup_expired_data(
    org_id: UUID,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db)
):
    """Trigger data cleanup for expired retention periods. Admin only."""
    admin_org_id = UUID(str(current_user.organization_id))
    if org_id != admin_org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot cleanup other organization's data"
        )

    stats = await gdpr_service.cleanup_expired_data(db, org_id)
    return {
        "status": "cleanup_completed",
        "organization_id": str(org_id),
        "stats": stats
    }
