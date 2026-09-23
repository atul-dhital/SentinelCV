from fastapi import APIRouter, Depends, Request
import logging

router = APIRouter(prefix="/audit-service", tags=["GDPR Audit"])
logger = logging.getLogger("sentinelcv.audit")

@router.post("/log-access")
async def log_pii_access(request: Request, data_type: str, accessed_by: str, reason: str):
    """
    Log access to PII data for GDPR compliance.
    """
    logger.info(f"PII Access Logged: type={data_type}, user={accessed_by}, reason={reason}")
    return {"status": "logged"}
