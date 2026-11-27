# Journeys for John: the whole trip to a place, step by step, from Google's Routes API (walks, each train or bus with
# its line, stops and times, transfers, or a drive), planned from home with Nestor's own Google key; "drive (or walk)
# to the station, then the train" is planned as two parts. By transit, a walk becomes a Rutgers campus bus when one
# helps (always, by bus). The last journey is kept, so John can answer follow-ups, the wall can show it, and "make it a
# plan" can send it to Datebook.
import datetime
import json
import logging
import urllib.request
from nestor import campus_buses
from nestor import weather
from nestor.config import load_secrets
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
ROUTE_FIELDS = ("routes.duration,routes.legs.steps.travelMode,routes.legs.steps.staticDuration,"
                "routes.legs.steps.transitDetails,routes.legs.steps.startLocation,routes.legs.steps.endLocation")
PLACE_FIELDS = "places.displayName,places.formattedAddress"
MODES = {"transit": "TRANSIT", "bus": "TRANSIT", "walk": "WALK", "drive": "DRIVE"}  # bus: a Rutgers campus bus
ONLY = {"train": "TRAIN", "bus": "BUS"}
STATION_SPARE_MINUTES = 5  # Between getting to the station and the train leaving, in a two-part journey
NEAR_KM = 60  # Places are looked for around home first
KEEP_MINUTES = 60  # The wall shows the last journey for this long after it was planned
TIMEOUT_SECONDS = 15
BUS_TYPES = ("BUS", "INTERCITY_BUS", "TROLLEYBUS")
SUBWAY_TYPES = ("SUBWAY", "METRO_RAIL", "TRAM", "MONORAIL", "LIGHT_RAIL")
last = None  # The last journey planned (see plan), for follow-ups, the wall and "make it a plan"
log = logging.getLogger(__name__)

# A time of day as John and the wall say it, "2:20 PM"
def clock(moment):
    return f"{moment.hour % 12 or 12}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"

# Nestor's Google Maps key from .env; raises ValueError without one
def maps_key():
    key = load_secrets().get("GOOGLE_MAPS_KEY", "")

    # Without a key there's nothing to ask
    if not key:
        raise ValueError("there's no GOOGLE_MAPS_KEY in Nestor's .env, so journeys can't be planned yet")
    return key

# Ask one of Google's APIs (Routes or Places) and return its JSON reply
def post(url, key, fields, body):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": key, "X-Goog-FieldMask": fields})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
        return json.loads(reply.read().decode())

# Where journeys start: home_address from config.yaml, else the home_location's coordinates
def home_origin(settings):
    address = str(settings.get("home_address") or "").strip()

    # A street address is best; the town's coordinates will do
    if address:
        return {"address": address}
    home = weather.find_location(str(settings.get("home_location") or "").strip())
    return {"location": {"latLng": {"latitude": home["latitude"], "longitude": home["longitude"]}}}

# Find a place by what was said ("Menlo Park Mall", "the Busch campus center"), near home first; returns its name and
# address, or the words as they are when Google doesn't know it
def find_place(key, words, origin):
    body = {"textQuery": words, "maxResultCount": 1}
    spot = (origin.get("location") or {}).get("latLng")

    # Look near home when home's coordinates are known
    if spot:
        body["locationBias"] = {"circle": {"center": spot, "radius": NEAR_KM * 1000.0}}

    # A failed look-up keeps the words, which Routes can still try
    try:
        found = (post(PLACES_URL, key, PLACE_FIELDS, body).get("places") or [None])[0]
    except Exception as error:
        log.warning("Place look-up for %r failed: %s", words, error)
        found = None

    # Google's name and address, or the words
    if not found:
        return {"name": words, "address": words}
    return {"name": (found.get("displayName") or {}).get("text") or words,
            "address": found.get("formattedAddress") or words}

# A time as Google wants it (UTC, like "2026-11-25T19:20:00Z")
def google_time(moment):
    return moment.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# Ask Google for a route between two places by a mode, leaving at a time or arriving by one, transit limited to
