"""30: add temporary scope elevation columns to users_api_keys

Revision ID: wb_api_key_temp_scopes_01
Revises: wb_gear_profile_01
Create Date: 2026-11-24 00:00:00.000000

Adds nullable ``temp_scopes`` and ``temp_scopes_expires_at`` columns to
``users_api_keys`` for temporary, time-bounded scope elevation. Existing keys
are untouched and receive ``NULL`` for both columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "wb_api_key_temp_scopes_01"
down_revision: str | None = "wb_gear_profile_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, str], ...] = (
    ("temp_scopes", sa.Text(), "JSON-encoded list of temporary elevated scope strings"),
    (
        "temp_scopes_expires_at",
        sa.DateTime(timezone=True),
        "Temporary scope elevation expiration timestamp",
    ),
)


def upgrade() -> None:
    """Add nullable temporary scope elevation columns to users_api_keys."""
    for name, col_type, comment in _COLUMNS:
        op.add_column(
            "users_api_keys",
            sa.Column(name, col_type, nullable=True, comment=comment),
        )


def downgrade() -> None:
    """Drop the temporary scope elevation columns from users_api_keys."""
    for name, _col_type, _comment in reversed(_COLUMNS):
        op.drop_column("users_api_keys", name)
