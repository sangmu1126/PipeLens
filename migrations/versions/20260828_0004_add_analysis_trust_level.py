"""Add analysis trust level.

Revision ID: 20260828_0004
Revises: 20260828_0003
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_0004"
down_revision: str | None = "20260828_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analyses",
        sa.Column(
            "trust_level",
            sa.String(length=32),
            server_default="trusted",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("analyses", "trust_level")
