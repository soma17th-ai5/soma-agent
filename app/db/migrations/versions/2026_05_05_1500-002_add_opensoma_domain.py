"""add opensoma domain tables (notices, mentorings, applications, sync_state)

Revision ID: 002_opensoma_domain
Revises: 001_users
Create Date: 2026-05-05 15:00:00.000000

SPEC §3.1.

Tables:
- notices, notice_attachments
- mentorings, mentoring_applicants (HMAC name)
- applications (apply_sn + qustnr_sn 둘 다)
- sync_state (job별 last_run/last_success/last_error)

#13 (PDF 추출) 의 NoticeAttachment ORM 모델은 이 PR 머지 후 동시에 가용.
#14 의 webex_rooms / webex_messages 는 평행 head — 모두 머지 후 alembic merge heads 필요.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002_opensoma_domain"
down_revision: str | None = "001_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notices",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("notice_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("author", sa.String(200), nullable=True),
        sa.Column("created_at_text", sa.String(50), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column("content_html", sa.Text(), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("detail_url", sa.String(1000), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    op.create_index("ix_notices_posted_at", "notices", ["posted_at"])

    op.create_table(
        "notice_attachments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("notice_id", sa.BigInteger(), nullable=False),
        sa.Column("file_name", sa.String(500), nullable=True),
        sa.Column("file_url", sa.String(1000), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["notice_id"], ["notices.notice_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_notice_attachments_notice_id", "notice_attachments", ["notice_id"])

    op.create_table(
        "mentorings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("mentoring_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("mentoring_type", sa.String(50), nullable=True),
        sa.Column("registration_start_at", sa.DateTime(), nullable=True),
        sa.Column("registration_end_at", sa.DateTime(), nullable=True),
        sa.Column("session_date", sa.Date(), nullable=True),
        sa.Column("session_start_time", sa.Time(), nullable=True),
        sa.Column("session_end_time", sa.Time(), nullable=True),
        sa.Column("session_started_at", sa.DateTime(), nullable=True),
        sa.Column("attendees_current", sa.Integer(), nullable=True),
        sa.Column("attendees_max", sa.Integer(), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=True),
        sa.Column("mentoring_status", sa.String(20), nullable=True),
        sa.Column("author", sa.String(200), nullable=True),
        sa.Column("created_at_text", sa.String(50), nullable=True),
        sa.Column("content_html", sa.Text(), nullable=True),
        sa.Column("venue", sa.String(500), nullable=True),
        sa.Column("detail_url", sa.String(1000), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    op.create_index("ix_mentorings_session_started_at", "mentorings", ["session_started_at"])

    op.create_table(
        "mentoring_applicants",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("mentoring_id", sa.BigInteger(), nullable=False),
        sa.Column("applicant_name_hash", sa.String(32), nullable=False),
        sa.Column("applied_at_text", sa.String(50), nullable=True),
        sa.Column("cancelled_at_text", sa.String(50), nullable=True),
        sa.Column("applicant_status", sa.String(50), nullable=True),
        sa.Column("collected_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["mentoring_id"], ["mentorings.mentoring_id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_mentoring_applicants_mentoring_id", "mentoring_applicants", ["mentoring_id"]
    )

    op.create_table(
        "applications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("soma_user_id", sa.String(255), nullable=False),
        sa.Column("apply_sn", sa.BigInteger(), nullable=False),
        sa.Column("qustnr_sn", sa.BigInteger(), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("target_url", sa.String(1000), nullable=True),
        sa.Column("author", sa.String(200), nullable=True),
        sa.Column("session_date_text", sa.String(100), nullable=True),
        sa.Column("applied_at_text", sa.String(50), nullable=True),
        sa.Column("application_status", sa.String(50), nullable=True),
        sa.Column("approval_status", sa.String(50), nullable=True),
        sa.Column("application_detail", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("cached_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("soma_user_id", "apply_sn", name="uq_user_apply_sn"),
    )
    op.create_index("ix_applications_soma_user_id", "applications", ["soma_user_id"])

    op.create_table(
        "sync_state",
        sa.Column("job_name", sa.String(100), primary_key=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sync_state")
    op.drop_index("ix_applications_soma_user_id", table_name="applications")
    op.drop_table("applications")
    op.drop_index("ix_mentoring_applicants_mentoring_id", table_name="mentoring_applicants")
    op.drop_table("mentoring_applicants")
    op.drop_index("ix_mentorings_session_started_at", table_name="mentorings")
    op.drop_table("mentorings")
    op.drop_index("ix_notice_attachments_notice_id", table_name="notice_attachments")
    op.drop_table("notice_attachments")
    op.drop_index("ix_notices_posted_at", table_name="notices")
    op.drop_table("notices")
