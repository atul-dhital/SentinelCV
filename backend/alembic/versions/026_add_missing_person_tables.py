"""Add missing-person case, submission, attachment and case-update tables (MP).

Revision ID: 026
Revises: 025
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.String(36)
    json_type = postgresql.JSONB() if is_pg else sa.Text()
    id_default = sa.text("gen_random_uuid()") if is_pg else None
    false_default = sa.text("false") if is_pg else sa.text("0")

    op.create_table(
        "disaster_events",
        sa.Column("id", uuid_type, primary_key=True, nullable=False, server_default=id_default),
        sa.Column("organization_id", uuid_type, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("affected_areas", json_type, nullable=True),
        sa.Column("starts_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", uuid_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_index("ix_disaster_events_org", "disaster_events", ["organization_id", "status"])

    op.create_table(
        "missing_person_cases",
        sa.Column("id", uuid_type, primary_key=True, nullable=False, server_default=id_default),
        sa.Column("organization_id", uuid_type, nullable=False),
        sa.Column("disaster_event_id", uuid_type, nullable=True),
        sa.Column("case_reference", sa.String(32), nullable=False),
        sa.Column("intake_token", sa.String(64), nullable=False),
        sa.Column("visitor_id", uuid_type, nullable=True),
        # Identity
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("nickname", sa.String(120), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("date_of_birth", sa.DateTime(), nullable=True),
        sa.Column("gender", sa.String(32), nullable=True),
        # Physical description
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("build", sa.String(64), nullable=True),
        sa.Column("hair_color", sa.String(64), nullable=True),
        sa.Column("eye_color", sa.String(64), nullable=True),
        sa.Column("complexion", sa.String(64), nullable=True),
        sa.Column("distinguishing_marks", sa.Text(), nullable=True),
        sa.Column("clothing_description", sa.Text(), nullable=True),
        sa.Column("medical_notes", sa.Text(), nullable=True),
        sa.Column("languages_spoken", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        # Last known location
        sa.Column("last_seen_location", sa.String(512), nullable=True),
        sa.Column("last_seen_latitude", sa.Float(), nullable=True),
        sa.Column("last_seen_longitude", sa.Float(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_wearing", sa.Text(), nullable=True),
        # Case handling
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=false_default),
        sa.Column("external_reference", sa.String(128), nullable=True),
        # Reporter
        sa.Column("reporter_name", sa.String(255), nullable=True),
        sa.Column("reporter_email", sa.String(255), nullable=True),
        sa.Column("reporter_phone", sa.String(64), nullable=True),
        sa.Column("reporter_relationship", sa.String(120), nullable=True),
        sa.Column("reporter_consent_given", sa.Boolean(), nullable=False, server_default=false_default),
        # Resolution
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolved_by", uuid_type, nullable=True),
        sa.Column("case_metadata", json_type, nullable=True),
        sa.Column("created_by", uuid_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["disaster_event_id"], ["disaster_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["visitor_id"], ["visitors.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
    )
    op.create_index("ix_mp_cases_org", "missing_person_cases", ["organization_id"])
    op.create_index("ix_mp_cases_event", "missing_person_cases", ["disaster_event_id"])
    op.create_index("ix_mp_cases_status", "missing_person_cases", ["organization_id", "status"])
    op.create_index(
        "uq_mp_cases_reference",
        "missing_person_cases",
        ["organization_id", "case_reference"],
        unique=True,
    )
    op.create_index("uq_mp_cases_intake_token", "missing_person_cases", ["intake_token"], unique=True)

    op.create_table(
        "missing_person_submissions",
        sa.Column("id", uuid_type, primary_key=True, nullable=False, server_default=id_default),
        sa.Column("organization_id", uuid_type, nullable=False),
        sa.Column("case_id", uuid_type, nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="web_form"),
        sa.Column("submission_type", sa.String(32), nullable=False, server_default="information"),
        sa.Column("submitter_name", sa.String(255), nullable=True),
        sa.Column("submitter_email", sa.String(255), nullable=True),
        sa.Column("submitter_phone", sa.String(64), nullable=True),
        sa.Column("submitter_relationship", sa.String(120), nullable=True),
        sa.Column("is_anonymous", sa.Boolean(), nullable=False, server_default=false_default),
        sa.Column("subject", sa.String(512), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("sighting_location", sa.String(512), nullable=True),
        sa.Column("sighting_latitude", sa.Float(), nullable=True),
        sa.Column("sighting_longitude", sa.Float(), nullable=True),
        sa.Column("sighting_at", sa.DateTime(), nullable=True),
        sa.Column("email_message_id", sa.String(512), nullable=True),
        sa.Column("email_in_reply_to", sa.String(512), nullable=True),
        sa.Column("email_from", sa.String(320), nullable=True),
        sa.Column("email_to", sa.String(512), nullable=True),
        sa.Column("match_method", sa.String(32), nullable=False, server_default="unmatched"),
        sa.Column("match_confidence", sa.Float(), nullable=True, server_default="0"),
        sa.Column("match_candidates", json_type, nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="new"),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by", uuid_type, nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("submission_metadata", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["missing_person_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
    )
    op.create_index("ix_mp_submissions_org", "missing_person_submissions", ["organization_id"])
    op.create_index("ix_mp_submissions_case", "missing_person_submissions", ["case_id"])
    # Triage queue lookup: unrouted submissions for an organization.
    op.create_index(
        "ix_mp_submissions_triage",
        "missing_person_submissions",
        ["organization_id", "status", "case_id"],
    )
    op.create_index(
        "ix_mp_submissions_email_message_id",
        "missing_person_submissions",
        ["email_message_id"],
    )

    op.create_table(
        "missing_person_attachments",
        sa.Column("id", uuid_type, primary_key=True, nullable=False, server_default=id_default),
        sa.Column("organization_id", uuid_type, nullable=False),
        sa.Column("case_id", uuid_type, nullable=True),
        sa.Column("submission_id", uuid_type, nullable=True),
        sa.Column("file_kind", sa.String(32), nullable=False, server_default="photo"),
        sa.Column("file_url", sa.String(1024), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=True),
        sa.Column("content_type", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=True),
        sa.Column("capture_location", sa.String(512), nullable=True),
        sa.Column("camera_id", uuid_type, nullable=True),
        sa.Column("face_indexed", sa.Boolean(), nullable=False, server_default=false_default),
        sa.Column("face_data_id", uuid_type, nullable=True),
        sa.Column("face_match_score", sa.Float(), nullable=True),
        sa.Column("processing_notes", sa.Text(), nullable=True),
        sa.Column("uploaded_by", uuid_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["missing_person_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["missing_person_submissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["face_data_id"], ["face_data.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
    )
    op.create_index("ix_mp_attachments_org", "missing_person_attachments", ["organization_id"])
    op.create_index("ix_mp_attachments_case", "missing_person_attachments", ["case_id"])
    op.create_index("ix_mp_attachments_submission", "missing_person_attachments", ["submission_id"])
    # De-duplicate the same file mailed in by several people.
    op.create_index(
        "ix_mp_attachments_checksum",
        "missing_person_attachments",
        ["organization_id", "checksum_sha256"],
    )

    op.create_table(
        "missing_person_case_updates",
        sa.Column("id", uuid_type, primary_key=True, nullable=False, server_default=id_default),
        sa.Column("organization_id", uuid_type, nullable=False),
        sa.Column("case_id", uuid_type, nullable=False),
        sa.Column("submission_id", uuid_type, nullable=True),
        sa.Column("update_type", sa.String(32), nullable=False, server_default="note"),
        sa.Column("previous_status", sa.String(32), nullable=True),
        sa.Column("new_status", sa.String(32), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reported_by_name", sa.String(255), nullable=True),
        sa.Column("reported_by_contact", sa.String(255), nullable=True),
        sa.Column("reported_by_relationship", sa.String(120), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=false_default),
        sa.Column("verified_by", uuid_type, nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", uuid_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["missing_person_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["missing_person_submissions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["verified_by"], ["users.id"]),
    )
    op.create_index("ix_mp_case_updates_org", "missing_person_case_updates", ["organization_id"])
    op.create_index("ix_mp_case_updates_case", "missing_person_case_updates", ["case_id", "created_at"])

    op.create_table(
        "located_persons",
        sa.Column("id", uuid_type, primary_key=True, nullable=False, server_default=id_default),
        sa.Column("organization_id", uuid_type, nullable=False),
        sa.Column("disaster_event_id", uuid_type, nullable=True),
        sa.Column("record_reference", sa.String(48), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="identity_unknown"),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("approximate_age", sa.Integer(), nullable=True),
        sa.Column("gender", sa.String(32), nullable=True),
        sa.Column("found_location", sa.String(512), nullable=True),
        sa.Column("found_at", sa.DateTime(), nullable=True),
        sa.Column("facility_name", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("photo_url", sa.String(1024), nullable=True),
        sa.Column("photo_content_type", sa.String(128), nullable=True),
        sa.Column("submitted_by", uuid_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["disaster_event_id"], ["disaster_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"]),
    )
    op.create_index("ix_located_persons_org", "located_persons", ["organization_id", "status"])
    op.create_index("ix_located_persons_event", "located_persons", ["disaster_event_id"])

    op.create_table(
        "missing_person_possible_matches",
        sa.Column("id", uuid_type, primary_key=True, nullable=False, server_default=id_default),
        sa.Column("organization_id", uuid_type, nullable=False),
        sa.Column("located_person_id", uuid_type, nullable=False),
        sa.Column("case_id", uuid_type, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("match_reasons", json_type, nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by", uuid_type, nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["located_person_id"], ["located_persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["missing_person_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
    )
    op.create_index("ix_mp_possible_matches_located", "missing_person_possible_matches", ["located_person_id", "status"])
    op.create_index("ix_mp_possible_matches_case", "missing_person_possible_matches", ["case_id", "status"])


def downgrade():
    op.drop_index("ix_mp_possible_matches_case", table_name="missing_person_possible_matches")
    op.drop_index("ix_mp_possible_matches_located", table_name="missing_person_possible_matches")
    op.drop_table("missing_person_possible_matches")
    op.drop_index("ix_located_persons_event", table_name="located_persons")
    op.drop_index("ix_located_persons_org", table_name="located_persons")
    op.drop_table("located_persons")
    op.drop_index("ix_mp_case_updates_case", table_name="missing_person_case_updates")
    op.drop_index("ix_mp_case_updates_org", table_name="missing_person_case_updates")
    op.drop_table("missing_person_case_updates")

    op.drop_index("ix_mp_attachments_checksum", table_name="missing_person_attachments")
    op.drop_index("ix_mp_attachments_submission", table_name="missing_person_attachments")
    op.drop_index("ix_mp_attachments_case", table_name="missing_person_attachments")
    op.drop_index("ix_mp_attachments_org", table_name="missing_person_attachments")
    op.drop_table("missing_person_attachments")

    op.drop_index("ix_mp_submissions_email_message_id", table_name="missing_person_submissions")
    op.drop_index("ix_mp_submissions_triage", table_name="missing_person_submissions")
    op.drop_index("ix_mp_submissions_case", table_name="missing_person_submissions")
    op.drop_index("ix_mp_submissions_org", table_name="missing_person_submissions")
    op.drop_table("missing_person_submissions")

    op.drop_index("uq_mp_cases_intake_token", table_name="missing_person_cases")
    op.drop_index("uq_mp_cases_reference", table_name="missing_person_cases")
    op.drop_index("ix_mp_cases_status", table_name="missing_person_cases")
    op.drop_index("ix_mp_cases_org", table_name="missing_person_cases")
    op.drop_index("ix_mp_cases_event", table_name="missing_person_cases")
    op.drop_table("missing_person_cases")
    op.drop_index("ix_disaster_events_org", table_name="disaster_events")
    op.drop_table("disaster_events")
