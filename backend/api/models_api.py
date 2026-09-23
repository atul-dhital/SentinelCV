from datetime import datetime, timedelta, timezone
"""Model management API — retraining, embedding refresh, batch upload, quality checks, augmentation."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
from db.base import get_db
from models import models
from services import visitor_service, user_service
from core.security import get_current_user
from schemas import schemas
from typing import List, Dict
from uuid import UUID
from io import BytesIO
import os
import requests
from core.paths import DATA_DIR, FACE_IMAGE_DIR
from core.storage import storage

router = APIRouter(prefix="/models", tags=["Models"])

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001")


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _check_image_quality(file_path: str) -> schemas.ImageQualityResult:
    """US-TRN-003: Check image quality — min 200x200, blur detection, brightness/contrast."""
    issues = []
    width, height = 0, 0
    try:
        from PIL import Image
        img = Image.open(file_path)
        width, height = img.size

        # Min resolution check
        if width < 200 or height < 200:
            issues.append(f"Image too small ({width}x{height}), minimum 200x200 required")

        # Convert to grayscale for analysis
        import numpy as np
        gray = np.array(img.convert("L"), dtype=np.float64)

        # Blur detection (Laplacian variance)
        from scipy.ndimage import laplace
        lap_var = laplace(gray).var()
        if lap_var < 50:
            issues.append(f"Image is too blurry (variance: {lap_var:.1f}, min: 50)")

        # Brightness check
        mean_brightness = gray.mean()
        if mean_brightness < 40:
            issues.append(f"Image is too dark (brightness: {mean_brightness:.0f})")
        elif mean_brightness > 220:
            issues.append(f"Image is too bright (brightness: {mean_brightness:.0f})")

        # Contrast check
        contrast = gray.std()
        if contrast < 20:
            issues.append(f"Image has low contrast (std: {contrast:.1f})")

    except ImportError:
        # If PIL/numpy/scipy not available, just check file exists
        pass
    except Exception as e:
        issues.append(f"Error analyzing image: {str(e)}")

    return schemas.ImageQualityResult(
        filename=os.path.basename(file_path),
        passed=len(issues) == 0,
        width=width,
        height=height,
        issues=issues,
    )


def _validate_media_strict(file_path: str, config: schemas.MediaValidationConfig = None) -> schemas.MediaValidationResult:
    """US-FUT-022: Strict media validation for uploads - blur, brightness, face size, corruption, duplicates."""
    if config is None:
        config = schemas.MediaValidationConfig()
    
    issues = []
    blur_score = None
    brightness = None
    contrast = None
    face_size = None
    is_corrupt = False
    
    try:
        from PIL import Image
        import numpy as np
        try:
            img = Image.open(file_path)
            img.verify()
            img = Image.open(file_path)
        except Exception:
            is_corrupt = True
            issues.append("Image file is corrupted or unreadable")
            return schemas.MediaValidationResult(
                valid=False if config.strict_mode else True,
                issues=issues,
                is_corrupt=is_corrupt,
            )
        
        width, height = img.size
        face_size = min(width, height)
        
        if face_size < config.min_face_size_pixels:
            issues.append(f"Face area too small ({face_size}px), minimum {config.min_face_size_pixels}px required")
        
        gray = np.array(img.convert("L"), dtype=np.float64)
        
        # Blur detection (Laplacian variance)
        try:
            from scipy.ndimage import laplace
            lap_var = laplace(gray).var()
            blur_score = lap_var
            if lap_var < config.min_blur_threshold:
                issues.append(f"Image is too blurry (variance: {lap_var:.1f}, min: {config.min_blur_threshold})")
        except ImportError:
            pass
        
        # Brightness check
        mean_brightness = gray.mean()
        brightness = mean_brightness
        if mean_brightness < config.min_brightness:
            issues.append(f"Image is too dark (brightness: {mean_brightness:.0f}, min: {config.min_brightness})")
        elif mean_brightness > config.max_brightness:
            issues.append(f"Image is too bright (brightness: {mean_brightness:.0f}, max: {config.max_brightness})")
        
        # Contrast check
        mean_contrast = gray.std()
        contrast = mean_contrast
        if mean_contrast < config.min_contrast:
            issues.append(f"Image has low contrast (std: {mean_contrast:.1f}, min: {config.min_contrast})")
    
    except ImportError:
        # If PIL/numpy not available, skip validation
        pass
    except Exception as e:
        issues.append(f"Error analyzing image: {str(e)}")
    
    valid = len(issues) == 0 if config.strict_mode else True
    
    return schemas.MediaValidationResult(
        valid=valid,
        issues=issues,
        blur_score=blur_score,
        brightness=brightness,
        contrast=contrast,
        face_size_pixels=face_size,
        is_corrupt=is_corrupt,
    )


@router.post("/retrain")
async def retrain_all(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Re-generate embeddings for ALL face images in the organization.
    This triggers a full model refresh — useful after updating the AI model
    or after bulk-importing new face images via the filesystem.

    Admin only.
    """
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can trigger full retrain")

    # Get all face data for the organization
    face_records = (
        db.query(models.FaceData)
        .join(models.Visitor)
        .filter(models.Visitor.organization_id == user.organization_id)
        .limit(100000).all()
    )

    if not face_records:
        return {
            "message": "No face data found in organization",
            "retrained": 0,
            "skipped": 0,
            "errors": [],
        }

    retrained = 0
    skipped = 0
    errors: List[str] = []

    for face in face_records:
        if not face.image_url:
            skipped += 1
            continue

        try:
            image_path = str(storage.ensure_local_file(face.image_url))
        except FileNotFoundError:
            skipped += 1
            errors.append(f"Image not found: {face.image_url}")
            continue
        except RuntimeError as exc:
            skipped += 1
            errors.append(f"Could not access image {face.image_url}: {exc}")
            continue

        try:
            resp = requests.post(
                f"{AI_SERVICE_URL}/embed-face",
                json={"image_path": image_path},
                timeout=60,
            )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("embedding"):
                    face.embedding = visitor_service.serialize_embedding_for_storage(result["embedding"])
                    face.quality_score = result.get("quality_score", face.quality_score)
                    retrained += 1
                elif result.get("error"):
                    errors.append(f"{face.image_url}: {result['error']}")
                    skipped += 1
            else:
                errors.append(f"{face.image_url}: AI service returned status {resp.status_code}")
                skipped += 1
        except requests.exceptions.ConnectionError:
            raise HTTPException(
                status_code=503,
                detail="AI service is not available. Please ensure the AI service is running.",
            )
        except Exception as e:
            errors.append(f"{face.image_url}: {str(e)}")
            skipped += 1

    db.commit()

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "retrain",
        "model", None,
        details={"retrained": retrained, "skipped": skipped, "errors": errors[:10]},
    )

    return {
        "message": f"Retrained {retrained} embedding(s), skipped {skipped}",
        "retrained": retrained,
        "skipped": skipped,
        "errors": errors[:20],
    }


