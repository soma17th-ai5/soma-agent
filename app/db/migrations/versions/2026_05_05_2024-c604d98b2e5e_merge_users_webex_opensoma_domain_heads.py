"""merge users + webex + opensoma_domain heads

Revision ID: c604d98b2e5e
Revises: 001_webex, 002_opensoma_domain
Create Date: 2026-05-05 20:24:49.387364+09:00
"""
from collections.abc import Sequence

revision: str = 'c604d98b2e5e'
down_revision: str | None = ('001_webex', '002_opensoma_domain')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
