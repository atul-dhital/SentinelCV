from datetime import datetime, timedelta, timezone
from typing import Any, Union, Optional
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
import logging
import os
import secrets
import base64
import hashlib
from dotenv import load_dotenv

from db.base import get_db

load_dotenv()

_logger = logging.getLogger("sentinelcv.security")

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY environment variable must be set. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# ─── Embedding encryption (at rest) ──────────────────────────────────────────
#
# IMPORTANT: this module previously derived the Fernet key directly from
# SECRET_KEY via raw SHA-256. That coupled JWT signing and embedding
# encryption to a single secret — rotating SECRET_KEY destroyed all stored
# embeddings, and a JWT-secret leak became a biometric leak.
#
# The current design:
#   * EMBEDDING_KEY_SECRET is a dedicated secret for embedding encryption.
#     Production must set it explicitly and keep it distinct from SECRET_KEY.
#     Development falls back to a stable dev-only key so local SQLite installs
#     remain usable without coupling JWT signing and biometric encryption.
#   * Keys are derived via HKDF-SHA256 with a per-version `info` context.
#   * Encrypted values are versioned: `v1:<fernet_blob>` for new writes.
#     Reads detect the prefix and dispatch; bare blobs without a prefix
#     are decrypted with the legacy SHA-256(SECRET_KEY) key for
#     backward compatibility, then re-wrapped on the next write.
#
# For PostgreSQL deployments, embeddings are stored in pgvector columns as
# plaintext floats so ANN search can run server-side. Application-level
# encryption of vectors would defeat ANN search. PostgreSQL deployments
# MUST therefore enable storage-level encryption (filesystem TDE, AWS RDS
# `storage_encrypted`, GCP CMEK, or pg_tde) — see PRODUCTION_READINESS.md.

_EMBEDDING_KEY_VERSION = "v1"
_EMBEDDING_KEY_PREFIX = f"{_EMBEDDING_KEY_VERSION}:"
_EMBEDDING_HKDF_INFO = b"sentinelcv-embedding-encryption-v1"
# Fixed application-wide salt is acceptable for HKDF when input keying
# material has high entropy (which our secrets do). The salt's job is
# context separation, not unpredictability.
_EMBEDDING_HKDF_SALT = b"sentinelcv|embedding|v1"

_is_production = os.getenv("SENTINELCV_ENV", "development") == "production"
_embedding_key_secret = os.getenv("EMBEDDING_KEY_SECRET", "").strip()
if not _embedding_key_secret:
    if _is_production:
        raise RuntimeError(
            "EMBEDDING_KEY_SECRET must be set in production and must not reuse SECRET_KEY."
        )
    _logger.warning(
        "EMBEDDING_KEY_SECRET is not set; using a development-only fallback key "
        "that is distinct from SECRET_KEY. Set a dedicated EMBEDDING_KEY_SECRET "
        "before sharing environments or rotating biometric data."
    )
    _embedding_key_secret = "sentinelcv-dev-embedding-key-not-for-production"
elif _embedding_key_secret == SECRET_KEY:
    if _is_production:
        raise RuntimeError(
            "EMBEDDING_KEY_SECRET must be distinct from SECRET_KEY in production."
        )
    _logger.warning(
        "EMBEDDING_KEY_SECRET matches SECRET_KEY; set a dedicated secret to "
        "decouple JWT signing from embedding encryption."
    )


def _derive_fernet_key(secret: str, *, info: bytes, salt: bytes) -> bytes:
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=info,
    ).derive(secret.encode("utf-8"))
    return base64.urlsafe_b64encode(derived)


_fernet_v1 = Fernet(
    _derive_fernet_key(
        _embedding_key_secret,
        info=_EMBEDDING_HKDF_INFO,
        salt=_EMBEDDING_HKDF_SALT,
    )
)

# Legacy key — only ever used for decryption of pre-migration ciphertext.
_fernet_legacy = Fernet(
    base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
)

# Dev-fallback key — used when embeddings were written without EMBEDDING_KEY_SECRET set.
# Allows seamless decryption after key is introduced without a full re-encryption migration.
_DEV_FALLBACK_SECRET = "sentinelcv-dev-embedding-key-not-for-production"
_fernet_dev_fallback: Optional[Fernet] = None
if _embedding_key_secret != _DEV_FALLBACK_SECRET:
    try:
        _fernet_dev_fallback = Fernet(
            _derive_fernet_key(
                _DEV_FALLBACK_SECRET,
                info=_EMBEDDING_HKDF_INFO,
                salt=_EMBEDDING_HKDF_SALT,
            )
        )
    except Exception:
        pass

_fernet = _fernet_v1  # backward-compatible alias (other modules may import it)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def create_access_token(
    subject: Union[str, Any], expires_delta: Optional[timedelta] = None
) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"exp": expire, "sub": str(subject), "type": "access"}
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(
    subject: Union[str, Any],
    expires_delta: Optional[timedelta] = None,
    jti: Optional[str] = None,
) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "type": "refresh",
        "jti": jti or secrets.token_urlsafe(18),
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def hash_password(password: str) -> str:
    """Hash a plain-text password for storage."""
    return get_password_hash(password)