# trains or buses when asked; returns the route (or raises ValueError when there's none)
def route(key, origin, destination, mode, leave_at=None, arrive_by=None, only=""):
    body = {"origin": origin, "destination": destination, "travelMode": mode}

    # Driving uses live traffic; transit is timed and can be limited
    if mode == "DRIVE":
        body["routingPreference"] = "TRAFFIC_AWARE"
        if leave_at:
            body["departureTime"] = google_time(leave_at)
    elif mode == "TRANSIT":
        # Arriving by a time, or leaving at one
        if arrive_by:
            body["arrivalTime"] = google_time(arrive_by)
        elif leave_at:
            body["departureTime"] = google_time(leave_at)

        if only in ONLY:
            body["transitPreferences"] = {"allowedTravelModes": [ONLY[only]]}
    routes = post(ROUTES_URL, key, ROUTE_FIELDS, body).get("routes") or []

    # No route at all
    if not routes:
        raise ValueError("Google found no way to get there like that")
    return routes[0]

# A length of time from Google ("360s") in seconds
def seconds(text):
    try:
        return float(str(text).rstrip("s"))
    except ValueError:
        return 0.0

# A time from Google in local time (None when missing)
def local_time(text):
    # Missing or odd times are left out
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
    except (AttributeError, ValueError):
        return None

# One step of a journey: its kind (walk, train, bus, subway, drive or arrive), what it is, a line under it, the
# line's short name and colour, when it starts and ends, and where (latitude, longitude; None when not known)
def journey_step(kind, title, under, starts, ends, line="", color="", start=None, end=None):
    return {"kind": kind, "title": title, "under": under, "line": line, "color": color, "starts": starts, "ends": ends,
            "from_spot": start, "to_spot": end}

# A spot from Google ({"latLng": {"latitude": .., "longitude": ..}}) as (latitude, longitude), or None
def spot_of(location):
    lat_lng = (location or {}).get("latLng") or {}
    return (lat_lng["latitude"], lat_lng["longitude"]) if "latitude" in lat_lng and "longitude" in lat_lng else None

