"""Save activity geometry for reuse and send it through TREK's native Tours import."""

import logging
import math
from collections.abc import Callable
from xml.etree import ElementTree as ET

import gpxpy
from sqlalchemy.orm import Session

import core.exceptions as errors
import modules.activities.activity.integration_service as activities
import modules.activities.saved_routes.crud as crud
from modules.activities.activity_streams.integration_service import get_stream_for_derivation
from modules.activities.saved_routes.schema import RouteRead, SendResult, TripChoice

BIKE = {4: "road", 5: "gravel", 6: "mtb", 27: "touring", 29: "gravel", 35: "touring", 36: "mtb"}
RUN = {1: "running", 2: "trail", 34: "running"}
WALK = {11, 12}
logger = logging.getLogger(__name__)
GPX_LIMIT = 1_000_000


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _snapshot(activity_id: int, db: Session) -> list:
    stream = get_stream_for_derivation(activity_id, 7, db)
    heights = get_stream_for_derivation(activity_id, 4, db)
    by_time = (
        {p["time"]: p.get("ele") for p in heights.stream_waypoints if isinstance(p.get("time"), (int, float, str))}
        if heights
        else {}
    )
    points = []
    for pt in stream.stream_waypoints if stream else []:
        lat, lon = _number(pt.get("lat")), _number(pt.get("lon"))
        if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
            continue
        position = [round(lat, 7), round(lon, 7)]
        if points and position == points[-1][:2]:
            continue
        stamp = pt.get("time")
        height = _number(pt.get("ele"))
        if height is None and isinstance(stamp, (int, float, str)):
            height = _number(by_time.get(stamp))
        points.append([*position, round(height, 2) if height is not None else None])
    if len(points) < 2:
        raise errors.InvalidInputError("This activity needs at least two distinct GPS points.")
    return points


def save_route(owner: int, activity_id: int, name: str, db: Session) -> RouteRead:
    """Serialize repeated saves on the owned activity before storing an immutable snapshot."""
    activity_type = activities.lock_owned_activity_type(activity_id, owner, db)
    if activity_type is None:
        raise errors.NotFoundError()
    found = crud.by_activity(owner, activity_id, db)
    if found:
        return RouteRead.model_validate(found)
    if activity_type not in (BIKE.keys() | RUN.keys() | WALK):
        raise errors.InvalidInputError("Choose an outdoor ride, run, walk or hike.")
    points = _snapshot(activity_id, db)
    route = crud.add_snapshot(owner, activity_id, name, activity_type, points, db)
    db.commit()
    logger.info("Saved activity route %d", route.id)
    return RouteRead.model_validate(route)


def routes_for(owner: int, db: Session) -> list[RouteRead]:
    """Return saved route metadata newest first."""
    return [RouteRead.model_validate(route) for route in crud.all_routes(owner, db)]


def trip_choices(owner: int, call_trek: Callable) -> list[TripChoice]:
    """List active TREK destinations for the mapped owner."""
    return [TripChoice.model_validate(trip) for trip in call_trek(owner, "list_trips", {})["trips"]]


def _gpx(name: str, points: list) -> tuple[str, int]:
    """Keep the full snapshot locally. Only sample the transfer if it exceeds TREK's limit."""

    def render(count: int) -> str:
        gpx = ET.Element("gpx", version="1.1", creator="Endurain", xmlns="http://www.topografix.com/GPX/1/1")
        track = ET.SubElement(gpx, "trk")
        ET.SubElement(track, "name").text = name
        segment = ET.SubElement(track, "trkseg")
        for i in range(count):
            lat, lon, ele = points[round(i * (len(points) - 1) / (count - 1))]
            node = ET.SubElement(segment, "trkpt", lat=str(lat), lon=str(lon))
            if ele is not None:
                ET.SubElement(node, "ele").text = str(ele)
        return ET.tostring(gpx, encoding="unicode")

    count = min(len(points), 32_000)
    xml = render(count)
    while len(xml) > GPX_LIMIT:
        count = max(2, int(count * GPX_LIMIT / len(xml) * 0.98))
        xml = render(count)
    return xml, count


def send_route(owner: int, route_id: int, trip_id: int, call_trek: Callable, db: Session) -> SendResult:
    """Write one tour per destination; retry against TREK's own GPX duplicate check after an interrupted response."""
    route = crud.lock_route(owner, route_id, db)
    if route is None:
        raise errors.NotFoundError()
    receipt = crud.receipt_for(route_id, trip_id, db)
    if receipt:
        return SendResult(already_added=True, tour_id=receipt.tour_id, sent_points=receipt.sent_points)
    xml, count = _gpx(route.name, route.geometry)
    args = {"tripId": trip_id, "gpx": xml, "file_name": route.name + ".gpx", "tour_type": "hike"}
    if route.activity_type in BIKE:
        args.update(tour_type="bike", bike_profile=BIKE[route.activity_type])
    elif route.activity_type in RUN:
        args.update(tour_type="run", run_profile=RUN[route.activity_type])
    tour_id, already_added = _import_matching_tour(owner, args, call_trek)
    if tour_id is None:
        # TREK considers a name and start a duplicate, even when two loops diverge.
        alternate = f"{route.name} (Endurain {route.id})"
        args.update(gpx=_gpx(alternate, route.geometry)[0], file_name=alternate + ".gpx")
        tour_id, already_added = _import_matching_tour(owner, args, call_trek)
    if tour_id is None:
        raise errors.ConflictError("TREK already has a different tour using both route names.")
    crud.store_receipt(route_id, trip_id, tour_id, count, db)
    db.commit()
    logger.info("Acknowledged TREK saved-route transfer for route %d", route_id)
    return SendResult(already_added=already_added, tour_id=tour_id, sent_points=count)


def _geometry(gpx: str) -> list[tuple]:
    """Normalize numeric GPX serialization for interrupted writes and same-start collisions."""
    track = gpxpy.parse(gpx).tracks[0]
    return [
        (round(p.latitude, 6), round(p.longitude, 6), None if p.elevation is None else round(p.elevation, 1))
        for seg in track.segments
        for p in seg.points
    ]


def _import_matching_tour(owner: int, args: dict, call_trek: Callable) -> tuple[int | None, bool]:
    reply = call_trek(owner, "import_tour_gpx", args)
    if tours := reply.get("tours"):
        return tours[0]["place_id"], False
    if reply.get("skipped") != 1:
        raise errors.UpstreamError("TREK did not report a tour or a duplicate.")
    destination = {"tripId": args["tripId"]}
    name = args["file_name"].removesuffix(".gpx")
    points = _geometry(args["gpx"])
    for tour in call_trek(owner, "list_tours", destination)["tours"]:
        if tour["name"] != name or tour["tour_type"] != args["tour_type"]:
            continue
        data = call_trek(owner, "export_tour_gpx", dict(destination, placeId=tour["place_id"]))
        if _geometry(data["gpx"]) == points:
            return tour["place_id"], True
    return None, False