def decode_token(token: str) -> Optional[dict]:
    """Decode JWT and return the full payload."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def get_current_user(token: str = Depends(oauth2_scheme)):
    """FastAPI dependency: extract user_id (subject) from access token."""
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_type = payload.get("type")
    if token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id: Optional[str] = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id


def get_current_active_user(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """FastAPI dependency: load user from DB, enforce is_active.

    Returns the full User ORM object. Prefer this over get_current_user for
    routes that need the user record — it also closes the gap where deactivated
    users could use existing access tokens for up to 30 minutes.
    """
    from models.models import User  # local import to avoid circular deps
    user = db.query(User).filter(User.id == current_user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )
    return user


def require_role(required_role: str):
    """Factory that returns a dependency requiring a specific role.

    Loads the user from the database, checks is_active, and checks the role.
    Admin role always passes. Returns the full User ORM object.

    Usage:
        current_user = Depends(require_role("admin"))
    """
    def _role_checker(current_user=Depends(get_current_active_user)):
        # Admin has full access; otherwise role must match exactly
        if current_user.role != "admin" and current_user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{required_role}' required",
            )
        return current_user
    return _role_checker


# ─── Password Reset ──────────────────────────────────────────────────────────


def create_password_reset_token() -> str:
    """Generate a secure random token for password reset."""
    return secrets.token_urlsafe(32)


# ─── Encryption at Rest ──────────────────────────────────────────────────────


def encrypt_embedding(embedding_json: str) -> str:
    """Encrypt a JSON-serialized embedding using the current key version.

    Output format: ``v1:<urlsafe-base64-fernet-blob>``. Readers must use
    ``decrypt_embedding`` (which dispatches by prefix).
    """
    cipher = _fernet_v1.encrypt(embedding_json.encode("utf-8")).decode("utf-8")
    return f"{_EMBEDDING_KEY_PREFIX}{cipher}"


def decrypt_embedding(encrypted: str) -> str:
    """Decrypt an embedding ciphertext.

    Versioned ciphertext (``v1:...``) is decrypted with the HKDF-derived key.
    Bare ciphertext (no prefix) is treated as legacy and decrypted with the
    raw-SHA256(SECRET_KEY) key.  If both fail, a dev-fallback key is tried so
    that embeddings written before EMBEDDING_KEY_SECRET was configured remain
    readable without a full re-encryption migration.
    """
    if encrypted.startswith(_EMBEDDING_KEY_PREFIX):
        payload = encrypted[len(_EMBEDDING_KEY_PREFIX):]
        try:
            return _fernet_v1.decrypt(payload.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            pass
        # Primary key failed — try dev fallback (covers data written before key was set)
        if _fernet_dev_fallback is not None:
            try:
                result = _fernet_dev_fallback.decrypt(payload.encode("utf-8")).decode("utf-8")
                _logger.warning(
                    "Embedding decrypted via dev-fallback key (v1 prefix) — "
                    "this record needs re-encryption with the current key."
                )
                return result
            except InvalidToken:
                pass
        raise InvalidToken

    # Legacy ciphertext (pre key-versioning).
    try:
        result = _fernet_legacy.decrypt(encrypted.encode("utf-8")).decode("utf-8")
        _logger.warning(
            "Embedding decrypted via legacy key — "
            "this record needs re-encryption with the current key."
        )
        return result
    except InvalidToken:
        pass
    # Last-resort: v1 without prefix or dev fallback without prefix
    try:
        result = _fernet_v1.decrypt(encrypted.encode("utf-8")).decode("utf-8")
        _logger.warning(
            "Embedding decrypted via v1 key (no prefix) — "
            "this record needs re-encryption with the current key."
        )
        return result
    except InvalidToken:
        pass
    if _fernet_dev_fallback is not None:
        result = _fernet_dev_fallback.decrypt(encrypted.encode("utf-8")).decode("utf-8")
        _logger.warning(
            "Embedding decrypted via dev-fallback key (no prefix) — "
            "this record needs re-encryption with the current key."
        )
        return result
    raise InvalidToken


def current_embedding_key_version() -> str:
    """Public accessor for the current embedding-key version label."""
    return _EMBEDDING_KEY_VERSION


# ─── Internal Service Key ─────────────────────────────────────────────────────

_INTERNAL_SERVICE_KEY: str = os.getenv("INTERNAL_SERVICE_KEY", "")


def verify_internal_key(candidate: Optional[str]) -> bool:
    """Constant-time comparison of the submitted internal API key.

    Uses ``secrets.compare_digest`` so the comparison time does not vary with
    how many characters match — preventing a timing oracle from enumerating the
    key character by character.

    Returns ``True`` only when INTERNAL_SERVICE_KEY is non-empty **and** the
    candidate matches exactly.
    """
    if not _INTERNAL_SERVICE_KEY:
        return False
    return secrets.compare_digest(candidate or "", _INTERNAL_SERVICE_KEY)
