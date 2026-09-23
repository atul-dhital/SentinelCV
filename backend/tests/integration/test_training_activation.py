from datetime import datetime, timezone

import torch

from core.runtime_registry import load_runtime_registry
from models.models import TrainingJob
from services import custom_classifier_service


def test_activate_trained_model_updates_runtime_registry(client, admin_headers, admin_user, db):
    model = custom_classifier_service.SimpleClassifier(3, 2, hidden_dims=[4, 4, 4])
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.network[-1].bias.copy_(torch.tensor([1.5, -1.5]))

    artifact = custom_classifier_service.save_training_artifact(
        organization_id=str(admin_user.organization_id),
        job_id="activation-job-001",
        model_state_dict=model.state_dict(),
        input_dim=3,
        num_classes=2,
        class_to_visitor_id={"0": "visitor-a", "1": "visitor-b"},
        scaler_mean=[0.0, 0.0, 0.0],
        scaler_scale=[1.0, 1.0, 1.0],
        config={"model_name": "arcface"},
        metrics={"accuracy": 0.97},
        hidden_dims=[4, 4, 4],
    )

    training_job = TrainingJob(
        organization_id=admin_user.organization_id,
        status="completed",
        config={"artifact_path": artifact["artifact_path"]},
        started_by=admin_user.id,
        accuracy=0.97,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(training_job)
    db.commit()
    db.refresh(training_job)

    response = client.post(
        f"/api/v1/training/jobs/{training_job.id}/activate",
        headers=admin_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "activated"
    assert payload["runtime_face_model"] == "CustomClassifier"

    runtime_registry = load_runtime_registry()
    face_component = next(
        item for item in runtime_registry["components"] if item.get("component") == "face_recognition"
    )
    assert face_component["current_model"] == "CustomClassifier"
    assert face_component["current_artifact"] == artifact["artifact_path"]
