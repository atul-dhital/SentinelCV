"""
Celery Batch Processing Pipeline for Video Analysis

Asynchronous task queue for:
- Video frame processing (detection, correlation, liveness)
- Batch face embedding generation
- Analytics aggregation
- Scheduled maintenance tasks
"""

import os
from celery import Celery, shared_task
from celery.schedules import crontab
from celery.signals import task_prerun, task_postrun
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ─── Celery App Configuration ──────────────────────────────────────────────────

celery_app = Celery(
    'sentinelcv',
    broker=os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/1'),
    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://redis:6379/2'),
)

# Celery configuration
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    
    # Task configuration
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes hard limit
    task_soft_time_limit=25 * 60,  # 25 minutes soft limit
    
    # Worker configuration
    worker_prefetch_multiplier=int(os.getenv('CELERY_WORKER_PREFETCH_MULTIPLIER', 4)),
    worker_max_tasks_per_child=1000,
    
    # Result configuration
    result_expires=3600,  # Results expire after 1 hour
    result_extended=True,
)

# ─── Periodic Tasks (Scheduled) ────────────────────────────────────────────────

celery_app.conf.beat_schedule = {
    'cleanup-old-videos': {
        'task': 'backend.services.batch_tasks.cleanup_old_video_files',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2 AM
        'args': (30,),  # Keep 30 days
    },
    'aggregate-daily-statistics': {
        'task': 'backend.services.batch_tasks.aggregate_daily_statistics',
        'schedule': crontab(hour=1, minute=0),  # Daily at 1 AM
    },
    'update-face-embedding-indices': {
        'task': 'backend.services.batch_tasks.update_face_embedding_indices',
        'schedule': crontab(hour=3, minute=0),  # Daily at 3 AM
    },
    'generate-compliance-reports': {
        'task': 'backend.services.batch_tasks.generate_compliance_reports',
        'schedule': crontab(day_of_week=0, hour=4, minute=0),  # Weekly Sunday at 4 AM
    },
    'health-check': {
        'task': 'backend.services.batch_tasks.health_check_workers',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },
}

# ─── Signal Handlers for Monitoring ────────────────────────────────────────────

@task_prerun.connect
def task_prerun_handler(task_id, task, args, kwargs, **extra):
    """Log task execution start."""
    logger.info(f"Task started: {task.name} [{task_id}]")


@task_postrun.connect
def task_postrun_handler(task_id, task, args, kwargs, retval, state, **extra):
    """Log task execution completion."""
    logger.info(f"Task completed: {task.name} [{task_id}] - State: {state}")


