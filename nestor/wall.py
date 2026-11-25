# What the wall screen shows, gathered in one place for its page: the weather and sun times, the next event and the
# rest of today from Datebook, the list counts, the train board for the saved trip, what's playing and the men's foil
# schedule. Slow sources (the weather, NJ Transit) are kept for a few minutes, so the page can ask often.
import datetime
import logging
import threading
from nestor import datebook
from nestor import journeys
from nestor import reminders
from nestor import spotify
from nestor import trains
from nestor import weather
WEATHER_MINUTES = 10  # How long a weather answer is used before asking Open-Meteo again
TRAIN_MINUTES = 2  # How long a departure board is used before asking NJ Transit again
JUST_LEFT_MINUTES = 30  # The train that just left shows this long
TRAIN_ROWS = 3  # Trains still to come on the board (after the one that just left)
STALE_MINUTES = 60  # With the phone away, Datebook's data counts as old after this long
# The scene picture for each Open-Meteo weather code (rain is everything wet that isn't snow or a storm)
SCENES = {0: "clear", 1: "clear", 2: "partly", 3: "overcast", 45: "fog", 48: "fog", 71: "snow", 73: "snow", 75: "snow",
          77: "snow", 85: "snow", 86: "snow", 95: "storm", 96: "storm", 99: "storm"}
LIST_WORDS = (("bills", "bill", "bills"), ("assignments", "assignment", "assignments"),
              ("packages", "package", "packages"), ("trips", "trip", "trips"))
CHIP_TEMP_PATH = "/sys/class/thermal/thermal_zone0/temp"  # The board's chip temperature (Linux), in thousandths
BOARD_ROWS = 6  # Trains each way on the Trains screen
EARLIER_TRAINS = 2  # Earlier trains named under your train on the trip screen
LIST_ROWS = 3  # Items each Lists column shows before it's opened
# A men's foil event's stages, and words in Datebook's stage line that say which one it's at (checked in this order)
FOIL_STAGES = ("Pools", "Table of 64", "Table of 32", "Table of 16", "Quarterfinals", "Semifinals", "Final")
STAGE_WORDS = (("pool", 0), ("64", 1), ("32", 2), ("16", 3), ("quarter", 4), ("of 8", 4), ("semi", 5), ("of 4", 5),
               ("final", 6))
log = logging.getLogger(__name__)

# The scene picture for a weather code ("wet" for rain and drizzle)
def scene_for(code):
    return SCENES.get(code, "wet" if code is not None else "partly")

# A time of day as the wall writes it: ("9:05", "AM")
def clock_parts(moment):
    return f"{moment.hour % 12 or 12}:{moment.minute:02d}", "AM" if moment.hour < 12 else "PM"

# A time of day as one piece of text, "9:05 AM"
def clock_text(moment):
    return " ".join(clock_parts(moment))

# How long until a moment, as the Next card says it: "in 1 h 18 min", "in 25 min", "in 2 h", "now"
def countdown(now, moment):
    minutes = max(0, round((moment - now).total_seconds() / 60))
    hours, minutes = divmod(minutes, 60)

    # Hours and minutes, just one of them, or nothing left
    if hours and minutes:
        return f"in {hours} h {minutes} min"
    elif hours:
        return f"in {hours} h"
    elif minutes:
        return f"in {minutes} min"
    return "now"

# Read a Datebook time ("2026-11-20T19:00" or a date alone); None when it's missing or unreadable
def read_moment(text):
    # Missing or odd times are left out
    try:
        return datetime.datetime.fromisoformat(text) if text else None
    except ValueError:
        return None

# A snapshot item with its title as the wall shows it, and its class's nickname in "class" (Canvas items)
def titled(item, class_names, lookup):
    title, class_name = datebook.split_class(item.get("title", ""), class_names, lookup)
    return dict(item, title=title, **{"class": class_name})

# Datebook's snapshot with titles as John says them: Canvas assignments without their course codes (the class's
# nickname kept in "class"), and events titled with a class's registrar name shown by its nickname
def readable(snapshot, class_names):
    lookup = datebook.class_lookup(snapshot, class_names)
    copy = dict(snapshot)
    copy["events"] = [titled(item, class_names, lookup) for item in snapshot.get("events") or []
                      if isinstance(item, dict)]
    lists = dict(snapshot.get("lists") or {})

    # Bills and assignments tidied the same way
    for part in ("bills", "assignments"):
        lists[part] = [titled(item, class_names, lookup) for item in lists.get(part) or [] if isinstance(item, dict)]
    copy["lists"] = lists
    return copy

# The next timed event today that hasn't started (None when nothing else has a time today)
def next_event(events, now):
    upcoming = [event for event in events if not event.get("all_day") and read_moment(event.get("start"))
                and read_moment(event["start"]) > now and read_moment(event["start"]).date() == now.date()]
    return min(upcoming, key=lambda event: event["start"]) if upcoming else None

