# Rutgers campus buses for John: the timetable (TripShot's free GTFS feed, downloaded weekly into data/), the next buses
# from a stop with their live times (TripShot's GTFS-realtime trip updates), and a journey's walk swapped for a campus
# bus when it lets you leave later or get there sooner, the same way Datebook does
import csv
import datetime
import io
import logging
import math
import os
import threading
import time
import urllib.request
import zipfile
from nestor.config import DATA_DIR
TIMETABLE_URL = "https://rutgers.tripshot.com/v1/gtfs.zip"
LIVE_URL = "https://rutgers.tripshot.com/v1/gtfs/realtime/tripUpdate"
FOLDER = os.path.join(DATA_DIR, "rutgers-buses")
KEPT_FILES = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt", "calendar.txt", "calendar_dates.txt",
              "frequencies.txt")
REFRESH_SECONDS = 7 * 24 * 3600  # the timetable is fetched again after a week
LIVE_SECONDS = 30  # live times are kept this long
MAX_WALK_MINUTES = 15  # the farthest walk to or from a stop
WALK_METERS_PER_MINUTE = 80
DETOUR = 1.25  # streets aren't straight lines
MIN_GAIN_MINUTES = 3  # a bus has to save at least this much to replace a walk
SEARCH = datetime.timedelta(hours=2)  # how far around a time buses are looked for
TIMEOUT_SECONDS = 30
SCHEDULED = "Scheduled"
log = logging.getLogger(__name__)
table = None  # the timetable, read once
live = (0, {})  # when the live times were fetched, and them

# Download a URL's bytes, or None on any failure
def download(url):
    # Any network problem means nothing
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Nestor"}),
                                    timeout=TIMEOUT_SECONDS) as reply:
            return reply.read()
    except OSError as error:
        log.warning("Campus bus download failed: %s", error)
        return None

# A GTFS file's rows as dicts
def rows(text):
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))

# "08:05:30" (hours can pass 24 for runs after midnight) as seconds after midnight, or -1 when blank
def seconds_of(text):
    parts = str(text or "").strip().split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]) if len(parts) == 3 else -1

# Read the timetable from its GTFS files (name → text): stops, routes, runs (each with its stops and times), the days
# each service runs, and the runs that repeat every few minutes
def parse_timetable(files):
    stops = {row["stop_id"]: {"id": row["stop_id"], "name": row["stop_name"].strip(), "lat": float(row["stop_lat"]),
                              "lon": float(row["stop_lon"])}
             for row in rows(files.get("stops.txt", "")) if row.get("stop_lat") and row.get("stop_lon")}
    routes = {row["route_id"]: {"id": row["route_id"], "short": row.get("route_short_name") or
                                row.get("route_long_name", ""), "color": row.get("route_color", "")}
              for row in rows(files.get("routes.txt", ""))}
    times = {}

    # Each stop time, grouped by its run
    for row in rows(files.get("stop_times.txt", "")):
        times.setdefault(row["trip_id"], []).append(row)
    trips = []

    # Each run with its stops in order
    for row in rows(files.get("trips.txt", "")):
        stop_times = sorted(times.get(row["trip_id"], []), key=lambda stop: int(stop.get("stop_sequence") or 0))
        arrives = [seconds_of(stop["arrival_time"]) for stop in stop_times]
        departs = [seconds_of(stop["departure_time"]) for stop in stop_times]
        arrives = [at if at >= 0 else departs[i] for i, at in enumerate(arrives)]
        departs = [at if at >= 0 else arrives[i] for i, at in enumerate(departs)]

        # Only runs with stops and every time known
        if stop_times and min(departs) >= 0:
            trips.append({"id": row["trip_id"], "route": row["route_id"], "service": row["service_id"],
                          "headsign": row.get("trip_headsign", ""), "stops": [stop["stop_id"] for stop in stop_times],
                          "arrives": arrives, "departs": departs})
    services = {}
    day = "%Y%m%d"

    # Each service's weekly pattern
    for row in rows(files.get("calendar.txt", "")):
        services[row["service_id"]] = {
            "weekdays": [row[name] == "1" for name in ("monday", "tuesday", "wednesday", "thursday", "friday",
                                                      "saturday", "sunday")],
            "from": datetime.datetime.strptime(row["start_date"], day).date(),
            "to": datetime.datetime.strptime(row["end_date"], day).date(), "added": set(), "removed": set()}

    # Dates added (1) or taken away (2)
    for row in rows(files.get("calendar_dates.txt", "")):
        service = services.setdefault(row["service_id"], {"weekdays": [False] * 7, "from": datetime.date.min,
                                                          "to": datetime.date.min, "added": set(), "removed": set()})
        service["added" if row["exception_type"] == "1" else "removed"].add(
            datetime.datetime.strptime(row["date"], day).date())
    headways = {}

    # Runs that repeat every few minutes between two times
    for row in rows(files.get("frequencies.txt", "")):
        every = int(row.get("headway_secs") or 0)

        # Skip a headway of nothing
        if every > 0:
            headways.setdefault(row["trip_id"], []).append((seconds_of(row["start_time"]),
                                                            seconds_of(row["end_time"]), every))
    return {"stops": stops, "routes": routes, "trips": trips, "services": services, "headways": headways}

