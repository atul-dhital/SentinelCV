from fastapi import HTTPException
from sqlalchemy.orm import Session
from models import models
from schemas import schemas
from core import security
from typing import Optional


def authenticate_user(db: Session, email: str, password: str) -> Optional[models.User]:
    """Authenticate a user by email and password."""
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        return None
    if not user.is_active:
        return None
    if not security.verify_password(password, user.password_hash):
        return None
    return user


def create_user(db: Session, user: schemas.UserCreate, *, commit: bool = True) -> models.User:
    """Create a new user with hashed password."""
    org_exists = db.query(models.Organization.id).filter(
        models.Organization.id == user.organization_id
    ).first()
    if not org_exists:
        raise HTTPException(status_code=404, detail="Organization not found")

    hashed_password = security.get_password_hash(user.password)
    db_user = models.User(
        email=user.email,
        full_name=user.full_name,
        password_hash=hashed_password,
        organization_id=user.organization_id,
        role=user.role,
    )
    db.add(db_user)
    if commit:
        db.commit()
        db.refresh(db_user)
    else:
        db.flush()
    return db_user


def get_user_by_id(db: Session, user_id: str) -> Optional[models.User]:
    """Get a user by their UUID string."""
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_user_by_email(db: Session, email: str) -> Optional[models.User]:
    """Get a user by email."""
    return db.query(models.User).filter(models.User.email == email).first()
