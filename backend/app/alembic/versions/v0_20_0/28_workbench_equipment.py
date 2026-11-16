"""Add owned workbench mappings and confirmed activity equipment."""

from alembic import op
import sqlalchemy as sa

revision = "wb_equipment_01"
down_revision = "d54bdd779392"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "activities", sa.Column("equipment_confirmed", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.create_table(
        "workbench_vehicles",
        sa.Column("vehicle_uuid", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gear_id", sa.Integer(), sa.ForeignKey("gear.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instance_id", sa.String(100), nullable=False),
        sa.Column("excluded_activity_ids", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("user_id", "gear_id"),
    )
    op.create_table(
        "activity_equipment",
        sa.Column("activity_id", sa.Integer(), sa.ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("asset_id", sa.String(36), primary_key=True),
        sa.Column("use_mode", sa.String(16), nullable=False),
        sa.Column("catalog_revision", sa.String(250), nullable=False),
        sa.Column("confirmed_at", sa.String(40), nullable=False),
    )


def downgrade():
    op.drop_table("activity_equipment")
    op.drop_table("workbench_vehicles")
    op.drop_column("activities", "equipment_confirmed")
