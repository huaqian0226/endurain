"""Store reusable route snapshots and per-trip TREK receipts."""

import sqlalchemy as sa
from alembic import op

revision = "wb_saved_routes_01"
down_revision = "wb_gear_group_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workbench_saved_routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_activity_id", sa.Integer(), sa.ForeignKey("activities.id", ondelete="SET NULL")),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("activity_type", sa.Integer(), nullable=False),
        sa.Column("point_count", sa.Integer(), nullable=False),
        sa.Column("geometry", sa.JSON(), nullable=False),
        sa.UniqueConstraint("user_id", "source_activity_id"),
    )
    op.create_table(
        "workbench_saved_route_trips",
        sa.Column(
            "route_id", sa.Integer(), sa.ForeignKey("workbench_saved_routes.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("trip_id", sa.Integer(), primary_key=True),
        sa.Column("tour_id", sa.Integer(), nullable=True),
        sa.Column("sent_points", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("workbench_saved_route_trips")
    op.drop_table("workbench_saved_routes")
