"""Public metadata of a reusable route and its TREK destination."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class RouteName(BaseModel):
    """User-visible name for a snapshot."""

    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160, pattern=r"^[^\x00-\x1f\x7f]+$")
    ]


class RouteRead(BaseModel):
    """List metadata only. Geometry stays server-side."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    activity_type: int
    point_count: int
    source_activity_id: int | None


class TripChoice(BaseModel):
    """Trip metadata required by the destination picker."""

    id: int
    title: str


class SendResult(BaseModel):
    """An acknowledged transfer, including the actual export resolution."""

    already_added: bool
    tour_id: int | None
    sent_points: int
