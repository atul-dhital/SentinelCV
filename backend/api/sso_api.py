"""SSO API routes for SAML/OAuth2 provider management.

Endpoints:
- POST /api/v1/sso/configure — Configure SSO provider
- GET /api/v1/sso/providers — List SSO providers
- GET /api/v1/sso/providers/{id} — Get SSO provider
- PUT /api/v1/sso/providers/{id} — Update SSO provider
- DELETE /api/v1/sso/providers/{id} — Delete SSO provider
- POST /api/v1/sso/acs — SAML Assertion Consumer Service
- GET /api/v1/sso/metadata — Generate SAML metadata
"""

import os
from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from db.base import get_db
from core.security import create_access_token, get_current_user, require_role
from api.auth import _issue_refresh_token, _set_refresh_cookie
from services.sso_service import SSOService
from services import user_service
from schemas.schemas import (
    SSOProviderCreate, SSOProviderUpdate, SSOProviderResponse
)
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/v1/sso", tags=["SSO"])
sso_service = SSOService()


class SAMLACSRequest(BaseModel):
    provider_id: UUID
    saml_response: str
    relay_state: Optional[str] = None


def _get_current_org_id(current_user_id: str = Depends(get_current_user), db: Session = Depends(get_db)) -> UUID:
    """Extract organization ID from current user."""
    user = user_service.get_user_by_id(db, current_user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user.organization_id


@router.post("/configure", response_model=SSOProviderResponse, status_code=status.HTTP_201_CREATED)
async def configure_sso_provider(
    provider_data: SSOProviderCreate,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db)
):
    """Configure a new SSO provider for organization. Admin only."""
    org_id = UUID(str(current_user.organization_id))
    try:
        provider = sso_service.create_sso_provider(db, org_id, provider_data)
        return provider
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to configure SSO provider: {str(e)}"
        )


@router.get("/providers", response_model=List[SSOProviderResponse])
async def list_sso_providers(
    active_only: bool = False,
    org_id: UUID = Depends(_get_current_org_id),
    db: Session = Depends(get_db)
):
    """List all SSO providers for organization.
    
    Args:
        active_only: Only return active providers
        org_id: Organization UUID
        db: Database session
        
    Returns:
        List of SSO providers
    """
    providers = sso_service.get_organization_sso_providers(db, org_id, active_only)
    return providers


@router.get("/providers/{provider_id}", response_model=SSOProviderResponse)
async def get_sso_provider(
    provider_id: UUID,
    org_id: UUID = Depends(_get_current_org_id),
    db: Session = Depends(get_db)
):
    """Get SSO provider details.
    
    Args:
        provider_id: Provider UUID
        org_id: Organization UUID
        db: Database session
        
    Returns:
        SSO provider details
    """
    provider = sso_service.get_sso_provider(db, provider_id)
    if not provider or provider.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SSO provider not found"
        )
    return provider


@router.put("/providers/{provider_id}", response_model=SSOProviderResponse)
async def update_sso_provider(
    provider_id: UUID,
    update_data: SSOProviderUpdate,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db)
):
    """Update SSO provider configuration. Admin only."""
    org_id_str = str(current_user.organization_id)
    provider = sso_service.get_sso_provider(db, provider_id)
    if not provider or str(provider.organization_id) != org_id_str:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SSO provider not found"
        )

    updated = sso_service.update_sso_provider(db, provider_id, update_data)
    return updated


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sso_provider(
    provider_id: UUID,
    current_user=Depends(require_role("admin")),
    db: Session = Depends(get_db)
):
    """Delete SSO provider configuration. Admin only."""
    org_id_str = str(current_user.organization_id)
    provider = sso_service.get_sso_provider(db, provider_id)
    if not provider or str(provider.organization_id) != org_id_str:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SSO provider not found"
        )

    sso_service.delete_sso_provider(db, provider_id)
    return None


@router.post("/acs")
async def saml_acs(
    payload: SAMLACSRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    """SAML Assertion Consumer Service endpoint.

    Receives SAML response from identity provider. On success issues a real
    JWT access token and sets the refresh cookie using the same mechanism as
    the normal login flow.
    """
    provider = sso_service.get_sso_provider(db, payload.provider_id)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SSO provider not found"
        )
    if provider.provider_type != "saml":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ACS is only supported for SAML providers"
        )

    attributes = await sso_service.validate_saml_response(
        payload.saml_response,
        {
            "entity_id": provider.entity_id,
            "attribute_mappings": provider.attribute_mappings or {},
        },
    )
    if not attributes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid SAML response"
        )

    email = (attributes.get("email") or "").strip().lower()
    user = user_service.get_user_by_email(db, email) if email else None
    if user and user.organization_id != provider.organization_id:
        user = None

    if not user:
        return {
            "authenticated": False,
            "provider_id": str(provider.id),
            "relay_state": payload.relay_state,
            "reason": "user_not_provisioned",
            "attributes": attributes,
        }

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    access_token = create_access_token(subject=str(user.id))
    refresh_token = _issue_refresh_token(db, user, request)
    _set_refresh_cookie(response, refresh_token, request)

    return {
        "authenticated": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "provider_id": str(provider.id),
        "user_id": str(user.id),
        "email": user.email,
        "relay_state": payload.relay_state,
        "attributes": attributes,
    }


