"""29: add rich profile fields to gear

Revision ID: wb_gear_profile_01
Revises: wb_equipment_01
Create Date: 2026-11-23 00:00:00.000000

Adds nullable bike/gear profile columns (dates, frame/size/color, model year,
groupset, specs, purchase source, and notes) to ``gear``. Existing rows are
untouched and receive ``NULL`` for every new column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "wb_gear_profile_01"
down_revision: str | None = "wb_equipment_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, str], ...] = (
    ("purchase_date", sa.Date(), "Gear purchase date (Date)"),
    ("retired_date", sa.Date(), "Gear retired date (Date)"),
    ("frame_number", sa.String(length=100), "Gear frame or serial number"),
    ("size", sa.String(length=50), "Gear size"),
    ("color", sa.String(length=100), "Gear color"),
    ("model_year", sa.SmallInteger(), "Gear retail model year"),
    ("groupset", sa.String(length=250), "Gear groupset or drivetrain"),
    ("specs", sa.Text(), "Additional gear specifications (multiline)"),
    ("purchase_source", sa.String(length=250), "Gear purchase or acquisition source"),
    ("notes", sa.Text(), "Gear notes and history (multiline)"),
)


def upgrade() -> None:
    """Add nullable profile columns to the gear table."""
    for name, col_type, comment in _COLUMNS:
        op.add_column(
            "gear",
            sa.Column(name, col_type, nullable=True, comment=comment),
        )


def downgrade() -> None:
    """Drop the profile columns added to the gear table."""
    for name, _col_type, _comment in reversed(_COLUMNS):
        op.drop_column("gear", name)