# Return True if a service runs on a date
def runs(service, date):
    # Dates added or taken away win over the weekly pattern
    if not service:
        return False
    elif date in service["added"]:
        return True
    elif date in service["removed"]:
        return False
    return service["from"] <= date <= service["to"] and service["weekdays"][date.weekday()]

# Download the timetable into data/ (keeping the old copy if the download fails), and read it again next time
def fetch_timetable():
    global table
    stamp = os.path.join(FOLDER, "fetched")
    data = download(TIMETABLE_URL)

    # Nothing downloaded, nothing to change
    if data:
        # A damaged download keeps the old copy
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = {os.path.basename(name): name for name in archive.namelist()}
                files = {name: archive.read(names[name]).decode("utf-8") for name in KEPT_FILES if name in names}

            # Only a complete timetable replaces the old one
            if "trips.txt" in files and "stop_times.txt" in files:
                os.makedirs(FOLDER, exist_ok=True)

                # Each file kept
                for name, text in files.items():
                    with open(os.path.join(FOLDER, name), "w", encoding="utf-8") as kept:
                        kept.write(text)
                with open(stamp, "w", encoding="utf-8") as kept:
                    kept.write(str(time.time()))
                table = None
        except (zipfile.BadZipFile, UnicodeDecodeError, OSError) as error:
            log.warning("Campus bus timetable unreadable: %s", error)

# The timetable: from memory, else data/'s copy; fetched first when there's none, and in the background when it's a
# week old (the old one is used meanwhile); None when it can't be had
def timetable():
    stamp = os.path.join(FOLDER, "fetched")
    have = os.path.exists(os.path.join(FOLDER, "trips.txt"))

    # Fetch it now when there's none, or in the background when it's old
    if not have:
        fetch_timetable()
    elif not os.path.exists(stamp) or time.time() - os.path.getmtime(stamp) > REFRESH_SECONDS:
        os.utime(stamp if os.path.exists(stamp) else os.path.join(FOLDER, "trips.txt"))  # one fetch at a time
        threading.Thread(target=fetch_timetable, daemon=True).start()
    return read_timetable()

# data/'s copy of the timetable, read once (None when there's none)
def read_timetable():
    global table

    # Read data/'s copy once
    if table is None and os.path.exists(os.path.join(FOLDER, "trips.txt")):
        files = {}

        # Each kept file there is
        for name in KEPT_FILES:
            path = os.path.join(FOLDER, name)

            # Skip files the feed didn't have
            if os.path.exists(path):
                with open(path, encoding="utf-8") as kept:
                    files[name] = kept.read()
        table = parse_timetable(files)
    return table

