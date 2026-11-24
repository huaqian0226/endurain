"""Add nullable group_name column to gear table.

Revision ID: wb_gear_group_01
Revises: wb_api_key_temp_scopes_01
Create Date: 2026-11-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "wb_gear_group_01"
down_revision: str | None = "wb_api_key_temp_scopes_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "gear",
        sa.Column(
            "group_name",
            sa.String(length=100),
            nullable=True,
            comment="Optional user-defined gear group name",
        ),
    )


def downgrade() -> None:
    op.drop_column("gear", "group_name")