# Read Google's route into steps toward a place: walks (and drives) joined, each ride with its line, headsign, stops
# and times, walks before and between rides ending when the next ride leaves; a route with no rides is timed from
# when you leave (or back from when you mean to arrive)
def steps_of(found, place_name, mode, leave_at, arrive_by):
    pieces = []

    # Each of Google's steps, joining walks or drives that follow each other
    for step in (leg_step for leg in found.get("legs") or [] for leg_step in leg.get("steps") or []):
        step_mode = step.get("travelMode", "")
        length = seconds(step.get("staticDuration", "0s"))
        start, end = spot_of(step.get("startLocation")), spot_of(step.get("endLocation"))

        # A ride stands alone; a walk or drive joins the one before it
        if step_mode == "TRANSIT":
            pieces.append({"mode": step_mode, "seconds": length, "ride": step.get("transitDetails") or {},
                           "start": start, "end": end})
        elif pieces and pieces[-1]["mode"] == step_mode:
            pieces[-1]["seconds"] += length
            pieces[-1]["end"] = end
        else:
            pieces.append({"mode": step_mode, "seconds": length, "ride": None, "start": start, "end": end})
    rides = [index for index, piece in enumerate(pieces) if piece["ride"] is not None]
    total = seconds(found.get("duration", "0s"))

    # Without rides: one walk or drive
    if not rides:
        leave = arrive_by - datetime.timedelta(seconds=total) if arrive_by else leave_at or datetime.datetime.now()
        arrive = leave + datetime.timedelta(seconds=total)
        minutes = round(total / 60)
        kind = "drive" if mode == "DRIVE" else "walk"
        start, end = (pieces[0]["start"], pieces[-1]["end"]) if pieces else (None, None)
        return [journey_step(kind, f"Leave · {minutes} min {kind}", f"to {place_name}", leave, arrive, start=start,
                             end=end), journey_step("arrive", f"Arrive · {place_name}", "", arrive, arrive)]
    at = local_time(pieces[rides[0]]["ride"].get("stopDetails", {}).get("departureTime"))
    steps = []

    # Each piece in turn, walks timed from the rides around them
    for index, piece in enumerate(pieces):
        ride = piece["ride"]

        # A walk, or a ride with its own times
        if ride is None:
            minutes = round(piece["seconds"] / 60) or 1
            after = next((pieces[later]["ride"] for later in rides if later > index), None)
            toward = ((after or {}).get("stopDetails", {}).get("departureStop", {}).get("name")) or place_name
            starts = at - datetime.timedelta(seconds=piece["seconds"]) if index < rides[0] else at
            ends = starts + datetime.timedelta(seconds=piece["seconds"])
            steps.append(journey_step("walk", f"Leave · {minutes} min walk" if index == 0 else f"{minutes} min walk",
                                      f"to {toward}", starts, ends, start=piece["start"], end=piece["end"]))
            at = max(at, ends)
        else:
            stops = ride.get("stopDetails") or {}
            departs = local_time(stops.get("departureTime")) or at
            arrives = local_time(stops.get("arrivalTime")) or departs + datetime.timedelta(seconds=piece["seconds"])
            line = ride.get("transitLine") or {}
            vehicle = (line.get("vehicle") or {}).get("type", "")
            short = line.get("nameShort") or line.get("name") or ""
            number = ride.get("tripShortText") or ""
            kind = "bus" if vehicle in BUS_TYPES else "subway" if vehicle in SUBWAY_TYPES else "train"
            headsign = f" toward {ride['headsign']}" if ride.get("headsign") else ""

            # Buses by their route, subways by their line, trains by their number
            if kind == "bus":
                name = f"Bus {short}".strip()
            elif kind == "subway":
                name = line.get("name") or "Subway"
            else:
                name = f"Train {number}" if number else "Train"
            count = ride.get("stopCount") or 0
            under = " · ".join(part for part in (f"{round((arrives - departs).total_seconds() / 60)} min",
                                                 f"{count} stops" if count else "",
                                                 f"from {stops.get('departureStop', {}).get('name', '')}",
                                                 f"off at {stops.get('arrivalStop', {}).get('name', '')}") if part)
            steps.append(journey_step(kind, name + headsign, under, departs, arrives, short, line.get("color", ""),
                                      spot_of(stops.get("departureStop", {}).get("location")),
                                      spot_of(stops.get("arrivalStop", {}).get("location"))))
            at = arrives
    steps.append(journey_step("arrive", f"Arrive · {place_name}", "", steps[-1]["ends"], steps[-1]["ends"]))
    return steps