# The distance between two spots (latitude, longitude) in meters
def meters(first, second):
    radians = math.pi / 180
    a = (math.sin((second[0] - first[0]) * radians / 2) ** 2 + math.cos(first[0] * radians) *
         math.cos(second[0] * radians) * math.sin((second[1] - first[1]) * radians / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(a))

# About how many minutes it takes to walk between two spots
def walk_minutes(first, second):
    return math.ceil(meters(first, second) * DETOUR / WALK_METERS_PER_MINUTE)

# The stops within a 15-minute walk of a spot, with the walk in minutes
def stops_near(buses, spot):
    near = {stop_id: walk_minutes(spot, (stop["lat"], stop["lon"])) for stop_id, stop in buses["stops"].items()}
    return {stop_id: minutes for stop_id, minutes in near.items() if minutes <= MAX_WALK_MINUTES}

# The seconds a run's times move by, once for each time it leaves on a day: 0 for a run that leaves once, or one per
# headway for a run that repeats every few minutes
def offsets(buses, trip):
    first = trip["departs"][0]
    found = buses["headways"].get(trip["id"])
    return [moment - first for start, end, every in found for moment in range(start, end, every)] if found else [0]

# Every bus ride from near one spot to near another leaving its stop between two times (naive local datetimes): one
# per run, getting on and off where the whole trip, walks included, is shortest
def bus_rides(buses, start, end, earliest, latest):
    near_start, near_end = stops_near(buses, start), stops_near(buses, end)
    found = []

    # Nothing to ride when either end has no stop nearby
    if not near_start or not near_end:
        return found
    day = earliest.date() - datetime.timedelta(days=1)  # runs past midnight

    # Each service day the window touches
    while day <= latest.date():
        midnight = datetime.datetime.combine(day, datetime.time())

        # Each run that day passing a stop near the start
        for trip in buses["trips"]:
            route = buses["routes"].get(trip["route"])

            # Only runs that run that day and stop near the start
            if not route or not runs(buses["services"].get(trip["service"]), day) or not any(
                    stop in near_start for stop in trip["stops"]):
                continue

            # Each time the run leaves
            for offset in offsets(buses, trip):
                best = None

                # Each stop near the start, then each later stop near the end
                for i, board in enumerate(trip["stops"]):
                    departs = midnight + datetime.timedelta(seconds=trip["departs"][i] + offset)

                    # Only stops near the start, at times in the window
                    if board not in near_start or not earliest <= departs <= latest:
                        continue

                    # Each later stop near the end, keeping the shortest door to door
                    for j in range(i + 1, len(trip["stops"])):
                        alight = trip["stops"][j]

                        # Only stops near the end
                        if alight not in near_end:
                            continue
                        arrives = midnight + datetime.timedelta(seconds=trip["arrives"][j] + offset)
                        ride = {"trip": trip, "route": route, "board": buses["stops"][board],
                                "alight": buses["stops"][alight], "departs": departs, "arrives": arrives,
                                "walk_to": near_start[board], "walk_from": near_end[alight], "stop_count": j - i}
                        ride["leave"] = departs - datetime.timedelta(minutes=ride["walk_to"])
                        ride["there"] = arrives + datetime.timedelta(minutes=ride["walk_from"])

                        # Keep the shortest
                        if best is None or ride["there"] - ride["leave"] < best["there"] - best["leave"]:
                            best = ride

                # One ride per time the run leaves
                if best:
                    found.append(best)
        day += datetime.timedelta(days=1)
    return found

# The bus that lets you leave latest and still get there by a time, or None
def latest_bus(buses, start, end, arrive_by):
    rides = [ride for ride in bus_rides(buses, start, end, arrive_by - SEARCH, arrive_by) if ride["there"] <= arrive_by]
    return max(rides, key=lambda ride: ride["leave"], default=None)

# The bus that gets you there soonest leaving after a time, or None
def soonest_bus(buses, start, end, leave_after):
    rides = [ride for ride in bus_rides(buses, start, end, leave_after, leave_after + SEARCH)
             if ride["leave"] >= leave_after]
    return min(rides, key=lambda ride: ride["there"], default=None)

# A step of a journey, as journeys.py makes them, with where it starts and ends
def step(kind, title, under, starts, ends, line="", color="", start=None, end=None):
    return {"kind": kind, "title": title, "under": under, "line": line, "color": color, "starts": starts,
            "ends": ends, "from_spot": start, "to_spot": end}

# The steps for a bus ride in place of a walk: the walk to its stop, the ride ("LX bus to Livingston Student Center",
# scheduled until live times come in) and the walk from its stop to where the old walk ended
def ride_steps(ride, walk, first):
    board, alight = ride["board"], ride["alight"]
    board_spot, alight_spot = (board["lat"], board["lon"]), (alight["lat"], alight["lon"])
    minutes = round((ride["arrives"] - ride["departs"]).total_seconds() / 60)
    stops = f"{ride['stop_count']} stop{'' if ride['stop_count'] == 1 else 's'}"
    bus = step("bus", f"{ride['route']['short']} bus to {alight['name']}",
               f"{SCHEDULED} · {minutes} min · {stops} · from {board['name']}", ride["departs"], ride["arrives"],
               ride["route"]["short"], f"#{ride['route']['color']}" if ride["route"]["color"] else "", board_spot,
               alight_spot)
    bus.update({"bus_trip": ride["trip"]["id"], "board_stop": board["id"], "scheduled": ride["departs"]})
    steps = []

    # The walk to the stop, when it's more than a step away
    if ride["walk_to"] > 0:
        title = f"Leave · {ride['walk_to']} min walk" if first else f"{ride['walk_to']} min walk"
        steps.append(step("walk", title, f"to {board['name']}", ride["leave"], ride["departs"],
                          start=walk.get("from_spot"), end=board_spot))
    steps.append(bus)

    # The walk from the stop, when there is one
    if ride["walk_from"] > 0:
        steps.append(step("walk", f"{ride['walk_from']} min walk", walk["under"], ride["arrives"], ride["there"],
                          start=alight_spot, end=walk.get("to_spot")))
    return steps

# A journey's steps with one walk swapped for a campus bus, when a bus lets you leave later (a walk before any ride)
# or get there sooner (a walk after one) by at least 3 minutes; forced (by bus) takes the best bus even when it saves
# nothing. The steps as they were when there's no bus near both ends of any walk, or no timetable
def with_campus_buses(steps, forced=False):
    buses = timetable()
    best = None

    # No timetable, no buses
    if not buses:
        return steps

    # Each walk that knows where it starts and ends
    for index, walk in enumerate(steps):
        # Only walks with both ends known
        if walk["kind"] != "walk" or not walk.get("from_spot") or not walk.get("to_spot"):
            continue
        after_ride = any(earlier["kind"] in ("train", "bus", "subway") for earlier in steps[:index])

        # After a ride the bus should get you there sooner; before one, let you leave later
        if after_ride:
            ride = soonest_bus(buses, walk["from_spot"], walk["to_spot"], walk["starts"])
            gain = (walk["ends"] - ride["there"]) if ride else None
        else:
            ride = latest_bus(buses, walk["from_spot"], walk["to_spot"], walk["ends"])
            gain = (ride["leave"] - walk["starts"]) if ride else None

        # Keep the walk the bus helps most
        if ride and (best is None or gain > best[2]):
            best = (index, ride, gain)

    # Only a bus that saves enough, unless the bus was asked for
    if not best or (not forced and best[2] < datetime.timedelta(minutes=MIN_GAIN_MINUTES)):
        return steps
    index, ride, _ = best
    swapped = steps[:index] + ride_steps(ride, steps[index], index == 0) + steps[index + 1:]
    arrive = [moving for moving in swapped if moving["kind"] != "arrive"][-1]["ends"]

    # The arriving step moves with it
    for moving in swapped:
        # Only the arriving step
        if moving["kind"] == "arrive":
            moving["starts"] = moving["ends"] = arrive
    return swapped

# Read a protobuf varint at a position: it and where the next field starts
def varint(data, position):
    result = shift = 0

    # Seven bits at a time until the top bit is clear
    while True:
        byte = data[position]
        position += 1
        result |= (byte & 0x7F) << shift
        shift += 7

        # The last byte of the number
        if byte < 0x80:
            return result, position

# A protobuf message's fields as (field number, value): numbers for varints, bytes for nested messages and text
def proto_fields(data):
    fields, position = [], 0

    # Each field in turn, by its wire type
    while position < len(data):
        key, position = varint(data, position)
        number, kind = key >> 3, key & 7

        # Numbers, nested bytes, or fixed widths skipped
        if kind == 0:
            value, position = varint(data, position)
            fields.append((number, value))
        elif kind == 2:
            length, position = varint(data, position)
            fields.append((number, data[position:position + length]))
            position += length
        elif kind in (1, 5):
            position += 8 if kind == 1 else 4
        else:
            break
    return fields

# The values of one field number
def field(data, number):
    return [value for key, value in proto_fields(data) if key == number]

# Read a GTFS-realtime trip updates feed into predicted times (naive local datetimes) at each stop of each run: trip
# id → stop id → times; departures where given, else arrivals
def parse_predictions(feed):
    found = {}

    # Each entity with a trip update
    for entity in field(feed, 2):
        update = (field(entity, 3) or [None])[0]
        trip = field((field(update, 1) or [b""])[0], 1) if update else []

        # Only updates that name their run
        if not trip:
            continue

        # Each stop's predicted time
        for stop_update in field(update, 2):
            stop = field(stop_update, 4)
            event = (field(stop_update, 3) or field(stop_update, 2) or [b""])[0]
            when = field(event, 2)

            # Only stops with a time
            if stop and when:
                found.setdefault(trip[0].decode(), {}).setdefault(stop[0].decode(), []).append(
                    datetime.datetime.fromtimestamp(when[0]))
    return found

# The live predicted times, fetched when the last ones are over 30 seconds old; empty when the feed can't be read
def predictions():
    global live

    # Use the last ones while they're fresh
    if time.time() - live[0] < LIVE_SECONDS:
        return live[1]
    data = download(LIVE_URL)

    # An unreadable feed means no live times
    try:
        live = (time.time(), parse_predictions(data) if data else {})
    except (IndexError, ValueError, OverflowError) as error:
        log.warning("Campus bus live times unreadable: %s", error)
        live = (time.time(), {})
    return live[1]

# How late a bus is from its predicted and scheduled times, in whole minutes (negative when early)
def minutes_late(predicted, scheduled):
    return round((predicted - scheduled).total_seconds() / 60)

# The predicted time for a run at a stop nearest its scheduled time (within 30 minutes), or None
def predicted(found, trip_id, stop_id, scheduled):
    times = [at for at in found.get(trip_id, {}).get(stop_id, []) if abs(at - scheduled) <= datetime.timedelta(
        minutes=30)]
    return min(times, key=lambda at: abs(at - scheduled), default=None)

# A journey's campus buses with their live state ("Live · 2 min late" in place of "Scheduled")
def with_live(steps):
    found = None

    # Each campus bus
    for ride in steps:
        # Only campus buses
        if not ride.get("bus_trip"):
            continue
        found = predictions() if found is None else found
        at = predicted(found, ride["bus_trip"], ride["board_stop"], ride["scheduled"])

        # A bus with a prediction says how late it is
        if at:
            late = minutes_late(at, ride["scheduled"])
            state = f"{late} min late" if late > 0 else f"{-late} min early" if late < 0 else "on time"
            ride["under"] = ride["under"].replace(SCHEDULED, f"Live · {state}", 1)
    return steps

# The stop whose name best matches what was said ("College Ave" → College Avenue Student Center): most words matched
# (each said word the start of a word in the name), student centers first, then the shortest name; None for no match
def find_stop(buses, words):
    plain = "".join(c if c.isalnum() else " " for c in words.lower()).replace("new brunswick", "nb")
    said = [word for word in plain.split() if word not in ("the", "stop", "at", "from", "to")]
    best, best_score = None, None

    # Each stop, scored against the words
    for stop in buses["stops"].values():
        name = stop["name"].lower().replace("(", " ").replace(")", " ").split()
        matched = sum(1 for word in said if any(part.startswith(word) for part in name))
        score = (matched, "student center" in stop["name"].lower(), -len(stop["name"]))

        # Keep the best match
        if matched and (best_score is None or score > best_score):
            best, best_score = stop, score
    return best

# The next buses leaving a stop (what was said), on a route when one is named and toward a stop when one is given,
# with their live state: route, where it's headed, scheduled and expected times, minutes late, and whether that's live
def next_buses(from_words, route_words="", to_words="", now=None, count=3):
    now = now or datetime.datetime.now()
    buses = timetable()

    # Nothing without a timetable or a stop
    if not buses:
        raise ValueError("the Rutgers bus timetable isn't available right now")
    stop = find_stop(buses, from_words)
    end = find_stop(buses, to_words) if to_words else None

    # A stop that can't be found says so
    if not stop:
        raise ValueError(f"no Rutgers bus stop matches {from_words}")
    wanted = route_words.strip().lower()
    found = predictions()
    leaving = []

    # Each run on the route through the stop (today, and runs from yesterday still going)
    for day in (now.date() - datetime.timedelta(days=1), now.date()):
        midnight = datetime.datetime.combine(day, datetime.time())

        # Each run that runs that day
        for trip in buses["trips"]:
            route = buses["routes"].get(trip["route"]) or {}

            # Only the route asked for (any when none), on a run that runs that day
            if (wanted and route.get("short", "").lower() != wanted) or not runs(
                    buses["services"].get(trip["service"]), day):
                continue

            # Each time the run leaves
            for offset in offsets(buses, trip):
                # Each time it calls at a stop
                for i, stop_id in enumerate(trip["stops"]):
                    scheduled = midnight + datetime.timedelta(seconds=trip["departs"][i] + offset)

                    # Only this stop, toward the end stop when given, soon
                    if stop_id != stop["id"] or (end and end["id"] not in trip["stops"][i + 1:]) or not (
                            now - datetime.timedelta(minutes=2) <= scheduled <= now + datetime.timedelta(hours=3)):
                        continue
                    at = predicted(found, trip["id"], stop_id, scheduled)
                    expected = at or scheduled

                    # Only buses that haven't left
                    if expected >= now - datetime.timedelta(minutes=1):
                        leaving.append({"route": route.get("short", ""), "toward": trip["headsign"],
                                        "scheduled": scheduled, "expected": expected, "live": at is not None,
                                        "minutes_late": minutes_late(at, scheduled) if at else 0})
    leaving.sort(key=lambda bus: bus["expected"])
    return {"stop": stop["name"], "to": end["name"] if end else "", "buses": leaving[:count]}
