"""add users

Revision ID: 001_users
Revises:
Create Date: 2026-05-05 12:00:00.000000

SPEC §3.1 users.

OpenSoma whoami 응답 (sidecar PoC #8 실측):
- userId: 로그인 username (이메일 형태) → soma_user_id
- userNo: 32자 hex GUID (예: 4558db6b39ea4b2a9a2ca5ff782a196b) → user_no
- userNm: 한글 이름 → user_name
- userGb: 'C'(연수생)/'T'(멘토) → role 매핑

email 컬럼은 별도로 두지 않음. soma_user_id 가 곧 이메일.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001_users"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("soma_user_id", sa.String(255), nullable=False, unique=True),
        sa.Column("user_no", sa.String(32), nullable=False, unique=True),
        sa.Column("user_name", sa.String(100), nullable=True),
        sa.Column(
            "role",
            sa.Enum("TRAINEE", "MENTOR", "EXPERT", "OPERATOR", name="user_role"),
            nullable=False,
            server_default="TRAINEE",
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            server_onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("users")
