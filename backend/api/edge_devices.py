from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from uuid import UUID

from db.base import get_db
from core.security import get_current_user
from models import models
from schemas import schemas
from services import user_service, edge_device_service

router = APIRouter(prefix="/edge-devices", tags=["Edge Devices"])
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8001")


def _get_user(db: Session, user_id: str) -> models.User:
    user = user_service.get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def _require_admin(user: models.User) -> None:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can manage edge devices")


def _get_device_by_token(
    edge_token: Optional[str],
    db: Session,
) -> models.EdgeDevice:
    if not edge_token:
        raise HTTPException(status_code=401, detail="Missing edge device token")
    device = edge_device_service.find_device_by_token(db, edge_token)
    if not device:
        raise HTTPException(status_code=401, detail="Invalid edge device token")
    if not device.is_active:
        raise HTTPException(status_code=403, detail="Edge device is disabled")
    return device


def _serialize_edge_device(device: models.EdgeDevice) -> schemas.EdgeDevice:
    payload = {
        "id": device.id,
        "organization_id": device.organization_id,
        "name": device.name,
        "device_type": device.device_type,
        "location": device.location,
        "endpoint_url": device.endpoint_url,
        "ip_address": device.ip_address,
        "serial_number": device.serial_number,
        "hardware_info": device.hardware_info or {},
        "tags": device.tags or [],
        "model_version_id": device.model_version_id,
        "model_artifact_path": device.model_artifact_path,
        "device_config": device.model_config or {},
        "status": device.status,
        "is_active": device.is_active,
        "token_prefix": device.token_prefix,
        "last_seen": device.last_seen,
        "last_metrics": device.last_metrics or {},
        "last_sync_at": device.last_sync_at,
        "last_sync_count": int(device.last_sync_count or 0),
        "last_sync_status": device.last_sync_status or "never",
        "last_export_at": device.last_export_at,
        "last_export_status": device.last_export_status,
        "last_export_path": device.last_export_path,
        "last_export_details": device.last_export_details or {},
        "created_at": device.created_at,
        "updated_at": device.updated_at,
    }
    return schemas.EdgeDevice.model_validate(payload)


class EdgeDeviceDeploymentRequest(BaseModel):
    model_version_id: Optional[UUID] = None
    deployment_config: Dict[str, Any] = Field(default_factory=dict)


class EdgeDeviceDeploymentResponse(BaseModel):
    device: schemas.EdgeDevice
    deployed_model_version_id: UUID
    deployed_model_name: str
    model_type: str
    artifact_path: Optional[str] = None
    deployed_at: Optional[datetime] = None


class EdgeDeviceSummaryResponse(BaseModel):
    total_devices: int
    online_devices: int
    offline_devices: int
    error_devices: int
    deployed_devices: int
    devices_with_recent_sync: int
    last_seen_at: Optional[datetime] = None
    recent_events: List[schemas.EdgeDeviceEventResponse] = Field(default_factory=list)


