"""add sample creator profile snapshot

Revision ID: df36e7f8a9b0
Revises: ce25d6e7f8a9
Create Date: 2026-09-10 16:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "df36e7f8a9b0"
down_revision: str | None = "ce25d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sample_applications",
        sa.Column("creator_avatar_object_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "sample_applications",
        sa.Column("creator_avatar_source_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "sample_applications",
        sa.Column(
            "creator_avatar_observed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "sample_applications",
        sa.Column("creator_profile_snapshot", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column(
        "sample_applications",
        sa.Column("creator_profile_source_type", sa.String(length=32)),
    )
    op.add_column(
        "sample_applications",
        sa.Column("creator_profile_observed_at", sa.DateTime(timezone=True)),
    )
    op.create_check_constraint(
        "ck_sample_applications_creator_profile_source",
        "sample_applications",
        "creator_profile_source_type IS NULL OR "
        "creator_profile_source_type IN ('official_api', 'hubstudio_cdp')",
    )
    op.create_check_constraint(
        "ck_sample_applications_creator_avatar_bundle",
        "sample_applications",
        "(creator_avatar_object_key IS NULL AND "
        "creator_avatar_source_hash IS NULL AND "
        "creator_avatar_observed_at IS NULL) OR "
        "(creator_avatar_object_key IS NOT NULL AND "
        "creator_avatar_source_hash IS NOT NULL AND "
        "creator_avatar_observed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_sample_applications_creator_profile_bundle",
        "sample_applications",
        "(creator_profile_snapshot IS NULL AND "
        "creator_profile_source_type IS NULL AND "
        "creator_profile_observed_at IS NULL) OR "
        "(creator_profile_snapshot IS NOT NULL AND "
        "creator_profile_source_type IS NOT NULL AND "
        "creator_profile_observed_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_sample_applications_creator_profile_bundle",
        "sample_applications",
        type_="check",
    )
    op.drop_constraint(
        "ck_sample_applications_creator_avatar_bundle",
        "sample_applications",
        type_="check",
    )
    op.drop_constraint(
        "ck_sample_applications_creator_profile_source",
        "sample_applications",
        type_="check",
    )
    op.drop_column("sample_applications", "creator_profile_observed_at")
    op.drop_column("sample_applications", "creator_profile_source_type")
    op.drop_column("sample_applications", "creator_profile_snapshot")
    op.drop_column("sample_applications", "creator_avatar_observed_at")
    op.drop_column("sample_applications", "creator_avatar_source_hash")
    op.drop_column("sample_applications", "creator_avatar_object_key")
