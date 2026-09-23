"""
SSO/OAuth Integration API (ENH-012) — LEGACY

This module implements the original OAuth2 flow (Google/GitHub).
The canonical SSO implementation is sso_api.py (SAML + provider management).

SECURITY NOTE: This module's OAuth2 flow has not been audited for PKCE, state
parameter replay, or token rotation. Do not expose to production until those
controls are verified. Prefer sso_api.py for new integrations.
"""

import hashlib
import os
import logging
import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from db.base import get_db
from core.security import get_current_user, create_access_token, create_refresh_token, REFRESH_TOKEN_EXPIRE_DAYS
from services import user_service
from models import models

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/sso", tags=["SSO/OAuth"])


def _issue_sso_refresh_token(db: Session, user: models.User, request: Request) -> str:
    """Create a tracked RefreshTokenSession and return the raw refresh token."""
    token_jti = secrets.token_urlsafe(18)
    refresh_token = create_refresh_token(subject=str(user.id), jti=token_jti)
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    forwarded_for = request.headers.get("x-forwarded-for", "")
    ip_address = forwarded_for.split(",")[0].strip() if forwarded_for else (
        request.client.host if request.client else None
    )
    user_agent = request.headers.get("user-agent")

    session = models.RefreshTokenSession(
        organization_id=user.organization_id,
        user_id=user.id,
        token_hash=token_hash,
        token_jti=token_jti,
        expires_at=expires_at,
        last_used_at=now,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(session)
    db.commit()
    return refresh_token

# OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")

PROVIDERS = {}
if GOOGLE_CLIENT_ID:
    PROVIDERS["google"] = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v2/userinfo",
        "scopes": ["openid", "email", "profile"],
    }
if GITHUB_CLIENT_ID:
    PROVIDERS["github"] = {
        "client_id": GITHUB_CLIENT_ID,
        "client_secret": GITHUB_CLIENT_SECRET,
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scopes": ["user:email"],
    }


class SSOCallbackRequest(BaseModel):
    code: str
    state: Optional[str] = None
    redirect_uri: Optional[str] = None


@router.get("/providers")
def list_providers():
    """List available SSO providers."""
    available = []
    for name, config in PROVIDERS.items():
        available.append({
            "name": name,
            "enabled": True,
            "auth_url": config["auth_url"],
        })

    if not available:
        available.append({
            "name": "none",
            "enabled": False,
            "note": "No SSO providers configured. Set GOOGLE_CLIENT_ID or GITHUB_CLIENT_ID env vars.",
        })

    return {"providers": available}


@router.get("/{provider}/login")
def sso_login(
    provider: str,
    redirect_uri: str = Query("http://localhost:3001/login"),
):
    """Get OAuth login URL for a provider."""
    if provider not in PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider}' not configured. Available: {list(PROVIDERS.keys()) or 'none'}",
        )

    config = PROVIDERS[provider]
    state = secrets.token_urlsafe(32)

    params = {
        "client_id": config["client_id"],
        "redirect_uri": redirect_uri,
        "scope": " ".join(config["scopes"]),
        "response_type": "code",
        "state": state,
    }

    # Build auth URL
    query = "&".join(f"{k}={v}" for k, v in params.items())
    auth_url = f"{config['auth_url']}?{query}"

    return {
        "auth_url": auth_url,
        "state": state,
        "provider": provider,
    }


@router.post("/{provider}/callback")
async def sso_callback(
    provider: str,
    request: SSOCallbackRequest,
    http_request: Request,
    http_response: Response,
    db: Session = Depends(get_db),
):
    """
    Handle OAuth callback.

    Exchanges authorization code for tokens, gets user info,
    and creates/links user account.
    """
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Provider '{provider}' not configured")

    config = PROVIDERS[provider]

    try:
        import httpx

        # Exchange code for token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                config["token_url"],
                data={
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "code": request.code,
                    "redirect_uri": request.redirect_uri or "http://localhost:3001/login",
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )

            if token_response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to exchange authorization code")

            token_data = token_response.json()
            access_token = token_data.get("access_token")

            if not access_token:
                raise HTTPException(status_code=400, detail="No access token received")

            # Get user info
            headers = {"Authorization": f"Bearer {access_token}"}
            if provider == "github":
                headers["Accept"] = "application/json"

            userinfo_response = await client.get(config["userinfo_url"], headers=headers)
            userinfo = userinfo_response.json()

        # Extract user details
        if provider == "google":
            provider_email = userinfo.get("email", "")
            provider_name = userinfo.get("name", "")
            provider_user_id = userinfo.get("id", "")
        elif provider == "github":
            provider_email = userinfo.get("email", "")
            provider_name = userinfo.get("name") or userinfo.get("login", "")
            provider_user_id = str(userinfo.get("id", ""))
        else:
            provider_email = userinfo.get("email", "")
            provider_name = userinfo.get("name", "")
            provider_user_id = userinfo.get("sub", userinfo.get("id", ""))

        if not provider_email:
            raise HTTPException(status_code=400, detail="Email not provided by SSO provider")

        # Find or create user
        user = user_service.get_user_by_email(db, provider_email)
        if not user:
            # Create new user and organization
            org = models.Organization(name=f"{provider_name}'s Organization")
            db.add(org)
            db.flush()

            from core.security import hash_password
            user = models.User(
                organization_id=org.id,
                email=provider_email,
                full_name=provider_name,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                role="admin",
            )
            db.add(user)
            db.flush()

        # Store SSO connection
        existing_conn = db.query(models.SSOConnection).filter(
            models.SSOConnection.user_id == user.id,
            models.SSOConnection.provider == provider,
        ).first()

        if not existing_conn:
            conn = models.SSOConnection(
                user_id=user.id,
                provider=provider,
                provider_user_id=provider_user_id,
                provider_email=provider_email,
            )
            db.add(conn)

        db.commit()

        # Generate tokens — refresh token is session-tracked and cookie-set (matches auth.py flow)
        jwt_token = create_access_token(subject=str(user.id))
        refresh = _issue_sso_refresh_token(db, user, http_request)

        refresh_max_age = int(timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS).total_seconds())
        http_response.set_cookie(
            key="sentinelcv_refresh_token",
            value=refresh,
            httponly=True,
            secure=(http_request.url.scheme == "https"),
            samesite="lax",
            max_age=refresh_max_age,
            expires=refresh_max_age,
            path="/api/v1/auth",
        )

        return {
            "access_token": jwt_token,
            "refresh_token": refresh,
            "token_type": "bearer",
            "user": {
                "id": str(user.id),
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
            },
            "sso_provider": provider,
            "is_new_user": not existing_conn,
        }

    except HTTPException:
        raise
    except ImportError:
        # httpx not installed - return instructions
        raise HTTPException(
            status_code=501,
            detail="SSO callback requires 'httpx' package. Install with: pip install httpx",
        )
    except Exception as e:
        logger.error(f"SSO callback failed: {e}")
        raise HTTPException(status_code=500, detail=f"SSO authentication failed: {str(e)}")


@router.get("/connections")
def list_sso_connections(
    db: Session = Depends(get_db),
    current_user_id: str = Depends(get_current_user),
):
    """List SSO connections for the current user."""
    connections = db.query(models.SSOConnection).filter(
        models.SSOConnection.user_id == current_user_id,
    ).limit(10000).all()

    return [
        {
            "id": str(c.id),
            "provider": c.provider,
            "provider_email": c.provider_email,
            "created_at": c.created_at,
        }
        for c in connections
    ]