@router.post("/import-directory")
async def import_from_directory(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Scan the known/ face image directory and register any unregistered images
    as new face data entries for matching visitors.

    Images should follow the naming convention: {visitor_id}_{name}.jpg
    or {visitor_name}.jpg

    Admin only.
    """
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can import from directory")

    known_dir = os.path.join(FACE_IMAGE_DIR, "known")
    if not os.path.exists(known_dir):
        return {"message": "No known/ directory found", "imported": 0, "errors": []}

    # Get all existing image_urls to skip already-registered images
    existing_urls = set()
    faces = (
        db.query(models.FaceData.image_url)
        .join(models.Visitor)
        .filter(models.Visitor.organization_id == user.organization_id)
        .limit(100000).all()
    )
    for (url,) in faces:
        if url:
            existing_urls.add(url)

    imported = 0
    errors: List[str] = []
    valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
    face_counts: Dict[str, int] = {}

    for filename in os.listdir(known_dir):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in valid_exts:
            continue

        image_url = f"face_images/known/{filename}"
        if image_url in existing_urls:
            continue  # Already registered

        image_path = os.path.join(known_dir, filename)

        # Try to match visitor by name from filename
        # Convention: {id}_{name}.jpg or {name}.jpg
        name_part = os.path.splitext(filename)[0]
        parts = name_part.split("_", 1)
        visitor_name = parts[-1].replace("_", " ") if len(parts) > 1 else name_part.replace("_", " ")

        # Find visitor by name (case-insensitive)
        visitor = (
            db.query(models.Visitor)
            .filter(
                models.Visitor.organization_id == user.organization_id,
                models.Visitor.name.ilike(f"%{visitor_name}%"),
            )
            .first()
        )

        if not visitor:
            errors.append(f"{filename}: No matching visitor found for name '{visitor_name}'")
            continue

        visitor_key = str(visitor.id)
        current_count = face_counts.get(visitor_key)
        if current_count is None:
            current_count = visitor_service.get_face_data_count(db, visitor.id)
        if current_count >= visitor_service.MAX_FACE_DATA_PER_VISITOR:
            errors.append(f"{filename}: Face data limit reached for visitor '{visitor.name}'")
            continue

        # Generate embedding via AI service
        try:
            resp = requests.post(
                f"{AI_SERVICE_URL}/embed-face",
                json={"image_path": image_path},
                timeout=60,
            )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("error"):
                    errors.append(f"{filename}: {result['error']}")
                    continue
                embedding = result.get("embedding")
                if not embedding:
                    errors.append(f"{filename}: No embedding generated")
                    continue

                quality_score = result.get("quality_score", 0.0)
                visitor_service.create_face_data(
                    db,
                    visitor.id,
                    embedding,
                    image_url=image_url,
                    quality_score=quality_score,
                    face_angle=result.get("face_angle"),
                    is_primary=len(visitor_service.get_face_data_for_visitor(db, visitor.id)) == 0,
                )
                imported += 1
                face_counts[visitor_key] = current_count + 1
            else:
                errors.append(f"{filename}: AI service returned status {resp.status_code}")
        except requests.exceptions.ConnectionError:
            raise HTTPException(
                status_code=503,
                detail="AI service is not available.",
            )

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "import_directory",
        "face_data", None,
        details={"imported": imported, "errors": errors[:10]},
    )

    return {
        "message": f"Imported {imported} face image(s) from known/ directory",
        "imported": imported,
        "errors": errors[:20],
    }


# ─── S14: Training Data Management (US-TRN-002 … US-TRN-006) ────────────────


@router.post("/batch-upload/{visitor_id}", response_model=schemas.BatchUploadResult)
async def batch_upload_faces(
    visitor_id: UUID,
    files: List[UploadFile] = File(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-TRN-002: Batch upload up to 50 training images for a visitor."""
    user = _get_user(db, current_user_id)

    visitor = db.query(models.Visitor).filter(
        models.Visitor.id == visitor_id,
        models.Visitor.organization_id == user.organization_id,
    ).first()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    if len(files) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 images per batch upload")

    remaining = (
        visitor_service.MAX_FACE_DATA_PER_VISITOR
        - visitor_service.get_face_data_count(db, visitor_id)
    )
    if remaining <= 0:
        raise HTTPException(
            status_code=400,
            detail=(
                "Visitor already has the maximum number of face images "
                f"({visitor_service.MAX_FACE_DATA_PER_VISITOR})."
            ),
        )

    results: List[schemas.ImageQualityResult] = []
    successful = 0
    failed = 0

    for file in files:
        if remaining <= 0:
            results.append(schemas.ImageQualityResult(
                filename=file.filename or "unknown",
                passed=False,
                width=0,
                height=0,
                issues=[
                    "Face data limit reached. Remove an image before adding more.",
                ],
            ))
            failed += 1
            continue
        ext = os.path.splitext(file.filename or "img.jpg")[1].lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
            results.append(schemas.ImageQualityResult(
                filename=file.filename or "unknown",
                passed=False,
                width=0,
                height=0,
                issues=[f"Unsupported format: {ext}"],
            ))
            failed += 1
            continue

        # Save temp file
        import uuid as _uuid
        safe_name = f"{_uuid.uuid4().hex}{ext}"
        relative_path = f"face_images/known/{visitor_id}/{safe_name}"
        content = await file.read()
        file_path = str(
            storage.save_file(
                relative_path,
                content,
                content_type=file.content_type or "application/octet-stream",
            )
        )

        # Quality check
        quality = _check_image_quality(file_path)
        quality.filename = file.filename or safe_name
        results.append(quality)

        if not quality.passed:
            storage.delete_file(relative_path)
            failed += 1
            continue

        # Generate embedding via AI service
        try:
            resp = requests.post(
                f"{AI_SERVICE_URL}/embed-face",
                json={"image_path": file_path},
                timeout=60,
            )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("embedding"):
                    image_url = relative_path
                    existing = visitor_service.get_face_data_for_visitor(db, visitor_id)
                    visitor_service.create_face_data(
                        db,
                        visitor_id,
                        result["embedding"],
                        image_url=image_url,
                        quality_score=result.get("quality_score", 0.0),
                        face_angle=result.get("face_angle"),
                        is_primary=len(existing) == 0,
                    )
                    successful += 1
                    remaining -= 1
                else:
                    quality.passed = False
                    quality.issues.append(result.get("error", "No embedding generated"))
                    storage.delete_file(relative_path)
                    failed += 1
            else:
                quality.passed = False
                quality.issues.append(f"AI service error: {resp.status_code}")
                storage.delete_file(relative_path)
                failed += 1
        except requests.exceptions.ConnectionError:
            storage.delete_file(relative_path)
            raise HTTPException(status_code=503, detail="AI service is not available")

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "batch_upload",
        "face_data", str(visitor_id),
        details={"successful": successful, "failed": failed, "total": len(files)},
    )

    return schemas.BatchUploadResult(
        successful=successful,
        failed=failed,
        total=len(files),
        results=results,
    )