# ─── Video Processing Tasks ────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_video_batch(
    self,
    video_path: str,
    organization_id: str,
    camera_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Process video file for face detection, liveness, and recognition.
    
    Args:
        video_path: Path to video file
        organization_id: Organization ID
        camera_id: Camera ID
        metadata: Additional metadata
        
    Returns:
        Processing results dictionary
    """
    try:
        logger.info(f"Processing video: {video_path} for org {organization_id}")
        
        from backend.services.video_queue_service import process_video_file
        
        results = process_video_file(
            video_path=video_path,
            organization_id=organization_id,
            camera_id=camera_id,
            metadata=metadata,
        )
        
        logger.info(f"Video processing completed: {video_path}")
        return {
            'status': 'completed',
            'results': results,
            'timestamp': datetime.utcnow().isoformat(),
        }
        
    except Exception as exc:
        logger.error(f"Video processing failed: {exc}")
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True)
def process_camera_stream(
    self,
    camera_id: str,
    organization_id: str,
    frame_rate: int = 5,
    duration_seconds: int = 60,
) -> Dict[str, Any]:
    """
    Process live camera stream for specified duration.
    
    Args:
        camera_id: Camera ID
        organization_id: Organization ID
        frame_rate: Frames per second to process
        duration_seconds: Process duration
        
    Returns:
        Stream processing results
    """
    try:
        logger.info(f"Processing camera stream: {camera_id}")
        
        from backend.services.rtsp_manager import RTSPManager
        from backend.services.video_queue_service import process_frame_batch
        from backend.db.base import SessionLocal
        
        db = SessionLocal()
        rtsp_manager = RTSPManager()
        
        # Get camera details
        camera = db.query(Camera).filter(
            Camera.id == camera_id,
            Camera.organization_id == organization_id,
        ).first()
        
        if not camera:
            raise ValueError(f"Camera not found: {camera_id}")
        
        # Open RTSP stream
        stream_handle = rtsp_manager.open_stream(camera.rtsp_url)
        frames = []
        frame_times = []
        
        try:
            # Capture frames
            for _ in range(duration_seconds * frame_rate):
                frame = rtsp_manager.read_frame(stream_handle)
                if frame is not None:
                    frames.append(frame)
                    frame_times.append(datetime.utcnow())
        finally:
            rtsp_manager.close_stream(stream_handle)
            db.close()
        
        # Process frames
        if frames:
            results = process_frame_batch(
                frames=frames,
                camera_id=camera_id,
                organization_id=organization_id,
            )
            return {
                'status': 'completed',
                'frames_processed': len(frames),
                'results': results,
            }
        else:
            raise ValueError("No frames captured from stream")
            
    except Exception as exc:
        logger.error(f"Stream processing failed: {exc}")
        return {
            'status': 'failed',
            'error': str(exc),
        }


# ─── Face Embedding Batch Tasks ────────────────────────────────────────────────

@shared_task(bind=True)
def batch_generate_face_embeddings(
    self,
    visitor_ids: List[str],
    organization_id: str,
) -> Dict[str, Any]:
    """
    Generate or update face embeddings for multiple visitors.
    
    Args:
        visitor_ids: List of visitor IDs
        organization_id: Organization ID
        
    Returns:
        Generation results
    """
    try:
        logger.info(f"Generating embeddings for {len(visitor_ids)} visitors")
        
        from backend.db.base import SessionLocal
        from backend.models.models import Visitor, FaceData
        from backend.services.recognition_service import extract_embedding
        
        db = SessionLocal()
        results = {'processed': 0, 'failed': 0, 'skipped': 0}
        
        try:
            for visitor_id in visitor_ids:
                visitor = db.query(Visitor).filter(
                    Visitor.id == visitor_id,
                    Visitor.organization_id == organization_id,
                ).first()
                
                if not visitor:
                    results['skipped'] += 1
                    continue
                
                # Check if face data exists
                face_data = db.query(FaceData).filter(
                    FaceData.visitor_id == visitor_id,
                ).first()
                
                if not face_data or not face_data.face_image_path:
                    results['skipped'] += 1
                    continue
                
                try:
                    # Extract embeddings
                    embedding = extract_embedding(face_data.face_image_path)
                    if embedding is not None:
                        face_data.embedding = embedding
                        results['processed'] += 1
                except Exception as e:
                    logger.warning(f"Failed to extract embedding for {visitor_id}: {e}")
                    results['failed'] += 1
            
            db.commit()
        finally:
            db.close()
        
        return {
            'status': 'completed',
            'results': results,
        }
        
    except Exception as exc:
        logger.error(f"Batch embedding generation failed: {exc}")
        return {
            'status': 'failed',
            'error': str(exc),
        }


# ─── Analytics Aggregation Tasks ────────────────────────────────────────────────

@shared_task(bind=True)
def aggregate_daily_statistics(self) -> Dict[str, Any]:
    """Aggregate daily statistics for all organizations."""
    try:
        logger.info("Aggregating daily statistics")
        
        from backend.db.base import SessionLocal
        from backend.models.models import Organization, VisitorLog
        from backend.services.analytics_service import compute_organization_stats
        from backend.services.cache_service import AnalyticsCacheManager, get_cache
        
        db = SessionLocal()
        cache = AnalyticsCacheManager(get_cache())
        results = {'processed': 0, 'failed': 0}
        
        try:
            # Get all organizations
            orgs = db.query(Organization).all()
            
            for org in orgs:
                try:
                    # Compute stats
                    stats = compute_organization_stats(
                        db=db,
                        organization_id=str(org.id),
                        time_window='24h',
                    )
                    
                    # Cache results (6 hour TTL)
                    cache.set_visitor_stats(
                        org_id=str(org.id),
                        stats=stats,
                        time_window='24h',
                        ttl=6 * 3600,
                    )
                    
                    results['processed'] += 1
                    logger.info(f"Aggregated stats for org {org.id}")
                    
                except Exception as e:
                    logger.error(f"Failed to aggregate stats for org {org.id}: {e}")
                    results['failed'] += 1
        finally:
            db.close()
        
        return {
            'status': 'completed',
            'results': results,
        }
        
    except Exception as exc:
        logger.error(f"Daily statistics aggregation failed: {exc}")
        return {
            'status': 'failed',
            'error': str(exc),
        }


# ─── Maintenance Tasks ──────────────────────────────────────────────────────────

@shared_task(bind=True)
def cleanup_old_video_files(self, retention_days: int = 30) -> Dict[str, Any]:
    """Delete video files older than retention period."""
    try:
        logger.info(f"Cleaning up videos older than {retention_days} days")
        
        import os
        from pathlib import Path
        
        video_dir = Path("/app/data/raw_videos")
        if not video_dir.exists():
            return {'status': 'skipped', 'reason': 'Video directory not found'}
        
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
        deleted = 0
        failed = 0
        
        for video_file in video_dir.glob("**/*.mp4"):
            try:
                file_mtime = datetime.fromtimestamp(video_file.stat().st_mtime)
                if file_mtime < cutoff_date:
                    video_file.unlink()
                    deleted += 1
                    logger.debug(f"Deleted old video: {video_file}")
            except Exception as e:
                logger.error(f"Failed to delete {video_file}: {e}")
                failed += 1
        
        return {
            'status': 'completed',
            'deleted': deleted,
            'failed': failed,
        }
        
    except Exception as exc:
        logger.error(f"Video cleanup failed: {exc}")
        return {
            'status': 'failed',
            'error': str(exc),
        }


@shared_task
def health_check_workers() -> Dict[str, Any]:
    """Health check for all workers."""
    try:
        from celery.app.utils import Settings
        
        active_tasks = celery_app.control.inspect().active()
        registered_tasks = celery_app.control.inspect().registered()
        
        return {
            'status': 'healthy',
            'active_tasks': len(active_tasks or {}),
            'registered_tasks': len(registered_tasks or {}),
            'timestamp': datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.error(f"Health check failed: {exc}")
        return {
            'status': 'unhealthy',
            'error': str(exc),
        }


# ─── Task Monitoring Utilities ─────────────────────────────────────────────────

def submit_video_processing_job(
    video_path: str,
    organization_id: str,
    camera_id: str,
    priority: str = 'normal',
) -> str:
    """
    Submit a video processing job to the queue.
    
    Args:
        video_path: Path to video file
        organization_id: Organization ID
        camera_id: Camera ID
        priority: Task priority ('low', 'normal', 'high')
        
    Returns:
        Task ID for tracking
    """
    priority_level = {'low': 9, 'normal': 5, 'high': 1}.get(priority, 5)
    
    task = process_video_batch.apply_async(
        args=[video_path, organization_id, camera_id],
        priority=priority_level,
        task_id=f"video-{organization_id}-{camera_id}-{datetime.utcnow().timestamp()}",
    )
    
    logger.info(f"Submitted video processing job: {task.id}")
    return task.id


def get_task_status(task_id: str) -> Dict[str, Any]:
    """Get status of a submitted task."""
    from celery.result import AsyncResult
    
    task_result = AsyncResult(task_id, app=celery_app)
    
    return {
        'task_id': task_id,
        'state': task_result.state,
        'result': task_result.result if task_result.state == 'SUCCESS' else None,
        'error': str(task_result.info) if task_result.state == 'FAILURE' else None,
    }
