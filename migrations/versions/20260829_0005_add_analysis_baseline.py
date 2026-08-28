"""Add analysis comparison baseline.

Revision ID: 20260829_0005
Revises: 20260828_0004
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0005"
down_revision: str | None = "20260828_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("baseline_sha", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "baseline_sha")
