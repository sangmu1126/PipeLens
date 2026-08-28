"""Add analysis timing and stage history.

Revision ID: 20260829_0006
Revises: 20260829_0005
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260829_0006"
down_revision: str | None = "20260829_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analyses", sa.Column("analysis_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "analyses", sa.Column("analysis_completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("analyses", sa.Column("duration_seconds", sa.Float(), nullable=True))
    op.create_table(
        "analysis_stage_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["analyses.run_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analysis_stage_events_occurred_at", "analysis_stage_events", ["occurred_at"]
    )
    op.create_index("ix_analysis_stage_events_run_id", "analysis_stage_events", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_stage_events_run_id", table_name="analysis_stage_events")
    op.drop_index("ix_analysis_stage_events_occurred_at", table_name="analysis_stage_events")
    op.drop_table("analysis_stage_events")
    op.drop_column("analyses", "duration_seconds")
    op.drop_column("analyses", "analysis_completed_at")
    op.drop_column("analyses", "analysis_started_at")
