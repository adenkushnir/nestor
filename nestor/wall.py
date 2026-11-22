# What the wall screen shows, gathered in one place for its page: the weather and sun times, the next event and the
# rest of today from Datebook, the list counts, the train board for the saved trip, what's playing and the men's foil
# schedule. Slow sources (the weather, NJ Transit) are kept for a few minutes, so the page can ask often.
import datetime
import logging
import threading
from nestor import datebook
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

# The next timed event today that hasn't started (None when nothing else has a time today)
def next_event(events, now):
    upcoming = [event for event in events if not event.get("all_day") and read_moment(event.get("start"))
                and read_moment(event["start"]) > now and read_moment(event["start"]).date() == now.date()]
    return min(upcoming, key=lambda event: event["start"]) if upcoming else None

# The status line under the Next card: the event's train from the live board, or its flight from Datebook (None when
# there's neither)
def travel_status(event, board_rows):
    flight = event.get("flight") or {}
    train = event.get("train") or {}

    # A flight carries its own status; a train is looked up on the board by its departure time
    if flight.get("text"):
        return {"kind": "flight", "text": flight["text"], "late": bool(flight.get("late"))}
    elif not train.get("departs"):
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
# the train or flight line
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
            "bring": event.get("bring") or "", "status": travel_status(event, board_rows)}

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

# Keeps the wall's slow sources (weather and trains) and puts together everything the screen shows
class Wall:
    # Keep the settings and the NJ Transit account (None without one)
    def __init__(self, settings, rail):
        self.settings = settings
        self.rail = rail
        self.lock = threading.Lock()
        self.weather = None
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
            self.weather = weather.forecast(location, self.settings.get("temperature_unit", "fahrenheit"))
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
            snapshot = datebook.read_state(now)
            trip_names = snapshot.get("trip") or {}
            trip = (trip_names.get("from") or self.settings.get("train_from", ""),
                    trip_names.get("to") or self.settings.get("train_to", ""))
            board = self.current_board(trip, now)
            left = self.left
        rows = train_rows(board, trip[1], left, now) if trip[1] else []
        event = next_event(snapshot.get("events") or [], now)
        music = spotify.music.now if spotify.music else None
        return {
            "now": now.isoformat(timespec="seconds"),
            "weather": forecast and {"temp": forecast["now"], "unit": forecast["unit"],
                                     "words": forecast["conditions"].capitalize(),
                                     "scene": scene_for(forecast.get("code")), "rain_from": wet_later(forecast),
                                     "sunrise": forecast["sunrise"], "sunset": forecast["sunset"]},
            "datebook": snapshot["connected"],
            "next": next_card(event, now, rows) if event else None,
            "later": later_today(snapshot, now, event, reminders.todays_reminders(now.date())),
            "counts": list_counts(snapshot.get("lists")),
            "updated": updated_line(snapshot, now),
            "trains": {"title": f"{trip_names.get('from_name') or trip[0]} → {trip_names.get('to_name') or trip[1]}",
                       "rows": rows} if trip[0] and trip[1] and self.rail else None,
            "music": music if music and music.get("playing") else None,
            "foil": foil_rows(snapshot.get("fencing"), now),
        }

# "Rain from 4 PM" for the weather line, only while it's dry now and rain is likely later today (None otherwise)
def wet_later(forecast):
    dry_now = scene_for(forecast.get("code")) in ("clear", "partly", "overcast")

    # Rain on the way while it's still dry
    if dry_now and forecast.get("rain_from"):
        hour = int(forecast["rain_from"][:2])
        return f"Rain from {hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"
    return None
