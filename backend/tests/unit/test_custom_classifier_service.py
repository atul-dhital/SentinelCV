import torch

from services import custom_classifier_service


def test_custom_classifier_artifact_round_trip_and_prediction():
    organization_id = "org-test-custom"
    job_id = "job-custom-001"

    model = custom_classifier_service.SimpleClassifier(3, 2, hidden_dims=[4, 4, 4])
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.zero_()
        model.network[-1].bias.copy_(torch.tensor([2.0, -2.0]))

    artifact = custom_classifier_service.save_training_artifact(
        organization_id=organization_id,
        job_id=job_id,
        model_state_dict=model.state_dict(),
        input_dim=3,
        num_classes=2,
        class_to_visitor_id={"0": "visitor-a", "1": "visitor-b"},
        scaler_mean=[0.0, 0.0, 0.0],
        scaler_scale=[1.0, 1.0, 1.0],
        config={"model_name": "arcface"},
        metrics={"accuracy": 0.95},
        hidden_dims=[4, 4, 4],
    )

    assert custom_classifier_service.artifact_exists(artifact["artifact_path"])
    scores = custom_classifier_service.predict_probabilities(
        artifact["artifact_path"],
        [0.1, 0.2, 0.3],
        organization_id=organization_id,
    )

    assert set(scores.keys()) == {"visitor-a", "visitor-b"}
    assert scores["visitor-a"] > scores["visitor-b"]
