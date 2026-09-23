"""Missing-person case, evidence intake and safe-report tests (MP).

Covers the behaviour the feature exists for: a case can be raised, evidence
from several sources lands on the *right* case, unroutable information is not
lost, and a "found safe" claim from the public cannot close a live case on
its own.
"""

import base64
import io
import os
from datetime import datetime, timezone

import pytest

from models import models
from services import missing_person_email_service as mp_email
from services import missing_person_service as mp_service


INTERNAL_KEY = "test-internal-service-key-for-missing-persons"


@pytest.fixture
def public_intake(monkeypatch):
    """Turn the public intake surface on for a test."""
    monkeypatch.setenv("ENABLE_PUBLIC_MISSING_PERSON_INTAKE", "1")
    yield


@pytest.fixture
def internal_key(monkeypatch):
    """Configure the internal service key used by the email webhook."""
    from core import security

    monkeypatch.setattr(security, "_INTERNAL_SERVICE_KEY", INTERNAL_KEY, raising=False)
    yield {"X-Internal-API-Key": INTERNAL_KEY}


@pytest.fixture
def case(client, admin_headers):
    response = client.post(
        "/api/v1/missing-persons/",
        headers=admin_headers,
        json={
            "full_name": "Sita Devi Sharma",
            "nickname": "Sita",
            "age": 17,
            "gender": "female",
            "height_cm": 158,
            "hair_color": "black",
            "eye_color": "brown",
            "distinguishing_marks": "Scar above left eyebrow",
            "clothing_description": "Red kurta, blue jeans",
            "last_seen_location": "Ratna Park, Kathmandu",
            "last_seen_at": "2026-08-20T14:30:00Z",
            "reporter_name": "Ram Sharma",
            "reporter_email": "ram@example.com",
            "reporter_relationship": "father",
            "reporter_consent_given": True,
            "priority": "high",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ─── Case lifecycle ─────────────────────────────────────────────────────────


def test_create_case_allocates_reference_and_intake_token(case, db):
    assert case["case_reference"].startswith(f"MP-{datetime.now(timezone.utc).year}-")
    assert case["status"] == "open"
    assert case["priority"] == "high"
    # The reply address carries the per-case token so an emailed reply routes back.
    assert case["intake_email"] and "+" in case["intake_email"]

    row = db.query(models.MissingPersonCase).filter(
        models.MissingPersonCase.case_reference == case["case_reference"]
    ).first()
    assert row is not None
    assert row.intake_token and len(row.intake_token) >= 16


def test_case_references_increment_per_organization(client, admin_headers, case):
    second = client.post(
        "/api/v1/missing-persons/",
        headers=admin_headers,
        json={"full_name": "Hari Bahadur"},
    )
    assert second.status_code == 201
    assert second.json()["case_reference"] != case["case_reference"]
    assert second.json()["case_reference"].endswith("0002")


def test_case_creation_records_timeline_entry(client, admin_headers, case):
    response = client.get(
        f"/api/v1/missing-persons/{case['id']}/timeline", headers=admin_headers
    )
    assert response.status_code == 200
    entries = response.json()
    assert any(e["update_type"] == "case_created" for e in entries)


def test_case_detail_returns_everything_on_the_case(client, admin_headers, case):
    response = client.get(f"/api/v1/missing-persons/{case['id']}", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Sita Devi Sharma"
    assert body["distinguishing_marks"] == "Scar above left eyebrow"
    assert "submissions" in body and "attachments" in body and "timeline" in body


def test_case_requires_authentication(client, case):
    assert client.get("/api/v1/missing-persons/").status_code in (401, 403)
    assert client.get(f"/api/v1/missing-persons/{case['id']}").status_code in (401, 403)


def test_case_management_requires_staff_or_admin(client, db, test_org, case):
    user = models.User(
        organization_id=test_org.id,
        email="analyst-mp@test.com",
        full_name="Analyst",
        password_hash="not-used",
        role="analyst",
    )
    db.add(user)
    db.commit()

    from core.security import create_access_token

    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    response = client.get(f"/api/v1/missing-persons/{case['id']}", headers=headers)
    assert response.status_code == 403


def test_case_is_tenant_scoped(client, db, admin_headers, case):
    """A case belonging to another organization is not visible."""
    other_org = models.Organization(name="Other Org")
    db.add(other_org)
    db.commit()
    db.refresh(other_org)

    foreign = mp_service.create_case(db, other_org.id, full_name="Someone Else")
    response = client.get(
        f"/api/v1/missing-persons/{foreign.id}", headers=admin_headers
    )
    assert response.status_code == 404


def test_search_and_filter_cases(client, admin_headers, case):
    hit = client.get("/api/v1/missing-persons/?q=Sita", headers=admin_headers)
    assert hit.status_code == 200
    assert hit.json()["total"] == 1

    miss = client.get("/api/v1/missing-persons/?status=found_safe", headers=admin_headers)
    assert miss.json()["total"] == 0


# ─── Evidence upload ────────────────────────────────────────────────────────


def _file(name: str, content: bytes = b"evidence-bytes", ctype: str = "image/jpeg"):
    return ("files", (name, io.BytesIO(content), ctype))


def test_upload_case_evidence_stores_files_with_kind(client, admin_headers, case):
    response = client.post(
        f"/api/v1/missing-persons/{case['id']}/evidence",
        headers=admin_headers,
        files=[_file("cctv-clip.mp4", b"video-bytes", "video/mp4")],
        data={"file_kind": "cctv_footage", "capture_location": "Ratna Park gate 2"},
    )
    assert response.status_code == 201, response.text
    attachment = response.json()[0]
    assert attachment["file_kind"] == "cctv_footage"
    assert attachment["capture_location"] == "Ratna Park gate 2"
    assert attachment["checksum_sha256"]


def test_evidence_kind_is_inferred_from_the_file(client, admin_headers, case):
    response = client.post(
        f"/api/v1/missing-persons/{case['id']}/evidence",
        headers=admin_headers,
        files=[
            _file("police-report.pdf", b"%PDF-1.4 report", "application/pdf"),
            _file("snapshot.jpg", b"jpeg-bytes", "image/jpeg"),
        ],
    )
    assert response.status_code == 201
    kinds = {a["original_filename"]: a["file_kind"] for a in response.json()}
    assert kinds["police-report.pdf"] == "document"
    assert kinds["snapshot.jpg"] == "photo"


def test_identical_files_are_deduplicated_on_disk(client, admin_headers, case, db):
    payload = b"the-same-photo-everyone-forwards"
    for _ in range(2):
        response = client.post(
            f"/api/v1/missing-persons/{case['id']}/evidence",
            headers=admin_headers,
            files=[_file("photo.jpg", payload)],
        )
        assert response.status_code == 201

    rows = (
        db.query(models.MissingPersonAttachment)
        .filter(models.MissingPersonAttachment.case_id == case["id"])
        .all()
    )
    assert len(rows) == 2
    # Two attachment rows, one stored object.
    assert len({r.file_url for r in rows}) == 1


def test_invalid_file_kind_is_rejected(client, admin_headers, case):
    response = client.post(
        f"/api/v1/missing-persons/{case['id']}/evidence",
        headers=admin_headers,
        files=[_file("x.jpg")],
        data={"file_kind": "not-a-kind"},
    )
    assert response.status_code == 400


def test_evidence_upload_is_audited(client, admin_headers, case, db):
    client.post(
        f"/api/v1/missing-persons/{case['id']}/evidence",
        headers=admin_headers,
        files=[_file("x.jpg")],
    )
    audit = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.action == "upload_evidence")
        .first()
    )
    assert audit is not None
    assert audit.entity_id == case["id"]


# ─── Routing: connecting a submission to the right case ─────────────────────


def test_case_reference_in_the_message_routes_the_tip(client, admin_headers, case, db, test_org):
    match = mp_service.route_submission(
        db,
        test_org.id,
        message=f"I think I saw her near the bus park, this is about {case['case_reference']}",
    )
    assert match.matched
    assert match.method == "case_reference"
    assert match.case.case_reference == case["case_reference"]


def test_intake_token_in_the_recipient_address_routes_the_tip(db, test_org, case):
    row = db.query(models.MissingPersonCase).filter(
        models.MissingPersonCase.id == case["id"]
    ).first()
    to_address = f"missing-persons+{row.intake_token}@sentinelcv.local"

    match = mp_service.route_submission(db, test_org.id, email_to=to_address)
    assert match.matched
    assert match.method == "intake_token"


def test_close_name_match_routes_the_tip(db, test_org, case):
    match = mp_service.route_submission(db, test_org.id, person_name="Sita Sharma")
    assert match.matched
    assert match.method == "name_match"
    assert match.confidence >= mp_service.AUTO_LINK_THRESHOLD


def test_unrelated_information_is_not_guessed_onto_a_case(db, test_org, case):
    match = mp_service.route_submission(db, test_org.id, person_name="Bikash Thapa")
    assert not match.matched
    assert match.method == "unmatched"
    # The near-misses are still recorded so a reviewer can see the reasoning.
    assert isinstance(match.candidates, list)


def test_email_reply_continues_the_original_thread(db, test_org, case):
    row = db.query(models.MissingPersonCase).filter(
        models.MissingPersonCase.id == case["id"]
    ).first()
    first = mp_service.create_submission(
        db,
        test_org.id,
        match=mp_service.CaseMatch(case=row, method="case_reference", confidence=1.0),
        source="email",
        email_message_id="<original@mail.example>",
    )
    assert first.case_id is not None

    match = mp_service.route_submission(
        db, test_org.id, email_in_reply_to="<original@mail.example>"
    )
    assert match.matched
    assert match.method == "email_thread"


def test_extract_case_reference_is_case_insensitive():
    assert mp_service.extract_case_reference("re: mp-2026-0007 sighting") == "MP-2026-0007"
    assert mp_service.extract_case_reference("nothing here") is None


def test_extract_intake_token_from_plus_address():
    token = mp_service.extract_intake_token("Tips <missing-persons+abc123def456@example.org>")
    assert token == "abc123def456"


# ─── Triage queue ───────────────────────────────────────────────────────────


def test_unrouted_submission_lands_in_triage(client, admin_headers, db, test_org):
    match = mp_service.route_submission(db, test_org.id, person_name="Totally Unknown")
    submission = mp_service.create_submission(
        db, test_org.id, match=match, source="web_form", message="Saw someone"
    )
    assert submission.case_id is None
    assert submission.status == "triage"

    response = client.get("/api/v1/missing-persons/submissions/triage", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["total"] == 1


def test_assigning_a_submission_moves_its_files_to_the_case(
    client, admin_headers, db, test_org, case
):
    match = mp_service.route_submission(db, test_org.id, person_name="Unknown Person")
    submission = mp_service.create_submission(
        db, test_org.id, match=match, source="web_form", message="A photo from the market"
    )
    attachment = mp_service.store_attachment(
        db, test_org.id, b"a-photo", filename="market.jpg", content_type="image/jpeg",
        submission=submission,
    )
    assert attachment.case_id is None

    response = client.post(
        f"/api/v1/missing-persons/submissions/{submission.id}/assign",
        headers=admin_headers,
        json={"case_id": case["id"], "notes": "Matches the clothing description"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["case_id"] == case["id"]

    db.refresh(attachment)
    assert str(attachment.case_id) == case["id"]


def test_review_submission_status(client, admin_headers, db, test_org, case):
    row = db.query(models.MissingPersonCase).filter(
        models.MissingPersonCase.id == case["id"]
    ).first()
    submission = mp_service.create_submission(
        db,
        test_org.id,
        match=mp_service.CaseMatch(case=row, method="explicit_id", confidence=1.0),
        source="web_form",
        message="Tip",
    )
    response = client.patch(
        f"/api/v1/missing-persons/submissions/{submission.id}",
        headers=admin_headers,
        json={"status": "verified", "review_notes": "Confirmed by CCTV"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "verified"


def test_review_rejects_unknown_status(client, admin_headers, db, test_org, case):
    row = db.query(models.MissingPersonCase).filter(
        models.MissingPersonCase.id == case["id"]
    ).first()
    submission = mp_service.create_submission(
        db,
        test_org.id,
        match=mp_service.CaseMatch(case=row, method="explicit_id", confidence=1.0),
        source="web_form",
    )
    response = client.patch(
        f"/api/v1/missing-persons/submissions/{submission.id}",
        headers=admin_headers,
        json={"status": "banana"},
    )
    assert response.status_code == 400


# ─── Staff submissions ──────────────────────────────────────────────────────


def test_staff_submission_attaches_files_and_appears_on_the_case(
    client, admin_headers, case
):
    response = client.post(
        f"/api/v1/missing-persons/{case['id']}/submissions",
        headers=admin_headers,
        data={
            "message": "Phoned in by a shopkeeper",
            "submission_type": "sighting",
            "sighting_location": "New Road",
        },
        files=[_file("shop-cctv.mp4", b"clip", "video/mp4")],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["matched"] is True
    assert body["attachments_received"] == 1

    detail = client.get(f"/api/v1/missing-persons/{case['id']}", headers=admin_headers).json()
    assert detail["submission_count"] == 1
    assert any(s["sighting_location"] == "New Road" for s in detail["submissions"])


# ─── Public intake ──────────────────────────────────────────────────────────


def test_public_routes_are_off_by_default(client, monkeypatch):
    monkeypatch.delenv("ENABLE_PUBLIC_MISSING_PERSON_INTAKE", raising=False)
    response = client.post("/api/v1/missing-persons/public/tips", data={"message": "hello"})
    assert response.status_code == 404


def test_public_report_creates_a_case_and_acknowledges(client, public_intake, test_org):
    response = client.post(
        "/api/v1/missing-persons/public/report",
        data={
            "full_name": "Bikash Thapa",
            "reporter_name": "Maya Thapa",
            "reporter_email": "maya@example.com",
            "reporter_relationship": "sister",
            "reporter_consent_given": "true",
            "last_seen_location": "Pokhara lakeside",
            "organization_id": str(test_org.id),
        },
        files=[_file("bikash.jpg", b"photo-bytes")],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["matched"] is True
    assert body["case_reference"].startswith("MP-")
    assert body["attachments_received"] == 1
    assert body["reply_to"] and "+" in body["reply_to"]


def test_public_report_requires_consent(client, public_intake, test_org):
    response = client.post(
        "/api/v1/missing-persons/public/report",
        data={
            "full_name": "Bikash Thapa",
            "reporter_name": "Maya Thapa",
            "reporter_email": "maya@example.com",
            "reporter_relationship": "sister",
            "reporter_consent_given": "false",
            "organization_id": str(test_org.id),
        },
    )
    assert response.status_code == 400


def test_public_case_created_is_not_published_automatically(
    client, public_intake, admin_headers, test_org
):
    client.post(
        "/api/v1/missing-persons/public/report",
        data={
            "full_name": "Bikash Thapa",
            "reporter_name": "Maya Thapa",
            "reporter_email": "maya@example.com",
            "reporter_relationship": "sister",
            "reporter_consent_given": "true",
            "organization_id": str(test_org.id),
        },
    )
    listing = client.get("/api/v1/missing-persons/", headers=admin_headers).json()
    assert listing["total"] == 1
    assert listing["items"][0]["is_public"] is False


def test_public_tip_routes_by_case_reference(client, public_intake, case, test_org):
    response = client.post(
        "/api/v1/missing-persons/public/tips",
        data={
            "message": f"Saw her at the bus park — {case['case_reference']}",
            "submitter_name": "Anon Helper",
            "sighting_location": "Bus Park",
            "organization_id": str(test_org.id),
        },
        files=[_file("busstop.jpg", b"bus-photo")],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["matched"] is True
    assert body["case_reference"] == case["case_reference"]
    assert body["match_method"] == "case_reference"
    assert body["attachments_received"] == 1


def test_public_tip_routes_by_intake_token_without_a_reference(
    client, public_intake, case, db
):
    row = db.query(models.MissingPersonCase).filter(
        models.MissingPersonCase.id == case["id"]
    ).first()
    response = client.post(
        "/api/v1/missing-persons/public/tips",
        data={"message": "She was on the 7am bus", "intake_token": row.intake_token},
    )
    assert response.status_code == 201, response.text
    assert response.json()["match_method"] == "intake_token"
    assert response.json()["case_reference"] == case["case_reference"]


def test_public_tip_without_a_match_is_kept_for_triage(
    client, public_intake, admin_headers, case, test_org
):
    response = client.post(
        "/api/v1/missing-persons/public/tips",
        data={
            "message": "I saw a lost child near the temple",
            "person_name": "Unknown Child",
            "organization_id": str(test_org.id),
        },
    )
    assert response.status_code == 201
    assert response.json()["matched"] is False

    triage = client.get(
        "/api/v1/missing-persons/submissions/triage", headers=admin_headers
    ).json()
    assert triage["total"] == 1


def test_public_tip_needs_a_message_or_a_file(client, public_intake, test_org):
    response = client.post(
        "/api/v1/missing-persons/public/tips",
        data={"organization_id": str(test_org.id)},
    )
    assert response.status_code == 400


def test_anonymous_tip_does_not_expose_submitter_details(
    client, public_intake, admin_headers, case, test_org
):
    client.post(
        "/api/v1/missing-persons/public/tips",
        data={
            "message": f"Reference {case['case_reference']} — seen at the station",
            "submitter_name": "Should Not Appear",
            "submitter_email": "hidden@example.com",
            "is_anonymous": "true",
            "organization_id": str(test_org.id),
        },
    )
    detail = client.get(f"/api/v1/missing-persons/{case['id']}", headers=admin_headers).json()
    submission = detail["submissions"][0]
    assert submission["is_anonymous"] is True
    assert submission["submitter_name"] is None
    assert submission["submitter_email"] is None


def test_public_case_listing_only_shows_published_cases(
    client, public_intake, admin_headers, case, test_org
):
    hidden = client.get(
        f"/api/v1/missing-persons/public/cases?organization_id={test_org.id}"
    )
    assert hidden.status_code == 200
    assert hidden.json() == []

    client.patch(
        f"/api/v1/missing-persons/{case['id']}",
        headers=admin_headers,
        json={"is_public": True},
    )
    shown = client.get(
        f"/api/v1/missing-persons/public/cases?organization_id={test_org.id}"
    ).json()
    assert len(shown) == 1
    assert shown[0]["case_reference"] == case["case_reference"]
    # The public view must not carry reporter contact details or medical notes.
    assert "reporter_email" not in shown[0]
    assert "medical_notes" not in shown[0]


def test_public_case_returns_only_published_reference_photos(
    client, public_intake, admin_headers, case, db, test_org
):
    row = db.query(models.MissingPersonCase).filter(
        models.MissingPersonCase.id == case["id"]
    ).first()
    attachment = mp_service.store_attachment(
        db,
        test_org.id,
        b"public-photo-bytes",
        filename="reference.jpg",
        content_type="image/jpeg",
        file_kind="reference_photo",
        case=row,
    )
    client.patch(
        f"/api/v1/missing-persons/{case['id']}",
        headers=admin_headers,
        json={"is_public": True},
    )

    listing = client.get(
        f"/api/v1/missing-persons/public/cases?organization_id={test_org.id}"
    ).json()
    assert listing[0]["photo_urls"] == [
        f"/api/v1/missing-persons/public/media/{attachment.id}"
    ]
    photo = client.get(listing[0]["photo_urls"][0])
    assert photo.status_code == 200
    assert photo.content == b"public-photo-bytes"


# ─── Email intake ───────────────────────────────────────────────────────────


def test_email_intake_requires_the_internal_key(client):
    response = client.post("/api/v1/missing-persons/intake/email", json={"subject": "hi"})
    assert response.status_code == 401


def test_email_intake_routes_by_plus_addressed_token_and_stores_attachments(
    client, internal_key, case, db, test_org
):
    row = db.query(models.MissingPersonCase).filter(
        models.MissingPersonCase.id == case["id"]
    ).first()
    response = client.post(
        "/api/v1/missing-persons/intake/email",
        headers=internal_key,
        json={
            "organization_id": str(test_org.id),
            "from": "Helpful Neighbour <neighbour@example.com>",
            "to": f"missing-persons+{row.intake_token}@sentinelcv.local",
            "subject": "I have CCTV from my shop",
            "text": "Attaching footage from Tuesday evening.",
            "message_id": "<tip-1@mail.example>",
            "attachments": [
                {
                    "filename": "shop.mp4",
                    "content_type": "video/mp4",
                    "content": base64.b64encode(b"cctv-bytes").decode(),
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["matched"] is True
    assert body["match_method"] == "intake_token"
    assert body["case_reference"] == case["case_reference"]
    assert body["attachments_stored"] == 1

    attachment = (
        db.query(models.MissingPersonAttachment)
        .filter(models.MissingPersonAttachment.case_id == row.id)
        .first()
    )
    assert attachment is not None
    assert attachment.file_kind == "video"


def test_email_intake_falls_back_to_the_subject_reference(
    client, internal_key, case, test_org
):
    response = client.post(
        "/api/v1/missing-persons/intake/email",
        headers=internal_key,
        json={
            "organization_id": str(test_org.id),
            "from": "someone@example.com",
            "to": "missing-persons@sentinelcv.local",
            "subject": f"Information about {case['case_reference']}",
            "text": "She was at the market on Sunday.",
        },
    )
    assert response.status_code == 201
    assert response.json()["match_method"] == "case_reference"


def test_unroutable_email_is_kept_not_dropped(client, internal_key, admin_headers, test_org):
    response = client.post(
        "/api/v1/missing-persons/intake/email",
        headers=internal_key,
        json={
            "organization_id": str(test_org.id),
            "from": "someone@example.com",
            "to": "missing-persons@sentinelcv.local",
            "subject": "Hello",
            "text": "I might have seen someone.",
        },
    )
    assert response.status_code == 201
    assert response.json()["matched"] is False

    triage = client.get(
        "/api/v1/missing-persons/submissions/triage", headers=admin_headers
    ).json()
    assert triage["total"] == 1
    assert triage["items"][0]["source"] == "email"


def test_parse_inbound_payload_handles_postmark_header_lists():
    parsed = mp_email.parse_inbound_payload(
        {
            "From": "Person <p@example.com>",
            "Subject": "Tip",
            "TextBody": "text here",
            "Headers": [
                {"Name": "Message-ID", "Value": "<abc@x>"},
                {"Name": "In-Reply-To", "Value": "<parent@x>"},
                {"Name": "To", "Value": "tips+tok12345678@example.org"},
            ],
        }
    )
    assert parsed["from_address"] == "p@example.com"
    assert parsed["message_id"] == "<abc@x>"
    assert parsed["in_reply_to"] == "<parent@x>"
    assert parsed["body"] == "text here"


def test_parse_inbound_payload_skips_undecodable_attachments():
    parsed = mp_email.parse_inbound_payload(
        {"from": "a@b.c", "text": "hi", "attachments": [{"filename": "x", "content": None}]}
    )
    assert parsed["attachments"] == []


# ─── Safe / found reports ───────────────────────────────────────────────────


def test_public_safe_report_does_not_close_the_case(
    client, public_intake, case, db, admin_headers
):
    row = db.query(models.MissingPersonCase).filter(
        models.MissingPersonCase.id == case["id"]
    ).first()
    response = client.post(
        "/api/v1/missing-persons/public/safe-report",
        json={
            "intake_token": row.intake_token,
            "reported_by_name": "Sita",
            "reported_by_relationship": "self",
            "outcome": "found_safe",
            "notes": "I am safe, I went to my aunt's house",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["verified"] is False
    assert body["case_status"] == "open"

    detail = client.get(f"/api/v1/missing-persons/{case['id']}", headers=admin_headers).json()
    assert detail["status"] == "open"
    assert detail["pending_safe_reports"] == 1
    # An unverified safe report raises the case for attention instead.
    assert detail["priority"] in ("high", "critical")


def test_verifying_a_safe_report_closes_the_case(
    client, public_intake, case, db, admin_headers
):
    row = db.query(models.MissingPersonCase).filter(
        models.MissingPersonCase.id == case["id"]
    ).first()
    report = client.post(
        "/api/v1/missing-persons/public/safe-report",
        json={"intake_token": row.intake_token, "outcome": "found_safe"},
    ).json()

    verified = client.post(
        f"/api/v1/missing-persons/updates/{report['update_id']}/verify",
        headers=admin_headers,
        json={"accept": True, "notes": "Confirmed by phone with the family"},
    )
    assert verified.status_code == 200, verified.text

    detail = client.get(f"/api/v1/missing-persons/{case['id']}", headers=admin_headers).json()
    assert detail["status"] == "found_safe"
    assert detail["resolved_at"] is not None
    # A resolved case stops being publicly appealed for.
    assert detail["is_public"] is False


def test_rejecting_a_safe_report_leaves_the_case_open(
    client, public_intake, case, db, admin_headers
):
    row = db.query(models.MissingPersonCase).filter(
        models.MissingPersonCase.id == case["id"]
    ).first()
    report = client.post(
        "/api/v1/missing-persons/public/safe-report",
        json={"intake_token": row.intake_token, "outcome": "found_safe"},
    ).json()

    client.post(
        f"/api/v1/missing-persons/updates/{report['update_id']}/verify",
        headers=admin_headers,
        json={"accept": False, "notes": "Caller could not describe her"},
    )
    detail = client.get(f"/api/v1/missing-persons/{case['id']}", headers=admin_headers).json()
    assert detail["status"] == "open"


def test_staff_safe_report_closes_the_case_directly(client, admin_headers, case):
    response = client.post(
        f"/api/v1/missing-persons/{case['id']}/safe-report",
        headers=admin_headers,
        json={
            "outcome": "found_safe",
            "reported_by_name": "Ram Sharma",
            "notes": "Returned home this morning",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["verified"] is True
    assert response.json()["case_status"] == "found_safe"


def test_safe_report_rejects_an_invalid_outcome(client, admin_headers, case):
    response = client.post(
        f"/api/v1/missing-persons/{case['id']}/safe-report",
        headers=admin_headers,
        json={"outcome": "vanished"},
    )
    assert response.status_code == 400


def test_status_change_records_previous_status_on_the_timeline(
    client, admin_headers, case
):
    client.post(
        f"/api/v1/missing-persons/{case['id']}/status",
        headers=admin_headers,
        json={"status": "closed", "notes": "Handed to police"},
    )
    timeline = client.get(
        f"/api/v1/missing-persons/{case['id']}/timeline", headers=admin_headers
    ).json()
    change = next(e for e in timeline if e["update_type"] == "status_change")
    assert change["previous_status"] == "open"
    assert change["new_status"] == "closed"


def test_status_change_rejects_an_unknown_status(client, admin_headers, case):
    response = client.post(
        f"/api/v1/missing-persons/{case['id']}/status",
        headers=admin_headers,
        json={"status": "lost-forever"},
    )
    assert response.status_code == 400


# ─── Stats ──────────────────────────────────────────────────────────────────


def test_stats_counts_open_cases_and_untriaged_submissions(
    client, admin_headers, case, db, test_org
):
    match = mp_service.route_submission(db, test_org.id, person_name="Nobody At All")
    mp_service.create_submission(db, test_org.id, match=match, source="web_form")

    stats = client.get("/api/v1/missing-persons/stats", headers=admin_headers).json()
    assert stats["total_cases"] == 1
    assert stats["open_cases"] == 1
    assert stats["untriaged_submissions"] == 1


# ─── Service-level helpers ──────────────────────────────────────────────────


def test_staff_can_create_disaster_event_and_bulk_import_cases(
    client, admin_headers, db, test_org
):
    event = client.post(
        "/api/v1/missing-persons/disaster-events",
        headers=admin_headers,
        json={
            "name": "Kavrepalanchok Flood Response",
            "event_type": "flood",
            "affected_areas": ["Kavrepalanchok", "Sindhuli"],
        },
    )
    assert event.status_code == 201, event.text

    csv_data = (
        "full_name,age,gender,last_seen_location,priority\n"
        "Ram Bahadur Thapa,42,male,Kavrepalanchok,high\n"
        "Maya Gurung,31,female,Sindhuli,medium\n"
    )
    imported = client.post(
        "/api/v1/missing-persons/bulk-import",
        headers=admin_headers,
        data={"disaster_event_id": event.json()["id"]},
        files={"file": ("missing-persons.csv", csv_data, "text/csv")},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported"] == 2
    assert imported.json()["failed"] == 0

    cases = db.query(models.MissingPersonCase).filter(
        models.MissingPersonCase.organization_id == test_org.id
    ).all()
    assert {case.full_name for case in cases} == {"Ram Bahadur Thapa", "Maya Gurung"}
    assert {str(case.disaster_event_id) for case in cases} == {event.json()["id"]}


def test_classify_attachment_falls_back_to_other():
    assert mp_service.classify_attachment("clip.mp4", None) == "video"
    assert mp_service.classify_attachment("scan.pdf", None) == "document"
    assert mp_service.classify_attachment("mystery.xyz", None) == "other"
    assert mp_service.classify_attachment(None, "image/png") == "photo"


def test_store_attachment_rejects_an_oversized_file(db, test_org, monkeypatch):
    monkeypatch.setattr(mp_service, "MAX_ATTACHMENT_BYTES", 10)
    with pytest.raises(ValueError):
        mp_service.store_attachment(db, test_org.id, b"x" * 11, filename="big.bin")


def test_name_similarity_ignores_ordering_and_extra_names():
    assert mp_service._name_similarity("Sita Devi Sharma", "Sharma Sita") > 0.5
    assert mp_service._name_similarity("Sita Sharma", "Bikash Thapa") < 0.4
