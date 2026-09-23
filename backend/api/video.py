from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.orm import Session
from db.base import get_db
from models import models
from schemas import schemas
from services import user_service, video_queue_service
from core.security import get_current_user
from uuid import UUID
import os
import uuid
import shutil
import time
import requests
from core.paths import RAW_VIDEO_DIR

router = APIRouter(prefix="/video", tags=["Video"])

UPLOAD_DIR = RAW_VIDEO_DIR
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001")

_ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
_ALLOWED_VIDEO_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/webm",
    # Some browsers send octet-stream for any binary upload
    "application/octet-stream",
}
_AI_MAX_RETRIES = 3
_AI_RETRY_BASE_DELAY = 5  # seconds; doubles each attempt


def trigger_video_processing(org_id: str, video_path: str, job_id: str):
    """Background task: call AI service to process the uploaded video,
    then update the processing job status in the database."""
    from db.base import SessionLocal
    db = SessionLocal()
    job = None
    try:
        job = db.query(models.VideoProcessingJob).filter(
            models.VideoProcessingJob.id == job_id
        ).first()
        if job:
            job.status = "processing"
            job.message = "AI processing in progress..."
            db.commit()

        last_exc: Exception | None = None
        response = None
        for attempt in range(1, _AI_MAX_RETRIES + 1):
            try:
                response = requests.post(
                    f"{AI_SERVICE_URL}/process",
                    json={"organization_id": org_id, "video_path": video_path},
                    timeout=600,
                )
                if response.status_code < 500:
                    break
                last_exc = RuntimeError(
                    f"AI service returned {response.status_code}: {response.text.strip()[:200]}"
                )
            except requests.RequestException as exc:
                last_exc = exc

            if attempt < _AI_MAX_RETRIES:
                delay = _AI_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                print(f"[video] AI service attempt {attempt} failed, retrying in {delay}s: {last_exc}")
                time.sleep(delay)

        if response is not None and response.status_code == 200:
            if job:
                result = response.json()
                job.status = result.get("status", "completed")
                job.message = result.get("message", "Processing completed")
                job.people_detected = result.get("people_detected", 0)
                job.people_identified = result.get("people_identified", 0)
                db.commit()
        else:
            raise last_exc or RuntimeError("AI service did not return a successful response")

    except Exception as e:
        print(f"[video] Failed to process job {job_id}: {e}")
        if job:
            job.status = "error"
            job.message = str(e)[:500]
            db.commit()
    finally:
        db.close()


@router.post("/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a video file and trigger async AI processing."""
    user = user_service.get_user_by_id(db, current_user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    os.makedirs(UPLOAD_DIR, exist_ok=True)

    filename = file.filename if file.filename else "video.mp4"
    file_extension = os.path.splitext(filename)[1].lower()

    if file_extension not in _ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported video format '{file_extension}'. "
                f"Allowed: {', '.join(sorted(_ALLOWED_VIDEO_EXTENSIONS))}"
            ),
        )

    content_type = (file.content_type or "").lower().split(";")[0].strip()
    if content_type and content_type not in _ALLOWED_VIDEO_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content type '{content_type}' for video upload",
        )

    file_id = str(uuid.uuid4())
    file_path = f"{UPLOAD_DIR}/{file_id}{file_extension}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Create processing job record
    job = models.VideoProcessingJob(
        organization_id=user.organization_id,
        file_id=file_id,
        file_path=file_path,
        status="queued",
        message="Video uploaded, queued for processing",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    queue_status = video_queue_service.get_video_job_queue_status()
    if queue_status.get("mode") == "redis":
        enqueued, enqueue_message = video_queue_service.enqueue_video_job(
            str(user.organization_id),
            file_path,
            str(job.id),
        )
        if enqueued:
            job.message = "Video uploaded, queued for Redis worker processing"
            db.commit()
            return {
                "message": "Video uploaded successfully. Queued for worker processing.",
                "file_id": file_id,
                "job_id": str(job.id),
                "processing_mode": "redis",
                "queue_status": enqueue_message,
            }

        job.message = f"Redis queue unavailable ({enqueue_message}); falling back to in-process background task"
        db.commit()

    # Trigger in-process background AI processing
    background_tasks.add_task(
        trigger_video_processing, str(user.organization_id), file_path, str(job.id)
    )

    return {
        "message": "Video uploaded successfully. Processing started.",
        "file_id": file_id,
        "job_id": str(job.id),
        "processing_mode": "background",
        "queue_status": queue_status.get("reason") if queue_status.get("mode") == "redis" else "background_task",
    }


@router.get("/status/{job_id}", response_model=schemas.VideoProcessingJobResponse)
async def get_processing_status(
    job_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the status of a video processing job."""
    user = user_service.get_user_by_id(db, current_user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    job = db.query(models.VideoProcessingJob).filter(
        models.VideoProcessingJob.id == job_id,
        models.VideoProcessingJob.organization_id == user.organization_id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Processing job not found")

    return job


@router.get("/jobs", response_model=schemas.PaginatedResponse)
async def list_processing_jobs(
    page: int = 1,
    limit: int = 20,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all video processing jobs for the user's organization."""
    user = user_service.get_user_by_id(db, current_user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    query = db.query(models.VideoProcessingJob).filter(
        models.VideoProcessingJob.organization_id == user.organization_id,
    )
    total = query.count()
    skip = (page - 1) * limit
    jobs = (
        query.order_by(models.VideoProcessingJob.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    pages = (total + limit - 1) // limit
    return schemas.PaginatedResponse(
        items=[schemas.VideoProcessingJobResponse.model_validate(j) for j in jobs],
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )
