from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from db.base import get_db
from models import models
from schemas import schemas
from core import security
from services import user_service, visitor_service, password_reset_email_service
from services.redis_service import get_redis_service
from uuid import UUID
from typing import Optional, Any
import hashlib
import secrets
import os

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_ip(raw: Optional[str]) -> Optional[str]:
    """Normalize IPv4-mapped IPv6 addresses and loopback variants to a canonical form."""
    if not raw:
        return raw
    import ipaddress as _ip
    try:
        addr = _ip.ip_address(raw)
        if isinstance(addr, _ip.IPv6Address) and addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        return str(addr)
    except ValueError:
        return raw


def _extract_request_metadata(request: Optional[Request]) -> tuple[Optional[str], Optional[str]]:
    if request is None:
        return None, None
    forwarded_for = request.headers.get("x-forwarded-for", "")
    raw_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else None)
    ip_address = _normalize_ip(raw_ip)
    user_agent = request.headers.get("user-agent")
    return ip_address, user_agent


def _refresh_expiry_from_payload(payload: dict[str, Any]) -> datetime:
    exp = payload.get("exp")
    if isinstance(exp, (int, float)):
        return datetime.fromtimestamp(float(exp), tz=timezone.utc)
    if isinstance(exp, str):
        try:
            parsed = datetime.fromisoformat(exp)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc) + timedelta(days=security.REFRESH_TOKEN_EXPIRE_DAYS)


