from models.models import Organization, Visitor
from services import visitor_service


def _make_visitor(db, org, *, name: str, threshold: float | None = None):
    visitor = Visitor(
        organization_id=org.id,
        name=name,
        is_known=True,
        is_active=True,
        custom_threshold=threshold,
    )
    db.add(visitor)
    db.commit()
    db.refresh(visitor)
    return visitor


def _make_org(db, name: str):
    org = Organization(name=name)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def test_sqlite_embedding_round_trip_uses_encrypted_storage():
    embedding = [0.1, 0.2, 0.3, 0.4]

    stored = visitor_service.serialize_embedding_for_storage(embedding)

    assert isinstance(stored, str)
    assert stored != str(embedding)
    assert visitor_service.parse_embedding_payload(stored) == embedding


def test_search_visitor_by_embedding_honors_angle_aliases_in_sqlite(db):
    org = _make_org(db, "Angle Alias Org")
    profile_visitor = _make_visitor(db, org, name="Profile Match")
    frontal_visitor = _make_visitor(db, org, name="Frontal Match")

    profile_embedding = [0.91, 0.09, 0.0]
    frontal_embedding = [0.0, 1.0, 0.0]

    visitor_service.create_face_data(
        db,
        profile_visitor.id,
        embedding=profile_embedding,
        face_angle="profile",
        is_primary=True,
    )
    visitor_service.create_face_data(
        db,
        frontal_visitor.id,
        embedding=frontal_embedding,
        face_angle="frontal",
        is_primary=True,
    )

    match = visitor_service.search_visitor_by_embedding(
        db,
        organization_id=org.id,
        embedding=profile_embedding,
        threshold=0.6,
        angle="profile_left",
    )

    assert match is not None
    matched_visitor, confidence, _face_data_id, metadata = match
    assert matched_visitor.id == profile_visitor.id
    assert confidence > 0.9
    assert metadata["detected_angle"] == "profile"


def test_search_visitor_by_embedding_applies_custom_threshold_and_consensus_boost(db):
    org = _make_org(db, "Consensus Org")
    strict_visitor = _make_visitor(db, org, name="Strict Threshold", threshold=0.95)
    consensus_visitor = _make_visitor(db, org, name="Consensus Match")

    strict_embedding = [0.82, 0.57, 0.02]
    query_embedding = [0.8, 0.6, 0.0]

    visitor_service.create_face_data(
        db,
        strict_visitor.id,
        embedding=strict_embedding,
        face_angle="frontal",
        is_primary=True,
    )

    for embedding in (
        [0.82, 0.58, 0.0],
        [0.81, 0.59, 0.0],
        [0.79, 0.61, 0.0],
    ):
        visitor_service.create_face_data(
            db,
            consensus_visitor.id,
            embedding=embedding,
            face_angle="frontal",
            is_primary=False,
        )

    match = visitor_service.search_visitor_by_embedding(
        db,
        organization_id=org.id,
        embedding=query_embedding,
        threshold=0.8,
        angle="frontal",
    )

    assert match is not None
    matched_visitor, confidence, _face_data_id, metadata = match
    assert matched_visitor.id == consensus_visitor.id
    assert confidence >= 0.95
    assert metadata["method"] == "top_k_consensus"
    assert metadata["top_k"] == 3


def test_search_visitor_by_embedding_can_rerank_with_custom_classifier(db, monkeypatch):
    org = _make_org(db, "Custom Classifier Org")
    classifier_favored = _make_visitor(db, org, name="Classifier Favored")
    cosine_favored = _make_visitor(db, org, name="Cosine Favored")

    query_embedding = [1.0, 0.0, 0.0]

    visitor_service.create_face_data(
        db,
        classifier_favored.id,
        embedding=[0.95, 0.31, 0.0],
        face_angle="frontal",
        is_primary=True,
    )
    visitor_service.create_face_data(
        db,
        cosine_favored.id,
        embedding=[0.99, 0.10, 0.0],
        face_angle="frontal",
        is_primary=True,
    )

    monkeypatch.setattr(
        visitor_service,
        "get_runtime_component",
        lambda component: (
            {
                "component": "face_recognition",
                "current_model": "CustomClassifier",
                "current_artifact": "model_artifacts/test/latest_custom_classifier.pt",
            }
            if component == "face_recognition"
            else None
        ),
    )
    monkeypatch.setattr(
        visitor_service.custom_classifier_service,
        "predict_probabilities",
        lambda artifact_path, embedding, organization_id=None: {
            str(classifier_favored.id): 0.99,
            str(cosine_favored.id): 0.05,
        },
    )

    match = visitor_service.search_visitor_by_embedding(
        db,
        organization_id=org.id,
        embedding=query_embedding,
        threshold=0.6,
        angle="frontal",
    )

    assert match is not None
    matched_visitor, confidence, _face_data_id, metadata = match
    assert matched_visitor.id == classifier_favored.id
    assert confidence > 0.95
    assert metadata["search_backend"] == "python_cosine_plus_custom_classifier"
    assert metadata["custom_classifier_confidence"] == 0.99
