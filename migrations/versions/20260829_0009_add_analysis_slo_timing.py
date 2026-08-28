"""Add analysis SLO timing.

Revision ID: 20260829_0009
Revises: 20260829_0008
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0009"
down_revision: str | None = "20260829_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("queue_wait_seconds", sa.Float(), nullable=True))
    op.add_column("analyses", sa.Column("total_latency_seconds", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "total_latency_seconds")
    op.drop_column("analyses", "queue_wait_seconds")
