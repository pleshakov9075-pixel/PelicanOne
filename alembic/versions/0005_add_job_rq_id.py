"""Add rq_job_id to jobs

Revision ID: 0005
Revises: 0004
Create Date: 2025-02-20 12:30:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("rq_job_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "rq_job_id")