# The status lines under the Next card: a flight's status from Datebook, then the event's train from the live board
# (a flight going by train shows both; empty when there's neither)
def travel_statuses(event, board_rows):
    flight = event.get("flight") or {}
    lines = []
    # A flight carries its own status line
    if flight.get("text"):
        lines.append({"kind": "flight", "text": flight["text"], "late": bool(flight.get("late"))})
    train = train_status(event, board_rows)
    # The train goes under it
    if train:
        lines.append(train)
    return lines

# The event's train line, looked up on the live board by its departure time (None without a train)
def train_status(event, board_rows):
    train = event.get("train") or {}

    # No train picked for it
    if not train.get("departs"):
        return None
    hour, minute = (int(part) for part in train["departs"].split(":"))
    name = f"{hour % 12 or 12}:{minute:02d} train"
    row = next((row for row in board_rows if row["clock"] == train["departs"]), None)

    # Not on the board (yet), cancelled, late, or on time with or without a track
    if not row:
        return {"kind": "train", "text": name, "late": False}
    elif row["state"] == "cancelled":
        later = next((other for other in board_rows if other["clock"] > row["clock"] and other["state"] != "cancelled"),
                     None)
        text = f"{name} cancelled" + (f" · next {later['time']}" if later else "")
        return {"kind": "train", "text": text, "late": True}
    elif row["state"] == "late":
        return {"kind": "train", "text": f"{name} · {row['status'].lower()}", "late": True}
    elif row["track"] == "Tr —":
        return {"kind": "train", "text": f"{name} · on time · track not posted yet", "late": False}
    return {"kind": "train", "text": f"{name} · {row['track']} · on time", "late": False}

# The Next card for an event: big time, countdown, place, leave-by (orange once it's time to go), what to bring and
# the flight and train lines
def next_card(event, now, board_rows):
    start = read_moment(event["start"])
    leave_by = read_moment(event.get("leave_by"))
    travel = event.get("travel") or ""
    urgent = bool(leave_by and now >= leave_by)
    time, ampm = clock_parts(start)
    leave = ""

    # Leave now once it's time, otherwise when to leave
    if urgent:
        leave = "Leave now" + (f" · {travel}" if travel else "")
    elif leave_by:
        leave = f"Leave by {clock_parts(leave_by)[0]}" + (f" · {travel}" if travel else "")
    return {"time": time, "ampm": ampm, "soon": "time to go" if urgent else countdown(now, start), "urgent": urgent,
            "title": event.get("title") or "", "place": event.get("place") or "", "leave": leave,
            "bring": event.get("bring") or "", "statuses": travel_statuses(event, board_rows)}

# Later today: what's left of today after the next event, in time order (timed events, all-day events, reminders, and
# bills and assignments due today)
def later_today(snapshot, now, shown_event, nestor_reminders):
    today = now.date()
    rows = []

    # Timed events still to come today (the one on the Next card is left out) and today's all-day events
    for event in snapshot.get("events") or []:
        start = read_moment(event.get("start"))

        # Only today's, and only what hasn't started
        if not start or start.date() != today or event is shown_event:
            continue
        elif event.get("all_day"):
            rows.append(("", "Today", event.get("title") or "", "", ""))
        elif start > now:
            rows.append((start.strftime("%H:%M"), clock_text(start), event.get("title") or "", event.get("place") or "",
                         ""))

    # Datebook's reminders and Nestor's own, for later today
    for reminder in snapshot.get("reminders") or []:
        at = read_moment(reminder.get("at"))

        # Only today's that haven't come yet
        if at and at.date() == today and at > now:
            rows.append((at.strftime("%H:%M"), clock_text(at), reminder.get("text") or "", "", "Reminder"))

    # Nestor's reminders are "18:00" times for today
    for reminder in nestor_reminders:
        at = datetime.datetime.combine(today, datetime.time.fromisoformat(reminder["time"]))

        # Only the ones still to come
        if at > now:
            rows.append((reminder["time"], clock_text(at), reminder["text"], "", "Reminder"))
    lists = snapshot.get("lists") or {}

    # Bills and assignments due today
    for part in ("bills", "assignments"):
        # Each one due today
        for item in lists.get(part) or []:
            due = read_moment(item.get("due"))

            # Only those due today, and only until their time if they have one
            if due and due.date() == today and (len(item.get("due", "")) <= 10 or due > now):
                rows.append(("", "Today", item.get("title") or "", "", "Due"))
    rows.sort(key=lambda row: row[0])
    return [{"time": time, "title": title, "place": place, "tag": tag} for key, time, title, place, tag in rows]

# The list counts for Later today's header: "2 bills · 1 assignment · 1 package · 1 trip" ("" when there are none)
def list_counts(lists):
    parts = []

    # Each kind of list, when it has something
    for part, one, many in LIST_WORDS:
        count = len((lists or {}).get(part) or [])

        # Only lists with items, in the singular or plural
        if count:
            parts.append(f"{count} {one if count == 1 else many}")
    return " · ".join(parts)

