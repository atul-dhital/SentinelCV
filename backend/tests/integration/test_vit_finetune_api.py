import os
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

import api.vision_transformers as vit_api
from core.paths import data_path
from models.models import FaceData, Visitor

# The vision_transformers router is only mounted onto the app when
# ENABLE_EXPERIMENTAL_FEATURES was truthy at `main` import time (main.py:791-815).
# That happens once per test session in conftest.py, before this module runs, so
# it can't be toggled per-test — the whole file belongs to the "experimental
# integration" profile, not "core". Skip cleanly there instead of 404ing.
pytestmark = [
    pytest.mark.requires_experimental,
    pytest.mark.skipif(
        os.getenv("ENABLE_EXPERIMENTAL_FEATURES", "0").strip().lower() not in ("1", "true", "yes"),
        reason="vision_transformers router not mounted (ENABLE_EXPERIMENTAL_FEATURES != 1)",
    ),
]

API = "/api/v1/recognition/vit"


class _FakeViTService:
    backend = "fake"

    def __init__(self):
        self.fine_tune_calls = []
        self.load_calls = []

    def fine_tune_on_org_data(
        self,
        organization_id,
        visitor_face_images,
        num_epochs=None,
        learning_rate=None,
    ):
        self.fine_tune_calls.append(
            {
                "organization_id": organization_id,
                "visitor_face_images": visitor_face_images,
                "num_epochs": num_epochs,
                "learning_rate": learning_rate,
            }
        )
        return {
            "status": "completed",
            "final_loss": 0.08,
            "best_loss": 0.05,
            "model_path": f"models/vit_finetuned/{organization_id}/model.pt",
            "message": "Fake fine-tune completed",
        }

    def load_finetuned_model(self, organization_id):
        self.load_calls.append(organization_id)
        return True


def _write_test_image(relative_path: str, color: tuple[int, int, int]) -> str:
    absolute = Path(data_path(relative_path))
    absolute.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (48, 48), color).save(absolute)
    return relative_path


def _create_visitor_with_images(db, organization_id, name: str, count: int, prefix: str) -> Visitor:
    visitor = Visitor(
        organization_id=organization_id,
        name=name,
        is_known=True,
        is_active=True,
    )
    db.add(visitor)
    db.commit()
    db.refresh(visitor)

    for idx in range(count):
        image_url = _write_test_image(
            f"face_images/vit/{prefix}_{idx}.jpg",
            ((idx * 30) % 255, (idx * 50) % 255, (idx * 70) % 255),
        )
        db.add(
            FaceData(
                visitor_id=visitor.id,
                embedding=[0.1 + (idx * 0.01)] * 128,
                image_url=image_url,
                quality_score=0.9,
                face_angle="frontal",
                is_primary=(idx == 0),
            )
        )
    db.commit()
    return visitor


def _purge_org_visitors(db, organization_id) -> None:
    """Delete all visitors and their face data for an org.

    Called at the start of tests that assert exact visitor/image counts to
    prevent stale data from previous test runs from leaking through when the
    conftest DB-cleanup fixture swallows its exception silently.
    """
    from sqlalchemy import select as sa_select
    visitor_ids = [
        row[0]
        for row in db.query(Visitor.id)
        .filter(Visitor.organization_id == organization_id)
        .all()
    ]
    if visitor_ids:
        db.query(FaceData).filter(FaceData.visitor_id.in_(visitor_ids)).delete(
            synchronize_session=False
        )
    db.query(Visitor).filter(Visitor.organization_id == organization_id).delete(
        synchronize_session=False
    )
    db.commit()


def test_vit_finetune_collects_real_org_face_images(
    client,
    admin_headers,
    admin_user,
    db,
    monkeypatch,
):
    fake_service = _FakeViTService()
    monkeypatch.setattr(vit_api, "get_vit_service", lambda: fake_service)
    monkeypatch.setattr(vit_api, "_vit_backend", None)

    # Purge any stale visitors/face-data so exact count assertions are reliable
    # even when the conftest DB-cleanup fixture fails silently between tests.
    _purge_org_visitors(db, admin_user.organization_id)

    visitor_a = _create_visitor_with_images(
        db,
        admin_user.organization_id,
        "ViT Visitor A",
        5,
        "visitor_a",
    )
    visitor_b = _create_visitor_with_images(
        db,
        admin_user.organization_id,
        "ViT Visitor B",
        5,
        "visitor_b",
    )

    response = client.post(
        f"{API}/finetune",
        headers=admin_headers,
        json={
            "organization_id": str(admin_user.organization_id),
            "num_epochs": 2,
            "learning_rate": 0.0002,
        },
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["organization_id"] == str(admin_user.organization_id)
    assert payload["visitor_count"] == 2
    assert payload["image_count"] == 10
    assert payload["backend"] == "fake"

    assert len(fake_service.fine_tune_calls) == 1
    call = fake_service.fine_tune_calls[0]
    assert call["organization_id"] == str(admin_user.organization_id)
    assert set(call["visitor_face_images"].keys()) == {str(visitor_a.id), str(visitor_b.id)}
    assert sum(len(paths) for paths in call["visitor_face_images"].values()) == 10
    for paths in call["visitor_face_images"].values():
        for path in paths:
            assert Path(path).is_absolute()
            assert Path(path).exists()


def test_vit_finetune_rejects_insufficient_training_dataset(
    client,
    admin_headers,
    admin_user,
    monkeypatch,
):
    fake_service = _FakeViTService()
    monkeypatch.setattr(vit_api, "get_vit_service", lambda: fake_service)
    monkeypatch.setattr(
        vit_api,
        "_collect_organization_face_images",
        lambda db, organization_id: (
            {str(uuid4()): [str(Path(data_path("face_images/vit/only_one.jpg")).resolve())]},
            {
                "face_records": 3,
                "image_count": 3,
                "visitor_count": 1,
                "missing_image_count": 0,
            },
        ),
    )

    response = client.post(
        f"{API}/finetune",
        headers=admin_headers,
        json={"organization_id": str(admin_user.organization_id)},
    )
    assert response.status_code == 400
    assert "Need face images from at least 2 visitors" in response.json()["detail"]
    assert fake_service.fine_tune_calls == []


def test_vit_load_finetuned_model_defaults_to_current_org(
    client,
    admin_headers,
    admin_user,
    monkeypatch,
):
    fake_service = _FakeViTService()
    monkeypatch.setattr(vit_api, "get_vit_service", lambda: fake_service)

    response = client.post(
        f"{API}/finetune/load",
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["organization_id"] == str(admin_user.organization_id)
    assert fake_service.load_calls == [str(admin_user.organization_id)]


def test_vit_load_finetuned_model_blocks_cross_org_access(
    client,
    admin_headers,
    monkeypatch,
):
    fake_service = _FakeViTService()
    monkeypatch.setattr(vit_api, "get_vit_service", lambda: fake_service)

    response = client.post(
        f"{API}/finetune/load?organization_id={uuid4()}",
        headers=admin_headers,
    )
    assert response.status_code == 403
    assert fake_service.load_calls == []
