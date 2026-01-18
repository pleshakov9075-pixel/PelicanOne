"""Use BIGINT for telegram_id

Revision ID: 0003
Revises: 0002
Create Date: 2025-02-20 00:00:00
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_constraint("users_telegram_id_key", "users", type_="unique")
    op.alter_column(
        "users",
        "telegram_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        nullable=False,
    )
    op.create_unique_constraint("users_telegram_id_key", "users", ["telegram_id"])
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])


def downgrade() -> None:
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_constraint("users_telegram_id_key", "users", type_="unique")
    op.alter_column(
        "users",
        "telegram_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        nullable=False,
    )
    op.create_unique_constraint("users_telegram_id_key", "users", ["telegram_id"])
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])
