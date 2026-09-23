from pathlib import Path

from core.paths import data_path
from models.models import FaceData, Visitor


API = "/api/v1/recognition/vit"


def _ensure_face_image(relative_path: str) -> str:
    absolute_path = Path(data_path(relative_path))
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_bytes(b"vit-benchmark-image")
    return relative_path


def _purge_org_visitors(db, organization_id) -> None:
    """Delete all visitors and face data for an org to ensure clean state."""
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


def test_vit_benchmark_uses_org_face_pairs(client, admin_headers, admin_user, db, monkeypatch):
    # Purge stale visitors so exact-count assertions are reliable.
    _purge_org_visitors(db, admin_user.organization_id)
    visitors = []
    try:
        for index in range(3):
            visitor = Visitor(
                organization_id=admin_user.organization_id,
                name=f"Benchmark Visitor {index}",
                email=f"benchmark{index}@example.com",
                is_known=True,
                is_active=True,
            )
            db.add(visitor)
            visitors.append(visitor)
        db.commit()

        for visitor in visitors:
            db.refresh(visitor)
            for image_index in range(2):
                db.add(
                    FaceData(
                        visitor_id=visitor.id,
                        embedding=[0.01 * (image_index + 1)] * 8,
                        image_url=_ensure_face_image(f"face_images/vit-benchmark-{visitor.id}-{image_index}.jpg"),
                        quality_score=0.95,
                        face_angle="frontal",
                        is_primary=image_index == 0,
                    )
                )
        db.commit()

        class _FakeVitService:
            def benchmark_against_arcface(self, test_pairs):
                assert len(test_pairs) >= 4
                assert any(pair[2] is True for pair in test_pairs)
                assert any(pair[2] is False for pair in test_pairs)
                return {
                    "total_pairs": len(test_pairs),
                    "processed_pairs": len(test_pairs),
                    "vit_accuracy": 0.97,
                    "arcface_accuracy": 0.94,
                    "improvement_pct": 3.0,
                    "vit_avg_inference_ms": 11.5,
                    "arcface_avg_inference_ms": 13.0,
                }

        monkeypatch.setattr("api.vision_transformers.get_vit_service", lambda: _FakeVitService(), raising=False)

        response = client.post(
            f"{API}/benchmark",
            json={"min_test_pairs": 4},
            headers=admin_headers,
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["processed_pairs"] >= 4
        assert payload["positive_pairs"] >= 3
        assert payload["negative_pairs"] >= 2
        assert payload["visitor_count"] == 3
    finally:
        visitor_ids = [visitor.id for visitor in visitors if getattr(visitor, "id", None)]
        if visitor_ids:
            db.query(FaceData).filter(FaceData.visitor_id.in_(visitor_ids)).delete(synchronize_session=False)
            db.query(Visitor).filter(Visitor.id.in_(visitor_ids)).delete(synchronize_session=False)
            db.commit()