@router.post("/providers/{provider_id}/test", status_code=status.HTTP_200_OK)
async def test_sso_provider(
    provider_id: UUID,
    org_id: UUID = Depends(_get_current_org_id),
    db: Session = Depends(get_db),
):
    """
    Validate SSO provider configuration without initiating a real login.

    Checks:
    - Provider exists and belongs to caller's org
    - Required fields (entity_id for SAML, client_id/secret for OAuth2) are present
    - Metadata URL is reachable (SAML)
    - Discovery document is reachable (OIDC)

    Returns a structured validation result with per-check status.
    """
    import httpx

    provider = sso_service.get_sso_provider(db, provider_id)
    if not provider or provider.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO provider not found")

    checks: dict = {}
    overall_ok = True

    provider_type = (provider.provider_type or "").lower()

    # ── SAML checks ──────────────────────────────────────────────────────────
    if provider_type == "saml":
        # 1. entity_id present
        checks["entity_id_present"] = {
            "ok": bool(provider.entity_id),
            "detail": "entity_id is set" if provider.entity_id else "entity_id is missing",
        }
        if not provider.entity_id:
            overall_ok = False

        # 2. metadata_url reachable (if configured)
        metadata_url = (provider.metadata_url or "").strip()
        if metadata_url:
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.get(metadata_url)
                reachable = resp.status_code < 400
                checks["metadata_url_reachable"] = {
                    "ok": reachable,
                    "url": metadata_url,
                    "http_status": resp.status_code,
                    "detail": "Metadata URL is reachable" if reachable else f"HTTP {resp.status_code}",
                }
                if not reachable:
                    overall_ok = False
            except Exception as exc:
                checks["metadata_url_reachable"] = {
                    "ok": False,
                    "url": metadata_url,
                    "detail": f"Connection error: {exc}",
                }
                overall_ok = False
        else:
            checks["metadata_url_reachable"] = {
                "ok": True,
                "detail": "No metadata_url configured — manual XML configuration assumed",
            }

    # ── OAuth2 / OIDC checks ─────────────────────────────────────────────────
    elif provider_type in ("oauth2", "oidc", "openid_connect"):
        checks["client_id_present"] = {
            "ok": bool(provider.client_id),
            "detail": "client_id is set" if provider.client_id else "client_id is missing",
        }
        checks["client_secret_present"] = {
            "ok": bool(provider.client_secret),
            "detail": "client_secret is set" if provider.client_secret else "client_secret is missing",
        }
        if not provider.client_id or not provider.client_secret:
            overall_ok = False

        if provider_type in ("oidc", "openid_connect"):
            discovery_url = (provider.discovery_url or "").strip()
            if discovery_url:
                try:
                    async with httpx.AsyncClient(timeout=8.0) as client:
                        resp = await client.get(discovery_url)
                    reachable = resp.status_code == 200
                    checks["discovery_url_reachable"] = {
                        "ok": reachable,
                        "url": discovery_url,
                        "http_status": resp.status_code,
                        "detail": "OIDC discovery document reachable" if reachable else f"HTTP {resp.status_code}",
                    }
                    if not reachable:
                        overall_ok = False
                except Exception as exc:
                    checks["discovery_url_reachable"] = {
                        "ok": False,
                        "url": discovery_url,
                        "detail": f"Connection error: {exc}",
                    }
                    overall_ok = False
    else:
        checks["provider_type"] = {
            "ok": False,
            "detail": f"Unknown provider_type: '{provider_type}'. Supported: saml, oauth2, oidc.",
        }
        overall_ok = False

    # ── Common: is provider marked active ─────────────────────────────────
    checks["provider_active"] = {
        "ok": bool(provider.is_active),
        "detail": "Provider is active" if provider.is_active else "Provider is disabled — set is_active=true to use",
    }

    return {
        "provider_id": str(provider_id),
        "provider_type": provider_type,
        "provider_name": provider.name,
        "overall_status": "ok" if overall_ok else "failed",
        "checks": checks,
    }


@router.get("/metadata")
async def get_saml_metadata(
    provider_id: UUID,
    org_id: UUID = Depends(_get_current_org_id),
    db: Session = Depends(get_db)
):
    """Generate SAML SP metadata.
    
    For configuration in identity provider.
    
    Args:
        provider_id: Provider UUID
        org_id: Organization UUID
        db: Database session
        
    Returns:
        XML SAML metadata
    """
    provider = sso_service.get_sso_provider(db, provider_id)
    if not provider or provider.organization_id != org_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SSO provider not found"
        )

    base_url = (
        os.getenv("SENTINELCV_PUBLIC_BASE_URL")
        or os.getenv("BACKEND_PUBLIC_URL")
        or "http://localhost:8000"
    )
    metadata_xml = sso_service.build_saml_metadata(provider, base_url)
    return Response(content=metadata_xml, media_type="application/xml")
