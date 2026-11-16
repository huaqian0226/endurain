"""Owned gear reads published for activity workbench references."""

from sqlalchemy.orm import Session

import modules.gears.gear.crud as crud
import modules.gears.gear.schema as schema


def read_owned_gear(user_id: int, gear_id: int, db: Session) -> schema.GearRead | None:
    """Read an existing gear without creating, updating or projecting prices."""
    return crud.get_gear_user_by_id(user_id, gear_id, db)
