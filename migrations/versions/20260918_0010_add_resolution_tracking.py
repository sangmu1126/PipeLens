"""Add automatic workflow resolution tracking.

Revision ID: 20260918_0010
Revises: 20260829_0009
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260918_0010"
down_revision: str | None = "20260829_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analyses", sa.Column("run_attempt", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column("analyses", sa.Column("head_branch", sa.String(length=255), nullable=True))
    op.add_column("analyses", sa.Column("pull_request_number", sa.Integer(), nullable=True))
    op.add_column(
        "analyses", sa.Column("run_completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("analyses", sa.Column("resolution_outcome", sa.String(length=32), nullable=True))
    op.add_column("analyses", sa.Column("resolution_run_id", sa.BigInteger(), nullable=True))
    op.add_column("analyses", sa.Column("resolution_run_attempt", sa.Integer(), nullable=True))
    op.add_column("analyses", sa.Column("resolution_html_url", sa.Text(), nullable=True))
    op.add_column(
        "analyses", sa.Column("resolution_completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("analyses", sa.Column("recovery_seconds", sa.Float(), nullable=True))
    op.create_index(
        "ix_analyses_resolution_lookup",
        "analyses",
        ["repository", "workflow_name", "head_branch", "resolution_outcome"],
    )


def downgrade() -> None:
    op.drop_index("ix_analyses_resolution_lookup", table_name="analyses")
    op.drop_column("analyses", "recovery_seconds")
    op.drop_column("analyses", "resolution_completed_at")
    op.drop_column("analyses", "resolution_html_url")
    op.drop_column("analyses", "resolution_run_attempt")
    op.drop_column("analyses", "resolution_run_id")
    op.drop_column("analyses", "resolution_outcome")
    op.drop_column("analyses", "run_completed_at")
    op.drop_column("analyses", "pull_request_number")
    op.drop_column("analyses", "head_branch")
    op.drop_column("analyses", "run_attempt")
