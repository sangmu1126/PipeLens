"""Add sanitized execution context.

Revision ID: 20260829_0008
Revises: 20260829_0007
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0008"
down_revision: str | None = "20260829_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("execution_context", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "execution_context")
