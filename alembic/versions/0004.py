"""Create enums and align timestamps

Revision ID: 0004
Revises: 0003
Create Date: 2025-02-20 12:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'section') THEN
                CREATE TYPE section AS ENUM ('text', 'image', 'video', 'audio', 'three_d', 'balance');
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'job_status') THEN
                CREATE TYPE job_status AS ENUM ('queued', 'processing', 'done', 'error');
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'drafts' AND column_name = 'section' AND udt_name <> 'section'
            ) THEN
                ALTER TABLE drafts
                    ALTER COLUMN section TYPE section
                    USING section::section;
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'jobs' AND column_name = 'section' AND udt_name <> 'section'
            ) THEN
                ALTER TABLE jobs
                    ALTER COLUMN section TYPE section
                    USING section::section;
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'jobs' AND column_name = 'status' AND udt_name <> 'job_status'
            ) THEN
                ALTER TABLE jobs
                    ALTER COLUMN status TYPE job_status
                    USING status::job_status;
            END IF;
        END$$;
        """
    )

    op.alter_column("users", "created_at", existing_type=sa.DateTime(), server_default=sa.text("now()"), existing_nullable=False)
    op.alter_column("drafts", "created_at", existing_type=sa.DateTime(), server_default=sa.text("now()"), existing_nullable=False)
    op.alter_column("drafts", "updated_at", existing_type=sa.DateTime(), server_default=sa.text("now()"), existing_nullable=False)
    op.alter_column("jobs", "created_at", existing_type=sa.DateTime(), server_default=sa.text("now()"), existing_nullable=False)
    op.alter_column("jobs", "updated_at", existing_type=sa.DateTime(), server_default=sa.text("now()"), existing_nullable=False)
    op.alter_column("prices", "updated_at", existing_type=sa.DateTime(), server_default=sa.text("now()"), existing_nullable=False)
    op.alter_column("ledger_entries", "created_at", existing_type=sa.DateTime(), server_default=sa.text("now()"), existing_nullable=False)


def downgrade() -> None:
    op.alter_column("ledger_entries", "created_at", existing_type=sa.DateTime(), server_default=None, existing_nullable=False)
    op.alter_column("prices", "updated_at", existing_type=sa.DateTime(), server_default=None, existing_nullable=False)
    op.alter_column("jobs", "updated_at", existing_type=sa.DateTime(), server_default=None, existing_nullable=False)
    op.alter_column("jobs", "created_at", existing_type=sa.DateTime(), server_default=None, existing_nullable=False)
    op.alter_column("drafts", "updated_at", existing_type=sa.DateTime(), server_default=None, existing_nullable=False)
    op.alter_column("drafts", "created_at", existing_type=sa.DateTime(), server_default=None, existing_nullable=False)
    op.alter_column("users", "created_at", existing_type=sa.DateTime(), server_default=None, existing_nullable=False)

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'jobs' AND column_name = 'status' AND udt_name = 'job_status'
            ) THEN
                ALTER TABLE jobs
                    ALTER COLUMN status TYPE VARCHAR(50)
                    USING status::text;
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'jobs' AND column_name = 'section' AND udt_name = 'section'
            ) THEN
                ALTER TABLE jobs
                    ALTER COLUMN section TYPE VARCHAR(50)
                    USING section::text;
            END IF;
        END$$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'drafts' AND column_name = 'section' AND udt_name = 'section'
            ) THEN
                ALTER TABLE drafts
                    ALTER COLUMN section TYPE VARCHAR(50)
                    USING section::text;
            END IF;
        END$$;
        """
    )
    op.execute("DROP TYPE IF EXISTS job_status")
    op.execute("DROP TYPE IF EXISTS section")