# Plan a journey and keep it as the last one: to a place (words), by transit, walking or driving, transit limited to
# trains or buses, leaving at a time (now by default) or arriving by one; first_by ("drive" or "walk") with a station
# plans it as two parts, to the station and then transit from it. Raises ValueError when it can't be planned
def plan(settings, to, mode="transit", only="", leave_at=None, arrive_by=None, first_by="", station="", asked=""):
    global last
    key = maps_key()
    origin = home_origin(settings)
    place = find_place(key, to, origin)
    google_mode = MODES.get(mode, "TRANSIT")
    destination = {"address": place["address"]}

    # One part, or two: to the station by car or on foot, then transit from the station
    if first_by in ("drive", "walk") and station:
        stop = find_place(key, f"{station} station", origin)
        first_mode = MODES[first_by]
        to_station = {"address": stop["address"]}

        # Arriving by a time plans the transit part first, then the way to the station back from its first ride
        if arrive_by:
            second = steps_of(route(key, to_station, destination, "TRANSIT", None, arrive_by, only), place["name"],
                              "TRANSIT", None, arrive_by)
            by_station = second[0]["starts"] - datetime.timedelta(minutes=STATION_SPARE_MINUTES)
            first = steps_of(route(key, origin, to_station, first_mode, None, by_station), stop["name"], first_mode,
                             None, by_station)
        else:
            start = leave_at or datetime.datetime.now()
            first = steps_of(route(key, origin, to_station, first_mode, start), stop["name"], first_mode, start, None)
            at_station = first[-1]["ends"] + datetime.timedelta(minutes=STATION_SPARE_MINUTES)
            second = steps_of(route(key, to_station, destination, "TRANSIT", at_station, None, only), place["name"],
                              "TRANSIT", at_station, None)
        steps = first[:-1] + second
    else:
        steps = steps_of(route(key, origin, destination, google_mode, leave_at, arrive_by, only), place["name"],
                         google_mode, leave_at, arrive_by)

    # By transit or bus, a walk can become a campus bus (a bus problem keeps Google's journey)
    if mode in ("transit", "bus"):
        try:
            steps = campus_buses.with_live(campus_buses.with_campus_buses(steps, forced=mode == "bus"))
        except (KeyError, ValueError, TypeError, OSError) as error:
            log.warning("Campus buses skipped: %s", error)
    leave, arrive = steps[0]["starts"], steps[-1]["ends"]
    last = {"to": to, "name": place["name"], "address": place["address"], "mode": mode, "only": only,
            "first_by": first_by, "station": station, "asked": asked or f"How do I get to {place['name']}?",
            "steps": steps, "leave": leave, "arrive": arrive, "minutes": round((arrive - leave).total_seconds() / 60),
            "planned": datetime.datetime.now()}
    return last

# John's one line about a journey: "Leave at 2:12, a 6 min walk, the 2:20 bus 810, there by 2:50."
def summary(journey):
    parts = [f"Leave at {clock(journey['leave'])}"]

    # The walks, drives and rides in a few words each
    for step in journey["steps"]:
        minutes = round((step["ends"] - step["starts"]).total_seconds() / 60)

        # Walks and drives by their length, rides by when and what
        if step["kind"] in ("walk", "drive"):
            parts.append(f"a {minutes} min {step['kind']}")
        elif step["kind"] == "bus":
            parts.append(f"the {clock(step['starts'])} bus {step['line']}".rstrip())
        elif step["kind"] in ("train", "subway"):
            parts.append(f"the {clock(step['starts'])} {step['title'].split(' toward')[0]}")
    return ", ".join(parts) + f", there by {clock(journey['arrive'])}."

# The last journey for the wall's preview screen (None when there's none, or it was planned over an hour ago)
def wall_screen(now=None):
    now = now or datetime.datetime.now()

    # Only a recent journey
    if not last or now - last["planned"] > datetime.timedelta(minutes=KEEP_MINUTES):
        return None
    hours, minutes = divmod(last["minutes"], 60)
    total = f"{hours} h {minutes} min" if hours and minutes else f"{hours} h" if hours else f"{minutes} min"
    return {"title": last["name"], "asked": last["asked"], "line": summary(last), "total": total,
            "arrive": clock(last["arrive"]),
            "steps": [{"time": clock(step["starts"]).replace(" AM", "").replace(" PM", ""), "title": step["title"],
                       "under": step["under"], "kind": step["kind"], "line": step["line"], "color": step["color"],
                       "late": False, "warn": step["kind"] == "arrive", "earlier": ""} for step in last["steps"]]}

# The last journey as a Datebook plan: its title, start (when it arrives), place and travel mode, for "make it a plan"
def as_plan(title=""):
    # Nothing planned, nothing to save
    if not last:
        raise ValueError("there's no journey to make a plan of; plan one first")
    mode = {"transit": "TRANSIT", "bus": "BUS", "walk": "WALK", "drive": "DRIVE"}.get(last["mode"], "TRANSIT")
    return {"title": title or last["name"], "start": last["arrive"].strftime("%Y-%m-%dT%H:%M"),
            "place": last["address"], "mode": mode}