@router.get("/", response_model=List[schemas.EdgeDevice])
async def list_edge_devices(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    devices = db.query(models.EdgeDevice).filter(
        models.EdgeDevice.organization_id == user.organization_id
    ).order_by(models.EdgeDevice.created_at.desc()).limit(10000).all()
    return [_serialize_edge_device(device) for device in devices]


@router.post("/", response_model=schemas.EdgeDeviceTokenResponse)
async def create_edge_device(
    request: schemas.EdgeDeviceCreate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    _require_admin(user)

    token, token_hash, token_prefix = edge_device_service.generate_device_token()

    device = models.EdgeDevice(
        organization_id=user.organization_id,
        name=request.name,
        device_type=request.device_type,
        location=request.location,
        endpoint_url=request.endpoint_url,
        ip_address=request.ip_address,
        serial_number=request.serial_number,
        hardware_info=request.hardware_info or {},
        tags=request.tags or [],
        model_version_id=request.model_version_id,
        model_artifact_path=request.model_artifact_path,
        model_config=request.device_config or {},
        status="offline",
        token_hash=token_hash,
        token_prefix=token_prefix,
    )
    db.add(device)
    db.commit()
    db.refresh(device)

    return schemas.EdgeDeviceTokenResponse(
        device=_serialize_edge_device(device),
        device_token=token,
    )


@router.get("/{device_id}", response_model=schemas.EdgeDevice)
async def get_edge_device(
    device_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    device = db.query(models.EdgeDevice).filter(
        models.EdgeDevice.id == device_id,
        models.EdgeDevice.organization_id == user.organization_id,
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Edge device not found")
    return _serialize_edge_device(device)


@router.put("/{device_id}", response_model=schemas.EdgeDevice)
async def update_edge_device(
    device_id: UUID,
    request: schemas.EdgeDeviceUpdate,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    _require_admin(user)
    device = db.query(models.EdgeDevice).filter(
        models.EdgeDevice.id == device_id,
        models.EdgeDevice.organization_id == user.organization_id,
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Edge device not found")

    update_data = request.model_dump(exclude_unset=True)
    device_config = update_data.pop("device_config", None)
    for key, value in update_data.items():
        setattr(device, key, value)
    if device_config is not None:
        device.model_config = device_config

    device.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(device)
    return _serialize_edge_device(device)


@router.delete("/{device_id}")
async def delete_edge_device(
    device_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    _require_admin(user)

    device = db.query(models.EdgeDevice).filter(
        models.EdgeDevice.id == device_id,
        models.EdgeDevice.organization_id == user.organization_id,
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Edge device not found")

    db.delete(device)
    db.commit()
    return {"message": "Edge device deleted"}


@router.post("/{device_id}/rotate-token", response_model=schemas.EdgeDeviceTokenResponse)
async def rotate_edge_device_token(
    device_id: UUID,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    _require_admin(user)

    device = db.query(models.EdgeDevice).filter(
        models.EdgeDevice.id == device_id,
        models.EdgeDevice.organization_id == user.organization_id,
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Edge device not found")

    token, token_hash, token_prefix = edge_device_service.generate_device_token()
    device.token_hash = token_hash
    device.token_prefix = token_prefix
    device.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(device)

    return schemas.EdgeDeviceTokenResponse(
        device=_serialize_edge_device(device),
        device_token=token,
    )


@router.get("/{device_id}/events", response_model=List[schemas.EdgeDeviceEventResponse])
async def list_edge_device_events(
    device_id: UUID,
    limit: int = 50,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    events = db.query(models.EdgeDeviceEvent).filter(
        models.EdgeDeviceEvent.edge_device_id == device_id,
        models.EdgeDeviceEvent.organization_id == user.organization_id,
    ).order_by(models.EdgeDeviceEvent.created_at.desc()).limit(limit).all()
    return events


@router.get("/dashboard/summary", response_model=EdgeDeviceSummaryResponse)
async def get_edge_device_summary(
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    summary = edge_device_service.build_device_summary(db, user.organization_id)
    return EdgeDeviceSummaryResponse(
        total_devices=summary.total_devices,
        online_devices=summary.online_devices,
        offline_devices=summary.offline_devices,
        error_devices=summary.error_devices,
        deployed_devices=summary.deployed_devices,
        devices_with_recent_sync=summary.devices_with_recent_sync,
        last_seen_at=summary.last_seen_at,
        recent_events=[
            schemas.EdgeDeviceEventResponse.model_validate(event)
            for event in summary.recent_events
        ],
    )


@router.post("/{device_id}/deploy-model", response_model=EdgeDeviceDeploymentResponse)
async def deploy_model_to_edge_device(
    device_id: UUID,
    request: EdgeDeviceDeploymentRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = _get_user(db, current_user_id)
    _require_admin(user)

    device = db.query(models.EdgeDevice).filter(
        models.EdgeDevice.id == device_id,
        models.EdgeDevice.organization_id == user.organization_id,
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Edge device not found")

    model_query = db.query(models.ModelVersion).filter(
        models.ModelVersion.organization_id == user.organization_id,
    )
    if request.model_version_id is not None:
        model_query = model_query.filter(models.ModelVersion.id == request.model_version_id)
    else:
        model_query = model_query.order_by(
            models.ModelVersion.is_production.desc(),
            models.ModelVersion.created_at.desc(),
        )
    model_version = model_query.first()
    if model_version is None:
        raise HTTPException(status_code=404, detail="Model version not found")

    deployed = edge_device_service.deploy_model_to_device(
        db,
        device,
        model_version,
        deployment_config=request.deployment_config,
    )
    deployed_at_raw = (deployed.model_config or {}).get("deployed_at")
    deployed_at = None
    if isinstance(deployed_at_raw, str):
        try:
            deployed_at = datetime.fromisoformat(deployed_at_raw)
        except ValueError:
            deployed_at = None

    return EdgeDeviceDeploymentResponse(
        device=_serialize_edge_device(deployed),
        deployed_model_version_id=model_version.id,
        deployed_model_name=model_version.name,
        model_type=model_version.model_type,
        artifact_path=model_version.file_path,
        deployed_at=deployed_at,
    )


@router.post("/{device_id}/export/onnx")
async def export_edge_model(
    device_id: UUID,
    request: schemas.EdgeDeviceExportRequest,
    current_user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    user = _get_user(db, current_user_id)
    _require_admin(user)

    device = db.query(models.EdgeDevice).filter(
        models.EdgeDevice.id == device_id,
        models.EdgeDevice.organization_id == user.organization_id,
    ).first()
    if not device:
        raise HTTPException(status_code=404, detail="Edge device not found")

    payload = request.model_dump()
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{AI_SERVICE_URL}/edge/export/onnx",
                json=payload,
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"AI service unavailable: {exc}")

    if resp.status_code != 200:
        detail = None
        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail or "Edge export failed")

    result = resp.json()
    device.last_export_at = datetime.now(timezone.utc)
    device.last_export_status = "success" if result.get("success", True) else "error"
    device.last_export_path = result.get("output_path")
    device.last_export_details = result
    if device.last_export_status == "success" and result.get("output_path"):
        device.model_artifact_path = result.get("output_path")
    db.commit()

    return result


@router.post("/heartbeat", response_model=schemas.EdgeDevice)
async def edge_device_heartbeat(
    request: schemas.EdgeDeviceHeartbeatRequest,
    edge_token: Optional[str] = Header(None, alias="X-Edge-Token"),
    db: Session = Depends(get_db),
):
    device = _get_device_by_token(edge_token, db)
    updated = edge_device_service.update_device_heartbeat(
        db,
        device,
        status=request.status,
        ip_address=request.ip_address,
        metrics=request.metrics,
        model_version_id=request.model_version_id,
    )
    return _serialize_edge_device(updated)


@router.post("/sync/embeddings", response_model=schemas.EdgeDeviceSyncResponse)
async def sync_edge_embeddings(
    request: schemas.EdgeDeviceSyncRequest,
    edge_token: Optional[str] = Header(None, alias="X-Edge-Token"),
    db: Session = Depends(get_db),
):
    device = _get_device_by_token(edge_token, db)
    result = edge_device_service.build_embedding_sync_payload(
        db,
        device.organization_id,
        since=request.since,
        offset=request.offset,
        limit=request.limit,
    )

    device.last_sync_at = datetime.now(timezone.utc)
    device.last_sync_count = result.count
    device.last_sync_status = "success"
    db.commit()

    return schemas.EdgeDeviceSyncResponse(
        device_id=device.id,
        synced_at=device.last_sync_at,
        since=request.since,
        count=result.count,
        next_offset=result.next_offset,
        items=[schemas.EdgeDeviceEmbeddingItem(**item) for item in result.items],
    )


@router.post("/events", response_model=schemas.EdgeDeviceEventResponse)
async def create_edge_device_event(
    request: schemas.EdgeDeviceEventCreate,
    edge_token: Optional[str] = Header(None, alias="X-Edge-Token"),
    db: Session = Depends(get_db),
):
    device = _get_device_by_token(edge_token, db)
    event = edge_device_service.record_edge_event(
        db,
        device,
        event_type=request.event_type,
        severity=request.severity,
        title=request.title,
        message=request.message,
        payload=request.payload,
    )
    return event
