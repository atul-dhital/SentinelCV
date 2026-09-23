"""Regression tests for model versioning route matching."""


API = "/api/v1/model-versions"


def test_list_ab_tests_route_is_not_captured_by_version_id(client, admin_headers):
    model_a = client.post(
        API,
        json={
            "name": "ArcFace",
            "version": "1.0.0",
            "model_type": "face_recognition",
            "file_path": "/models/arcface-v1.onnx",
            "metrics": {"accuracy": 0.91, "precision": 0.9, "recall": 0.89, "f1_score": 0.895},
        },
        headers=admin_headers,
    )
    assert model_a.status_code == 200, model_a.text
    model_a_id = model_a.json()["id"]

    model_b = client.post(
        API,
        json={
            "name": "ArcFace",
            "version": "1.1.0",
            "model_type": "face_recognition",
            "file_path": "/models/arcface-v1_1.onnx",
            "metrics": {"accuracy": 0.93, "precision": 0.92, "recall": 0.91, "f1_score": 0.915},
        },
        headers=admin_headers,
    )
    assert model_b.status_code == 200, model_b.text
    model_b_id = model_b.json()["id"]

    experiment = client.post(
        f"{API}/ab-tests",
        json={
            "name": "ArcFace A/B",
            "description": "Route regression test",
            "model_a_id": model_a_id,
            "model_b_id": model_b_id,
            "traffic_split_percent": 50,
        },
        headers=admin_headers,
    )
    assert experiment.status_code == 200, experiment.text
    experiment_id = experiment.json()["id"]

    listed = client.get(f"{API}/ab-tests", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    assert any(item["id"] == experiment_id for item in listed.json()), listed.text