def _env_int(name: str, default: int, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    raw_value = os.getenv(name)
    try:
        value = int(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        value = default

    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _refresh_cookie_name() -> str:
    return (os.getenv("REFRESH_COOKIE_NAME") or "sentinelcv_refresh_token").strip()


def _refresh_cookie_domain() -> Optional[str]:
    value = (os.getenv("REFRESH_COOKIE_DOMAIN") or "").strip()
    return value or None


def _refresh_cookie_path() -> str:
    return (os.getenv("REFRESH_COOKIE_PATH") or "/api/v1/auth").strip()


def _refresh_cookie_samesite() -> str:
    raw = os.getenv("REFRESH_COOKIE_SAMESITE")
    value = (raw or "lax").strip().lower()
    if value not in {"lax", "strict", "none"}:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "Invalid REFRESH_COOKIE_SAMESITE=%r — falling back to 'lax'. "
            "Valid values: lax, strict, none.",
            raw,
        )
        return "lax"
    return value


def _refresh_cookie_secure(request: Optional[Request]) -> bool:
    if os.getenv("REFRESH_COOKIE_SECURE") is not None:
        return _env_bool("REFRESH_COOKIE_SECURE", False)
    forwarded_proto = request.headers.get("x-forwarded-proto") if request else None
    scheme = forwarded_proto or (request.url.scheme if request else None)
    return bool(scheme == "https" or os.getenv("SENTINELCV_ENV") == "production")


def _set_refresh_cookie(response: Response, refresh_token: str, request: Optional[Request]) -> None:
    max_age = int(timedelta(days=security.REFRESH_TOKEN_EXPIRE_DAYS).total_seconds())
    response.set_cookie(
        key=_refresh_cookie_name(),
        value=refresh_token,
        httponly=True,
        secure=_refresh_cookie_secure(request),
        samesite=_refresh_cookie_samesite(),
        max_age=max_age,
        expires=max_age,
        path=_refresh_cookie_path(),
        domain=_refresh_cookie_domain(),
    )


def _clear_refresh_cookie(response: Response, request: Optional[Request]) -> None:
    response.delete_cookie(
        key=_refresh_cookie_name(),
        path=_refresh_cookie_path(),
        domain=_refresh_cookie_domain(),
        secure=_refresh_cookie_secure(request),
        httponly=True,
        samesite=_refresh_cookie_samesite(),
    )


def _resolve_refresh_token(
    request: Optional[Request],
    data: Optional[schemas.RefreshTokenRequest | schemas.LogoutRequest],
) -> Optional[str]:
    if data and data.refresh_token:
        token = data.refresh_token.strip()
        if token:
            return token
    if request is None:
        return None
    cookie_value = (request.cookies.get(_refresh_cookie_name()) or "").strip()
    return cookie_value or None


def _normalize_utc_timestamp(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _raise_rate_limit(scope: str, result: dict[str, Any]):
    retry_after = result.get("retry_after")
    headers = {
        "X-RateLimit-Limit": str(result.get("limit", "")),
        "X-RateLimit-Remaining": str(result.get("remaining", 0)),
    }
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Rate limit exceeded for {scope}",
        headers=headers,
    )


def _enforce_auth_rate_limit(
    scope: str,
    key: str,
    max_requests: int,
    window_seconds: int,
):
    normalized_key = (key or "").strip().lower()
    if not normalized_key:
        return

    redis_service = get_redis_service()
    result = redis_service.check_rate_limit(
        key=f"auth:{scope}:{normalized_key}",
        max_requests=max_requests,
        window_seconds=window_seconds,
    )
    if not result.get("allowed", True):
        _raise_rate_limit(scope, result)


def _issue_refresh_token(
    db: Session,
    user: models.User,
    request: Optional[Request],
    rotate_from_session: Optional[models.RefreshTokenSession] = None,
    *,
    commit: bool = True,
) -> str:
    token_jti = secrets.token_urlsafe(18)
    refresh_token = security.create_refresh_token(subject=str(user.id), jti=token_jti)
    payload = security.decode_token(refresh_token) or {}
    expires_at = _refresh_expiry_from_payload(payload)
    token_hash = _hash_refresh_token(refresh_token)
    now = datetime.now(timezone.utc)
    ip_address, user_agent = _extract_request_metadata(request)

    if rotate_from_session:
        rotate_from_session.revoked_at = now
        rotate_from_session.revoke_reason = "rotated"
        rotate_from_session.replaced_by_token_hash = token_hash
        rotate_from_session.last_used_at = now

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
    if commit:
        db.commit()
    return refresh_token


@router.post("/login", response_model=schemas.Token)
async def login(
    login_data: schemas.LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Authenticate user with email+password and return access+refresh tokens."""
    ip_address, user_agent = _extract_request_metadata(request)
    _enforce_auth_rate_limit(
        "login_ip",
        ip_address or "unknown",
        _env_int("AUTH_LOGIN_IP_LIMIT", 12, min_value=1, max_value=500),
        _env_int("AUTH_LOGIN_IP_WINDOW_SECONDS", 300, min_value=30, max_value=86400),
    )
    _enforce_auth_rate_limit(
        "login_email",
        login_data.email,
        _env_int("AUTH_LOGIN_EMAIL_LIMIT", 8, min_value=1, max_value=500),
        _env_int("AUTH_LOGIN_EMAIL_WINDOW_SECONDS", 900, min_value=30, max_value=86400),
    )

    user = user_service.authenticate_user(db, login_data.email, login_data.password)

    if not user:
        existing_user = user_service.get_user_by_email(db, login_data.email)
        if existing_user:
            visitor_service.create_audit_log(
                db,
                existing_user.organization_id,
                existing_user.id,
                "login_failed",
                "auth",
                str(existing_user.id),
                details={
                    "email_hash": hashlib.sha256(login_data.email.encode()).hexdigest()[:16],
                    "ip_address": ip_address,
                    "user_agent": user_agent,
                },
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = security.create_access_token(subject=str(user.id))
    refresh_token = _issue_refresh_token(db, user, request)
    _set_refresh_cookie(response, refresh_token, request)

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "login",
        "auth",
        str(user.id),
        details={
            "email": user.email,
            "ip_address": ip_address,
            "user_agent": user_agent,
        },
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/register", response_model=schemas.Token)
async def register(
    data: schemas.RegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Register a new organization with an admin user. Returns tokens for immediate login."""
    ip_address, _user_agent = _extract_request_metadata(request)
    _enforce_auth_rate_limit(
        "register_ip",
        ip_address or "unknown",
        _env_int("AUTH_REGISTER_IP_LIMIT", 5, min_value=1, max_value=100),
        _env_int("AUTH_REGISTER_IP_WINDOW_SECONDS", 3600, min_value=60, max_value=86400),
    )
    # Check if email already exists
    existing = user_service.get_user_by_email(db, data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    try:
        db_org = models.Organization(name=data.organization_name)
        db.add(db_org)
        db.flush()

        user_data = schemas.UserCreate(
            email=data.email,
            full_name=data.full_name,
            password=data.password,
            organization_id=db_org.id,
            role="admin",
        )
        db_user = user_service.create_user(db, user_data, commit=False)

        from services.visitor_service import create_audit_log
        create_audit_log(
            db,
            db_org.id,
            db_user.id,
            "register",
            "organization",
            str(db_org.id),
            commit=False,
        )

        access_token = security.create_access_token(subject=str(db_user.id))
        refresh_token = _issue_refresh_token(db, db_user, request, commit=False)
        db.commit()
    except Exception:
        db.rollback()
        raise

    _set_refresh_cookie(response, refresh_token, request)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=schemas.Token)
async def refresh_token(
    request: Request,
    response: Response,
    data: Optional[schemas.RefreshTokenRequest] = None,
    db: Session = Depends(get_db),
):
    """Get a new access token using a refresh token."""
    ip_address, _user_agent = _extract_request_metadata(request)
    _enforce_auth_rate_limit(
        "refresh_ip",
        ip_address or "unknown",
        _env_int("AUTH_REFRESH_IP_LIMIT", 30, min_value=1, max_value=1000),
        _env_int("AUTH_REFRESH_IP_WINDOW_SECONDS", 300, min_value=30, max_value=86400),
    )

    submitted_refresh_token = _resolve_refresh_token(request, data)
    if not submitted_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is required",
        )

    payload = security.decode_token(submitted_refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token payload",
        )
    user = user_service.get_user_by_id(db, str(user_id))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    refresh_token_hash = _hash_refresh_token(submitted_refresh_token)
    session = db.query(models.RefreshTokenSession).filter(
        models.RefreshTokenSession.token_hash == refresh_token_hash,
        models.RefreshTokenSession.user_id == user.id,
    ).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is not active",
        )

    now = datetime.now(timezone.utc)
    if session.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )
    session_expires_at = _normalize_utc_timestamp(session.expires_at)
    if session_expires_at and session_expires_at < now:
        session.revoked_at = now
        session.revoke_reason = "expired"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired",
        )

    token_jti = payload.get("jti")
    if token_jti and session.token_jti and token_jti != session.token_jti:
        session.revoked_at = now
        session.revoke_reason = "jti_mismatch"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token mismatch",
        )

    session.last_used_at = now
    ip_address, user_agent = _extract_request_metadata(request)
    access_token = security.create_access_token(subject=str(user.id))
    refresh_token = _issue_refresh_token(db, user, request, rotate_from_session=session)
    _set_refresh_cookie(response, refresh_token, request)

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "token_refresh",
        "auth",
        str(user.id),
        details={
            "ip_address": ip_address,
            "user_agent": user_agent,
        },
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    data: Optional[schemas.LogoutRequest] = None,
    db: Session = Depends(get_db),
    current_user_id: str = Depends(security.get_current_user),
):
    """Logout and revoke refresh token sessions."""
    user = user_service.get_user_by_id(db, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    now = datetime.now(timezone.utc)
    ip_address, user_agent = _extract_request_metadata(request)
    revoked_count = 0

    submitted_refresh_token = _resolve_refresh_token(request, data)

    if submitted_refresh_token:
        session = db.query(models.RefreshTokenSession).filter(
            models.RefreshTokenSession.user_id == user.id,
            models.RefreshTokenSession.token_hash == _hash_refresh_token(submitted_refresh_token),
        ).first()
        if session and session.revoked_at is None:
            session.revoked_at = now
            session.revoke_reason = "logout"
            session.last_used_at = now
            revoked_count = 1
            db.commit()
    else:
        sessions = db.query(models.RefreshTokenSession).filter(
            models.RefreshTokenSession.user_id == user.id,
            models.RefreshTokenSession.revoked_at.is_(None),
        ).limit(10000).all()
        for session in sessions:
            session.revoked_at = now
            session.revoke_reason = "logout_all"
            session.last_used_at = now
        revoked_count = len(sessions)
        if sessions:
            db.commit()

    visitor_service.create_audit_log(
        db,
        user.organization_id,
        user.id,
        "logout",
        "auth",
        str(user.id),
        details={
            "revoked_sessions": revoked_count,
            "scope": "single" if data and data.refresh_token else "all",
            "ip_address": ip_address,
            "user_agent": user_agent,
        },
    )
    _clear_refresh_cookie(response, request)

    return {
        "message": "Logged out successfully",
        "revoked_sessions": revoked_count,
    }


@router.get("/me", response_model=schemas.UserWithOrg)
async def get_current_user_info(
    current_user=Depends(security.get_current_active_user),
):
    """Get current authenticated user details."""
    return current_user


@router.get("/login-history", response_model=schemas.PaginatedResponse)
async def get_login_history(
    user_id: Optional[UUID] = None,
    include_failed: bool = True,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    page: int = 1,
    limit: int = 50,
    current_user_id: str = Depends(security.get_current_user),
    db: Session = Depends(get_db),
):
    """Return login audit history (admin only), including IP and user-agent details."""
    user = user_service.get_user_by_id(db, current_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can view login history")

    safe_page = max(page, 1)
    safe_limit = max(1, min(limit, 200))
    skip = (safe_page - 1) * safe_limit

    actions = ["login", "login_failed"] if include_failed else ["login"]
    query = db.query(models.AuditLog).filter(
        models.AuditLog.organization_id == user.organization_id,
        models.AuditLog.action.in_(actions),
    )
    if user_id:
        query = query.filter(models.AuditLog.user_id == user_id)
    if date_from:
        query = query.filter(models.AuditLog.timestamp >= date_from)
    if date_to:
        query = query.filter(models.AuditLog.timestamp <= date_to)

    total = query.count()
    logs = (
        query.order_by(models.AuditLog.timestamp.desc())
        .offset(skip)
        .limit(safe_limit)
        .all()
    )

    pages = (total + safe_limit - 1) // safe_limit
    return schemas.PaginatedResponse(
        items=[schemas.AuditLog.model_validate(log) for log in logs],
        total=total,
        page=safe_page,
        limit=safe_limit,
        pages=pages,
    )


@router.post("/forgot-password")
async def forgot_password(
    data: schemas.ForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Request a password reset.

    If SMTP is configured, the reset token is sent by email.
    For local development fallback, token can still be returned directly when
    ALLOW_PASSWORD_RESET_TOKEN_RESPONSE is enabled.
    """
    ip_address, _user_agent = _extract_request_metadata(request)
    _enforce_auth_rate_limit(
        "forgot_password_ip",
        ip_address or "unknown",
        _env_int("AUTH_FORGOT_PASSWORD_IP_LIMIT", 5, min_value=1, max_value=200),
        _env_int("AUTH_FORGOT_PASSWORD_IP_WINDOW_SECONDS", 3600, min_value=60, max_value=86400),
    )
    _enforce_auth_rate_limit(
        "forgot_password_email",
        data.email,
        _env_int("AUTH_FORGOT_PASSWORD_EMAIL_LIMIT", 3, min_value=1, max_value=100),
        _env_int("AUTH_FORGOT_PASSWORD_EMAIL_WINDOW_SECONDS", 3600, min_value=60, max_value=86400),
    )

    user = user_service.get_user_by_email(db, data.email)
    if not user:
        # Don't reveal whether email exists — return success anyway
        return {"message": "If the email exists, a reset link has been generated.", "reset_token": None}

    # Generate reset token — store only the SHA-256 hash in DB so a DB
    # compromise does not expose usable reset tokens.
    token = security.create_password_reset_token()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires = datetime.now(timezone.utc) + timedelta(hours=1)

    db_token = models.PasswordResetToken(
        user_id=user.id,
        token=token_hash,
        expires_at=expires,
    )
    db.add(db_token)
    db.commit()

    email_sent, email_status = password_reset_email_service.send_password_reset_email(user.email, token)
    if email_sent:
        return {
            "message": "If the email exists, password reset instructions were sent.",
            "reset_token": None,
            "email_delivery": {"sent": True},
        }

    is_production = (os.getenv("SENTINELCV_ENV") or "development").strip().lower() == "production"
    allow_plain_token = (
        not is_production
        and (os.getenv("ALLOW_PASSWORD_RESET_TOKEN_RESPONSE") or "false").strip().lower() in {"1", "true", "yes", "on"}
    )
    if allow_plain_token:
        return {
            "message": "Password reset email delivery is unavailable in this environment; using development fallback token.",
            "reset_token": token,
            "email_delivery": {"sent": False, "reason": email_status},
        }

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Password reset email delivery is not configured",
    )


@router.post("/reset-password")
async def reset_password(
    data: schemas.ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Reset password using a valid reset token."""
    ip_address, _user_agent = _extract_request_metadata(request)
    _enforce_auth_rate_limit(
        "reset_password_ip",
        ip_address or "unknown",
        _env_int("AUTH_RESET_PASSWORD_IP_LIMIT", 8, min_value=1, max_value=200),
        _env_int("AUTH_RESET_PASSWORD_IP_WINDOW_SECONDS", 3600, min_value=60, max_value=86400),
    )

    submitted_hash = hashlib.sha256(data.token.encode("utf-8")).hexdigest()
    reset_record = (
        db.query(models.PasswordResetToken)
        .filter(
            models.PasswordResetToken.token == submitted_hash,
            models.PasswordResetToken.used == False,
        )
        .first()
    )
    if not reset_record:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    reset_expires_at = _normalize_utc_timestamp(reset_record.expires_at)
    if not reset_expires_at or reset_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Reset token has expired")

    user = db.query(models.User).filter(models.User.id == reset_record.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update password
    user.password_hash = security.get_password_hash(data.new_password)
    reset_record.used = True
    db.commit()

    return {"message": "Password has been reset successfully"}