# "Updated 3 h ago" when the phone is away and Datebook's data is over an hour old (None otherwise)
def updated_line(state, now):
    updated = read_moment(state.get("updated"))

    # Fresh data, or the phone is home: nothing to say
    if not updated or state.get("phone_home") or now - updated < datetime.timedelta(minutes=STALE_MINUTES):
        return None
    hours = int((now - updated).total_seconds() // 3600)
    return f"Updated {hours} h ago" if hours < 48 else f"Updated {hours // 24} days ago"

# The board's rows: the train that just left (faded), then the next trains to the destination, late in orange and
# cancelled in red
def train_rows(board, to_code, left, now, count=TRAIN_ROWS):
    rows = []
    coming = [train for train in trains.trains_to(board, to_code, count=count + 1)
              if train["departs"] and train["departs"] > now - datetime.timedelta(minutes=1)][:count]

    # The one that just left comes first, faded
    if left and left["departs"] and now - left["departs"] < datetime.timedelta(minutes=JUST_LEFT_MINUTES):
        rows.append(board_row(left, "gone"))

    # Then each train still to come
    for train in coming:
        cancelled = "cancel" in train["status"].lower()
        rows.append(board_row(train, "cancelled" if cancelled else "late" if train["minutes_late"] > 0 else ""))
    return rows

# One row of the train board: departure time, track and status
def board_row(train, state):
    late = f"{train['minutes_late']} min late"
    status = {"gone": "Left", "cancelled": "Cancelled", "late": late}.get(state, "On time")
    track = "" if state == "cancelled" else f"Tr {train['track']}" if train["track"] else "Tr —"
    return {"time": clock_parts(train["departs"])[0], "clock": train["departs"].strftime("%H:%M"), "track": track,
            "status": status, "state": state}

# Is a men's foil event live now: inside the stream times Datebook sent for its day, else Datebook's own flag (from its
# last snapshot, which can be up to 10 minutes old)
def foil_live(event, now):
    live_from = read_moment(event.get("live_from"))
    live_until = read_moment(event.get("live_until"))
    return live_from <= now < live_until if live_from and live_until else bool(event.get("live"))

# The week's men's foil events from Datebook's fencing list (it follows only men's foil; each event comes on the day it
# shows, today while it's on), with LIVE for one on now
def foil_rows(fencing, now):
    rows = []
    week_end = now.date() + datetime.timedelta(days=7)

    # Each tournament event Datebook sent
    for event in fencing or []:
        start = read_moment(event.get("start"))
        end = read_moment(event.get("end")) or start

        # Only this week's, not over yet
        if not start or start.date() > week_end or end.date() < now.date():
            continue
        live = foil_live(event, now)
        timed = len(event.get("start", "")) > 10
        rows.append({"day": "LIVE" if live else start.strftime("%a"), "live": live, "name": event.get("name") or "",
                     "where": event.get("stage") if live and event.get("stage") else event.get("where") or "",
                     "time": "" if live or not timed else clock_text(start), "sort": event.get("start") or ""})
    rows.sort(key=lambda row: (not row["live"], row["sort"]))
    return [{key: value for key, value in row.items() if key != "sort"} for row in rows]

# A "16:52" time from Datebook as the wall writes it, "4:52 PM" ("" when it's missing)
def clock_of(hhmm):
    # Missing or odd times are left out
    try:
        hour, minute = (int(part) for part in hhmm.split(":"))
    except (AttributeError, ValueError):
        return ""
    return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"

# One step of a trip: its time, what happens, a line under it, its kind (walk, train, stop, goal or plane), whether
# it's late, whether it's what you aim for, and the earlier trains under a train
def trip_step(time, title, under, kind, late=False, warn=False, earlier=""):
    return {"time": time, "title": title, "under": under, "kind": kind, "late": bool(late), "warn": warn,
            "earlier": earlier}

# The board's train that leaves at a "16:52" time (None when it isn't on the board)
def board_train(board, hhmm):
    return next((train for train in board if train["departs"] and train["departs"].strftime("%H:%M") == hhmm), None)

# The trains before yours that also stop where yours takes you, still to come: "4:22 PM · 4:32 PM" ("" for none)
def earlier_trains(board, mine, to_name, now):
    wanted = (to_name or "").lower()
    code = next((stop["code"] for stop in mine["stops"] if wanted and (wanted in stop["name"].lower() or
                                                                        stop["name"].lower() in wanted)), None)
    # Without the stop there's nothing to compare
    if not code:
        return ""
    before = [train for train in board if train["departs"] and now < train["departs"] < mine["departs"] and
              "cancel" not in train["status"].lower() and trains.arrival_at(train, code)]
    return " · ".join(clock_text(train["departs"]) for train in before[-EARLIER_TRAINS:])

# The trip screen for the next event: its card (big time, countdown, flight status, terminal and gate, leave line,
# what to bring) and the steps of the trip (leave, the train with its track and earlier trains, the station, being at
# the airport early, then the flight or the event); None without an event
def trip_screen(event, board, now):
    # Nothing next, nothing to show
    if not event:
        return None
    start = read_moment(event["start"])
    leave_by = read_moment(event.get("leave_by"))
    urgent = bool(leave_by and now >= leave_by)
    flight = event.get("flight") or {}
    train = event.get("train") or {}
    travel = event.get("travel") or ""
    early = int(event.get("early") or 0)
    time, ampm = clock_parts(start)
    steps = []

    # Without a picked train, the journey Datebook kept for the plan gives every step (buses and transfers too)
    if event.get("journey") and not train.get("departs"):
        steps = [dict(trip_step(clock_text(read_moment(step.get("starts")) or start), step.get("title") or "",
                                step.get("under") or "", "goal" if step.get("kind") == "arrive" else
                                step.get("kind") or "walk", warn=step.get("kind") == "arrive"),
                      line=step.get("line") or "", color=step.get("color") or "") for step in event["journey"]]

    # Leaving: now, or at the leave time
    if leave_by and not steps:
        steps.append(trip_step(clock_text(leave_by), "Leave now" if urgent else "Leave", travel, "walk"))

    # The train, live from the board when it's on it, with the earlier ones under it, then where it gets you
    if train.get("departs"):
        mine = board_train(board, train["departs"])
        late = mine["minutes_late"] if mine else int(train.get("late") or 0)
        track = (mine["track"] if mine else train.get("track")) or "not posted yet"
        cancelled = "cancel" in ((mine["status"] if mine else train.get("status")) or "").lower()
        state = "Cancelled" if cancelled else f"{late} min late" if late > 0 else "On time"
        earlier = earlier_trains(board, mine, train.get("to"), now) if mine else ""
        steps.append(trip_step(clock_of(train["departs"]), f"NJT {train.get('id') or ''} · Track {track}".strip(),
                               state, "train", late=late > 0 or cancelled,
                               earlier=f"Earlier trains: {earlier}" if earlier else ""))

        # The station it takes you to
        if train.get("arrives"):
            steps.append(trip_step(clock_of(train["arrives"]), train.get("to") or "", "AirTrain to the terminal"
                                   if flight.get("text") else "", "stop"))

    # A flight: at the airport early, then it departs; anything else: it starts (unless the kept journey arrives)
    if flight.get("text"):
        departs = read_moment(flight.get("departs")) or start
        lands = read_moment(flight.get("lands"))
        city = f" in {flight['to_city']}" if flight.get("to_city") else ""

        # Being at the airport early, when there's a time for it
        if early:
            steps.append(trip_step(clock_text(start - datetime.timedelta(minutes=early)), "At the airport",
                                   f"{early} min before departure", "goal", warn=True))
        steps.append(trip_step(clock_text(departs), f"{flight.get('number') or 'Flight'} departs",
                               f"Lands {clock_text(lands)}{city}" if lands else "", "plane", late=flight.get("late")))
    elif not (event.get("journey") and not train.get("departs")):
        steps.append(trip_step(clock_text(start), event.get("title") or "", event.get("place") or "", "goal"))
    gate = " · ".join(part for part in (f"Terminal {flight['terminal']}" if flight.get("terminal") else "",
                                        f"gate {flight['gate']}" if flight.get("gate") else "") if part)
    leave = (f"Leave now · {travel}" if urgent else f"Leave by {clock_text(leave_by)} · {travel}") if leave_by else ""
    return {"title": event.get("title") or "", "time": time, "ampm": ampm, "urgent": urgent,
            "soon": "time to go" if urgent else countdown(now, start), "status": flight.get("text") or "",
            "status_late": bool(flight.get("late")), "gate": gate, "leave": leave.rstrip(" ·"),
            "bring": event.get("bring") or "", "steps": steps}

# How far off a day is, as the lists say it: "Overdue", "Today", "Tomorrow" or "in 3 days"
def days_off(day, today):
    gap = (day - today).days

    # Past, today, tomorrow or later
    if gap < 0:
        return "Overdue"
    elif gap == 0:
        return "Today"
    elif gap == 1:
        return "Tomorrow"
    return f"in {gap} days"

# A day as the lists write it, "Fri, Nov 27"
def day_text(day):
    return f"{day.strftime('%a, %b')} {day.day}"

# One row of a list: its title, a line under it, a value on the right (amount or time), how far off it is, and
# whether it needs you soon (orange)
def list_row(title, under, value, day, today):
    soon = days_off(day, today) if day else ""
    return {"title": title, "under": under, "value": value, "when": soon,
            "warn": soon in ("Overdue", "Today", "Tomorrow")}

# The Lists screen: four columns (bills, assignments, trips, packages), each soonest first, from Datebook's lists
def lists_screen(lists, now):
    lists = lists or {}
    today = now.date()
    columns = []
    kinds = (("bills", "Bills"), ("assignments", "Assignments"), ("trips", "Trips"), ("packages", "Packages"))

    # Each kind of list as a column
    for kind, name in kinds:
        rows = []

        # Each item of the list, with the line and value that suit its kind
        for item in lists.get(kind) or []:
            due = read_moment(item.get("due") or item.get("start") or item.get("expected"))
            day = due.date() if due else None
            timed = len(item.get("due") or "") > 10

            # Bills, assignments, trips and packages each read their own way
            if kind == "bills":
                under = (f"Was due {day_text(day)}" if day < today else f"Due {day_text(day)}") if day else ""
                rows.append((due, list_row(item.get("title") or "", under, item.get("amount") or "", day, today)))
            elif kind == "assignments":
                value = f"{due.strftime('%a')} {clock_text(due)}" if timed else (day_text(day) if day else "")
                rows.append((due, list_row(item.get("title") or "", item.get("class") or "", value, day, today)))
            elif kind == "trips":
                end = read_moment(item.get("end"))
                dates = f"{day_text(day)} – {day_text(end.date())}" if day and end and end.date() != day else \
                    (day_text(day) if day else "")
                plans = " · ".join(plan.get("title") or "" for plan in item.get("plans") or [])
                rows.append((due, list_row(item.get("title") or "", dates, plans, day, today)))
            else:
                carrier = item.get("carrier") or ""
                carrier = carrier if len(carrier) <= 4 else carrier.title()  # UPS stays, AMAZON reads Amazon
                rows.append((due, list_row(item.get("title") or "", carrier, day_text(day) if day else "", day,
                                           today)))
        rows.sort(key=lambda pair: pair[0] or datetime.datetime.max)
        items = [row for due, row in rows]
        columns.append({"key": kind, "name": name, "count": len(items), "rows": items, "shown": items[:LIST_ROWS],
                        "more": len(items) - LIST_ROWS if len(items) > LIST_ROWS else 0})
    return {"columns": columns}

# One train on the Trains screen: time, track and state (board_row), where it ends and when, whether it's a train
# picked for one of your plans, and its stops for tapping
def screen_train(train, end_code, picked):
    state = "cancelled" if "cancel" in train["status"].lower() else "late" if train["minutes_late"] > 0 else ""
    row = board_row(train, state)
    stops = [stop for stop in train["stops"] if stop["time"]]
    last = next((stop for stop in stops if stop["code"] == end_code), stops[-1] if stops else None)
    arrives = f"{last['name'].replace(' Station', '')} {clock_parts(last['time'])[0]}" if last else ""
    return dict(row, id=train["id"], arrives=arrives, mine=row["clock"] in picked,
                stops=[{"name": stop["name"].replace(" Station", ""), "time": clock_text(stop["time"])}
                       for stop in stops])

# The Trains screen: the trip's first station both ways, trains toward the trip's end on the left and the other way
# on the right (named by where most of them go), with the trains picked for your plans lit
def trains_screen(board, trip, trip_names, picked, now):
    coming = [train for train in board if train["departs"] and train["departs"] > now - datetime.timedelta(minutes=1)]
    toward = [train for train in coming if trains.arrival_at(train, trip[1])][:BOARD_ROWS]
    other = [train for train in coming if not trains.arrival_at(train, trip[1])][:BOARD_ROWS]
    ends = [train["destination"] for train in other if train["destination"]]
    other_name = max(set(ends), key=ends.count) if ends else "the other way"
    to_name = (trip_names.get("to_name") or trip[1]).replace(" Penn Station", "").replace(" Station", "")
    return {"station": (trip_names.get("from_name") or trip[0]).replace(" Station", ""),
            "ways": [{"name": f"Toward {to_name}",
                      "trains": [screen_train(train, trip[1], picked) for train in toward]},
                     {"name": f"Toward {other_name}", "trains": [screen_train(train, "", picked) for train in other]}]}

# Where a men's foil event is in its day, as the standard stages with the current one lit (empty without a stage)
def foil_stages(stage):
    words = (stage or "").lower()
    current = next((index for word, index in STAGE_WORDS if word in words), None)

    # A stage line that names none of them gets no bar
    if current is None:
        return []
    return [{"name": name, "state": "done" if index < current else "now" if index == current else "next"}
            for index, name in enumerate(FOIL_STAGES)]

# Keeps the wall's slow sources (weather and trains) and puts together everything the screen shows
class Wall:
    # Keep the settings and the NJ Transit account (None without one)
    def __init__(self, settings, rail):
        self.settings = settings
        self.rail = rail
        self.lock = threading.Lock()
        self.weather = None
        self.hours = []
        self.weather_at = None
        self.board = []
        self.board_at = None
        self.board_trip = None
        self.left = None

    # Today's weather, asked for again every few minutes (the last answer is kept if Open-Meteo doesn't answer)
    def current_weather(self, now):
        location = str(self.settings.get("home_location") or "").strip()

        # Without a home location there's no weather; otherwise use the kept answer while it's fresh
        if not location:
            return None
        elif self.weather_at and now - self.weather_at < datetime.timedelta(minutes=WEATHER_MINUTES):
            return self.weather

        # A failed check keeps the last weather
        try:
            unit = self.settings.get("temperature_unit", "fahrenheit")
            self.weather = weather.forecast(location, unit)
            self.hours = weather.hourly(location, unit)
        except Exception as error:
            log.warning("The wall's weather didn't update: %s", error)
        self.weather_at = now
        return self.weather

    # The live board for the trip's first station, asked for again every few minutes; notices the train that left
    def current_board(self, trip, now):
        # Without an account or a trip there's no board
        if not self.rail or not trip[0] or not trip[1]:
            return []
        elif trip == self.board_trip and self.board_at and now - self.board_at < datetime.timedelta(
                minutes=TRAIN_MINUTES):
            return self.board

        # A failed check keeps the last board
        try:
            board = self.rail.departures(trip[0])
        except Exception as error:
            log.warning("The wall's trains didn't update: %s", error)
            self.board_at = now
            return self.board
        still_there = {train["id"] for train in board}
        gone = [train for train in trains.trains_to(self.board, trip[1], count=10)
                if train["id"] not in still_there and train["departs"] and train["departs"] <= now]

        # A train to the destination that dropped off the board has just left (a new trip starts afresh)
        if trip != self.board_trip:
            self.left = None
        elif gone:
            self.left = max(gone, key=lambda train: train["departs"])
        self.board, self.board_at, self.board_trip = board, now, trip
        return board

    # Everything the wall screen shows right now, as JSON-ready data
    def state(self, now=None):
        now = now or datetime.datetime.now()

        # One page asking at a time, so slow sources are only fetched once
        with self.lock:
            forecast = self.current_weather(now)
            snapshot = readable(datebook.read_state(now), self.settings.get("class_names"))
            trip_names = snapshot.get("trip") or {}
            trip = (trip_names.get("from") or self.settings.get("train_from", ""),
                    trip_names.get("to") or self.settings.get("train_to", ""))
            board = self.current_board(trip, now)
            left = self.left
            hours = self.hours
        rows = train_rows(board, trip[1], left, now) if trip[1] else []
        event = next_event(snapshot.get("events") or [], now)
        picked = {(item.get("train") or {}).get("departs") for item in snapshot.get("events") or []} - {None}
        music = spotify.music.now if spotify.music else None
        nestor_reminders = reminders.todays_reminders(now.date())
        return {
            "now": now.isoformat(timespec="seconds"),
            "weather": forecast and {"temp": forecast["now"], "unit": forecast["unit"],
                                     "words": forecast["conditions"].capitalize(),
                                     "scene": scene_for(forecast.get("code")), "rain_from": wet_later(forecast),
                                     "sunrise": forecast["sunrise"], "sunset": forecast["sunset"]},
            "datebook": snapshot["connected"],
            "next": next_card(event, now, rows) if event else None,
            "later": later_today(snapshot, now, event, nestor_reminders),
            "counts": list_counts(snapshot.get("lists")),
            "updated": updated_line(snapshot, now),
            "trains": {"title": f"{trip_names.get('from_name') or trip[0]} → {trip_names.get('to_name') or trip[1]}",
                       "rows": rows} if trip[0] and trip[1] and self.rail else None,
            "music": music if music and music.get("playing") else None,
            "foil": foil_rows(snapshot.get("fencing"), now),
            "big": {"week": week_screen(snapshot, now, nestor_reminders),
                    "weather": weather_screen(hours, forecast, now),
                    "fencing": foil_screen(snapshot.get("fencing"), now),
                    "trip": trip_screen(event, board, now),
                    "lists": lists_screen(snapshot.get("lists"), now),
                    "trains": trains_screen(board, trip, trip_names, picked, now) if trip[0] and trip[1] and self.rail
                    else None,
                    "journey": journeys.wall_screen(now)},
            "chip_temp": chip_temperature(),
        }

# "Rain from 4 PM" for the weather line, only while it's dry now and rain is likely later today (None otherwise)
def wet_later(forecast):
    dry_now = scene_for(forecast.get("code")) in ("clear", "partly", "overcast")

    # Rain on the way while it's still dry
    if dry_now and forecast.get("rain_from"):
        hour = int(forecast["rain_from"][:2])
        return f"Rain from {hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"
    return None

# The parts of the day for the weather screen: name, first hour, the hour after the last
DAY_PARTS = (("Morning", 6, 12), ("Afternoon", 12, 17), ("Evening", 17, 21), ("Night", 21, 30))
WEATHER_HOURS = 12  # The weather screen covers this many hours
WET = 50  # A rain chance from this percent counts as rain coming
SNOW_CODES = {71, 73, 75, 77, 85, 86}
STORM_CODES = {95, 96, 99}

# An hour as the wall says it: "4 PM", "noon", "midnight"
def hour_text(hour):
    hour %= 24

    # Noon and midnight have names; other hours a number and AM or PM
    if hour == 12:
        return "noon"
    elif hour == 0:
        return "midnight"
    return f"{hour % 12} {'AM' if hour < 12 else 'PM'}"

# An hour's place in the day's parts, with the small hours after midnight counted as part of the night (24 to 29)
def night_hour(hour):
    clock = int(hour["time"][11:13])
    return clock if clock >= 6 else clock + 24

# What falls in a list of hours: "Snow", "Storms" or "Rain" (by the codes of the wet ones)
def wet_kind(hours):
    codes = {hour["code"] for hour in hours if hour["rain"] >= WET}

    # Snow wins, then storms, then plain rain
    if codes & SNOW_CODES:
        return "Snow"
    elif codes & STORM_CODES:
        return "Storms"
    return "Rain"

# The weather screen in words: a big line about rain (or none), a line under it, and the parts of the day in the next
# 12 hours, each with its temperatures, words and rain chance
def weather_screen(hours, forecast, now):
    coming = [hour for hour in hours if datetime.datetime.fromisoformat(hour["time"]) >= now.replace(
        minute=0, second=0, microsecond=0)][:WEATHER_HOURS]

    # Without the hours there's nothing to say
    if not coming:
        return None
    wet = [hour for hour in coming if hour["rain"] >= WET]
    peak = max(coming, key=lambda hour: hour["rain"])
    peak_hour = int(peak["time"][11:13])

    # Rain (or snow, or storms) coming, falling now, or a dry spell
    if wet and wet[0] is coming[0]:
        dry_again = next((hour for hour in coming[coming.index(wet[-1]) + 1:]), None)
        banner = f"{wet_kind(coming)} now"
        under = f"Heaviest around {hour_text(peak_hour)} ({peak['rain']}%)" + (
            f", easing by {hour_text(int(dry_again['time'][11:13]))}." if dry_again else ", on and off all evening.")
    elif wet:
        start = int(wet[0]["time"][11:13])
        banner = f"{wet_kind(coming)} from {hour_text(start)}"
        under = f"Heaviest around {hour_text(peak_hour)} ({peak['rain']}%). Take an umbrella if you're out then."
    else:
        banner = f"No rain in the next {WEATHER_HOURS} hours"
        known = forecast and forecast.get("now") is not None
        under = f"{forecast['now']}° and {forecast['conditions']} now." if known else ""
    parts = []

    # The parts of the day the next 12 hours cover, in order (at most 3)
    for name, first, last in DAY_PARTS:
        part = [hour for hour in coming if first <= night_hour(hour) < last]

        # Only parts with hours in the window
        if part:
            parts.append(day_part(name, part, last))
    parts.sort(key=lambda part: part["order"])
    return {"banner": banner, "under": under,
            "parts": [{key: value for key, value in part.items() if key != "order"} for part in parts[:3]]}

# One part of the day on the weather screen: its name, hours, temperatures, words and highest rain chance
def day_part(name, hours, last):
    first_temp = hours[0]["temp"]
    last_temp = hours[-1]["temp"]
    top = max(hour["temp"] for hour in hours)
    rain = max(hour["rain"] for hour in hours)
    wet = [hour for hour in hours if hour["rain"] >= WET]
    start = int(hours[0]["time"][11:13])
    stop = min(night_hour(hours[-1]) + 1, last)  # The part ends at its own end, or where the 12 hours do

    # The temperatures: rising to a peak in the middle, or from start to end
    if top >= max(first_temp, last_temp) + 2:
        temps = f"up to {top}°"
    elif first_temp == last_temp:
        temps = f"{first_temp}°"
    else:
        temps = f"{first_temp}° → {last_temp}°"

    # The words: rain (from when, or all along), or the most common sky
    if wet and wet[0] is hours[0]:
        words = f"{wet_kind(hours)} on and off" if len(wet) < len(hours) else wet_kind(hours)
    elif wet:
        words = f"{wet_kind(hours)} from {hour_text(int(wet[0]['time'][11:13]))}"
    else:
        codes = [hour["code"] for hour in hours]
        words = "Dry, " + weather.WEATHER_WORDS.get(max(set(codes), key=codes.count), "mixed")
    return {"name": name, "span": f"{hour_text(start)} – {hour_text(stop)}", "temps": temps, "words": words,
            "rain": rain, "order": hours[0]["time"]}

# One line for an item on a coming day of the week screen: "4:00 PM · Study group · Library room 2"
def week_line(time_text, title, place=""):
    return " · ".join(part for part in (time_text, title, place) if part)

# The week screen: today in full (what's done faded; places, when to leave and what to bring), then the next 6 days
def week_screen(snapshot, now, nestor_reminders):
    today = now.date()
    rows = []

    # Today's events, past and still to come
    for event in snapshot.get("events") or []:
        start = read_moment(event.get("start"))

        # Only today's
        if not start or start.date() != today:
            continue
        timed = not event.get("all_day")
        leave_by = read_moment(event.get("leave_by"))
        travel = f" · {event['travel']}" if event.get("travel") else ""
        leave = f"Leave by {clock_text(leave_by)}{travel}" if leave_by and timed else ""
        rows.append((start.strftime("%H:%M") if timed else "", clock_text(start) if timed else "Today",
                     event.get("title") or "", event.get("place") or "", leave, event.get("bring") or "", "",
                     timed and start < now))

    # Today's reminders, Datebook's and Nestor's
    for reminder in snapshot.get("reminders") or []:
        at = read_moment(reminder.get("at"))

        # Only today's
        if at and at.date() == today:
            rows.append((at.strftime("%H:%M"), clock_text(at), reminder.get("text") or "", "", "", "", "Reminder",
                         at < now))

    # Nestor's reminders are "18:00" times for today
    for reminder in nestor_reminders:
        at = datetime.datetime.combine(today, datetime.time.fromisoformat(reminder["time"]))
        rows.append((reminder["time"], clock_text(at), reminder["text"], "", "", "", "Reminder", at < now))
    lists = snapshot.get("lists") or {}

    # Bills and assignments due today
    for part in ("bills", "assignments"):
        # Each one due today
        for item in lists.get(part) or []:
            due = read_moment(item.get("due"))

            # Only those due today
            if due and due.date() == today:
                rows.append(("", "Today", item.get("title") or "", item.get("class") or "", "", "", "Due", False))
    rows.sort(key=lambda row: row[0])
    days = []

    # The next 6 days, each with its events, reminders and what's due
    for ahead in range(1, 7):
        day = today + datetime.timedelta(days=ahead)
        lines = []

        # The day's events in time order (all-day ones first)
        for event in sorted(snapshot.get("events") or [], key=lambda event: event.get("start") or ""):
            start = read_moment(event.get("start"))

            # Only that day's
            if not start or start.date() != day:
                continue
            elif event.get("all_day"):
                lines.append(week_line("", event.get("title") or "", "all day"))
            else:
                lines.append(week_line(clock_text(start), event.get("title") or "", event.get("place") or ""))

        # Bills and assignments due that day
        for part, word in (("bills", "due"), ("assignments", "due")):
            # Each one due that day
            for item in lists.get(part) or []:
                due = read_moment(item.get("due"))

                # Only that day's, with its class and its time when it has one
                if due and due.date() == day:
                    timed = len(item.get("due", "")) > 10
                    name = item.get("title") or ""
                    name += f" ({item['class']})" if item.get("class") else ""
                    lines.append(f"{name} {word}" + (f" · {clock_text(due)}" if timed else ""))
        days.append({"day": f"{day.strftime('%a %b')} {day.day}", "items": lines})
    return {"today_name": now.strftime("%A"),
            "today": [{"time": time, "title": title, "place": place, "leave": leave, "bring": bring, "tag": tag,
                       "past": past} for key, time, title, place, leave, bring, tag, past in rows],
            "days": days}

# The men's foil screen: this week's events by day, LIVE with today's stage, its place among the stages and its
# stream times (just the schedule)
def foil_screen(fencing, now):
    days = {}
    week_end = now.date() + datetime.timedelta(days=7)

    # Each event this week that isn't over
    for event in fencing or []:
        start = read_moment(event.get("start"))
        end = read_moment(event.get("end")) or start

        # Only this week's, not over yet
        if not start or start.date() > week_end or end.date() < now.date():
            continue
        first = start.strftime("%a")
        last = end.strftime("%a")
        timed = len(event.get("start", "")) > 10
        label = f"{start.strftime('%a %b')} {start.day}"
        live_from = read_moment(event.get("live_from"))
        live_until = read_moment(event.get("live_until"))
        live = foil_live(event, now)
        days.setdefault((start.date(), label), []).append({
            "name": event.get("name") or "", "where": event.get("where") or "",
            "days": first if first == last else f"{first}–{last}", "time": clock_text(start) if timed else "",
            "live": live, "stage": event.get("stage") or "",
            "stream": f"Stream on {clock_text(live_from)} – {clock_text(live_until)}" if live_from and live_until
            else "", "stages": foil_stages(event.get("stage")) if live else []})
    return [{"day": label, "events": events} for (date, label), events in sorted(days.items())]

# The chip's temperature in °C on the Tinker Board (None elsewhere), so the wall can go lite when it runs hot
def chip_temperature():
    # Only Linux boards have it
    try:
        with open(CHIP_TEMP_PATH) as reading:
            return round(int(reading.read().strip()) / 1000)
    except (OSError, ValueError):
        return None