@router.post("/quality-check", response_model=List[schemas.ImageQualityResult])
async def quality_check(
    files: List[UploadFile] = File(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-TRN-003: Check image quality without saving — returns quality report per image."""
    _get_user(db, current_user_id)  # auth check

    results: List[schemas.ImageQualityResult] = []
    tmp_dir = os.path.join(DATA_DIR, "tmp_quality_check")
    os.makedirs(tmp_dir, exist_ok=True)

    for file in files:
        import uuid as _uuid
        ext = os.path.splitext(file.filename or "img.jpg")[1].lower()
        tmp_path = os.path.join(tmp_dir, f"{_uuid.uuid4().hex}{ext}")
        try:
            with open(tmp_path, "wb") as f:
                content = await file.read()
                f.write(content)
            quality = _check_image_quality(tmp_path)
            quality.filename = file.filename or "unknown"
            results.append(quality)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # Clean up tmp dir if empty
    try:
        os.rmdir(tmp_dir)
    except OSError:
        pass

    return results


@router.get("/training-stats", response_model=schemas.TrainingStatsResponse)
async def training_stats(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-TRN-005: Return training data statistics for the organization."""
    user = _get_user(db, current_user_id)
    org_id = user.organization_id

    total_visitors = (
        db.query(func.count(models.Visitor.id))
        .filter(models.Visitor.organization_id == org_id)
        .scalar() or 0
    )

    # Visitors with at least 1 face embedding
    visitors_with_faces_q = (
        db.query(models.FaceData.visitor_id)
        .join(models.Visitor)
        .filter(models.Visitor.organization_id == org_id)
        .distinct()
    )
    visitors_with_faces = visitors_with_faces_q.count()

    total_images = (
        db.query(func.count(models.FaceData.id))
        .join(models.Visitor)
        .filter(models.Visitor.organization_id == org_id)
        .scalar() or 0
    )

    avg_images = round(total_images / visitors_with_faces, 1) if visitors_with_faces else 0.0

    avg_quality = (
        db.query(func.avg(models.FaceData.quality_score))
        .join(models.Visitor)
        .filter(models.Visitor.organization_id == org_id)
        .scalar() or 0.0
    )

    # Per-visitor breakdown
    per_visitor = []
    visitors = db.query(models.Visitor).filter(
        models.Visitor.organization_id == org_id
    ).limit(100000).all()
    for v in visitors:
        faces = visitor_service.get_face_data_for_visitor(db, v.id)
        per_visitor.append({
            "visitor_id": str(v.id),
            "visitor_name": v.name,
            "image_count": len(faces),
            "avg_quality": round(sum(f.quality_score or 0 for f in faces) / max(len(faces), 1), 2),
        })

    return schemas.TrainingStatsResponse(
        total_visitors=total_visitors,
        visitors_with_faces=visitors_with_faces,
        total_images=total_images,
        avg_images_per_visitor=avg_images,
        avg_quality_score=round(float(avg_quality), 2),
        per_visitor=per_visitor,
    )


@router.post("/augment/{visitor_id}", response_model=schemas.AugmentationResult)
async def augment_training_data(
    visitor_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """US-TRN-006: Apply data augmentation (flip, brightness, rotation) to
    existing training images for a visitor, creating additional training samples."""
    user = _get_user(db, current_user_id)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can augment data")

    visitor = db.query(models.Visitor).filter(
        models.Visitor.id == visitor_id,
        models.Visitor.organization_id == user.organization_id,
    ).first()
    if not visitor:
        raise HTTPException(status_code=404, detail="Visitor not found")

    faces = visitor_service.get_face_data_for_visitor(db, visitor_id)
    if not faces:
        raise HTTPException(status_code=400, detail="Visitor has no training images to augment")

    generated = 0
    errors_list: List[str] = []
    techniques_used = set()

    try:
        from PIL import Image, ImageEnhance
        import numpy as np
    except ImportError:
        return schemas.AugmentationResult(
            original_count=len(faces),
            generated_count=0,
            techniques_used=[],
            errors=["PIL/numpy not installed — cannot augment"],
        )

    for face in faces:
        if not face.image_url:
            continue
        try:
            image_path = str(storage.ensure_local_file(face.image_url))
        except FileNotFoundError:
            errors_list.append(f"Missing: {face.image_url}")
            continue
        except RuntimeError as exc:
            errors_list.append(f"{face.image_url}: {exc}")
            continue

        try:
            img = Image.open(image_path)
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            image_dir = os.path.dirname(face.image_url.replace("\\", "/"))

            augmentations = {
                "flip": img.transpose(Image.FLIP_LEFT_RIGHT),
                "bright": ImageEnhance.Brightness(img).enhance(1.3),
                "dark": ImageEnhance.Brightness(img).enhance(0.7),
                "rotate5": img.rotate(5, expand=False, fillcolor=(0, 0, 0)),
                "rotate_n5": img.rotate(-5, expand=False, fillcolor=(0, 0, 0)),
            }

            for aug_name, aug_img in augmentations.items():
                aug_filename = f"{base_name}_{aug_name}.jpg"
                aug_relative_path = f"{image_dir}/{aug_filename}"
                try:
                    storage.ensure_local_file(aug_relative_path)
                    continue
                except FileNotFoundError:
                    pass
                except RuntimeError as exc:
                    errors_list.append(f"{aug_relative_path}: {exc}")
                    continue

                buffer = BytesIO()
                aug_img.save(buffer, "JPEG", quality=95)
                aug_path = str(
                    storage.save_file(
                        aug_relative_path,
                        buffer.getvalue(),
                        content_type="image/jpeg",
                    )
                )

                # Generate embedding for augmented image
                try:
                    resp = requests.post(
                        f"{AI_SERVICE_URL}/embed-face",
                        json={"image_path": aug_path},
                        timeout=60,
                    )
                    if resp.status_code == 200:
                        result = resp.json()
                        if result.get("embedding"):
                            visitor_service.create_face_data(
                                db, visitor_id, result["embedding"],
                                image_url=aug_relative_path,
                                quality_score=result.get("quality_score", 0.0),
                                face_angle=result.get("face_angle"),
                            )
                            generated += 1
                            techniques_used.add(aug_name)
                        else:
                            storage.delete_file(aug_relative_path)
                except requests.exceptions.ConnectionError:
                    raise HTTPException(status_code=503, detail="AI service is not available")
        except Exception as e:
            errors_list.append(f"{face.image_url}: {str(e)}")

    visitor_service.create_audit_log(
        db, user.organization_id, user.id, "augment",
        "face_data", str(visitor_id),
        details={"generated": generated, "techniques": list(techniques_used)},
    )

    return schemas.AugmentationResult(
        original_count=len(faces),
        generated_count=generated,
        techniques_used=list(techniques_used),
        errors=errors_list[:20],
    )
