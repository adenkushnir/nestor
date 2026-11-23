# The wall display's live feed: what has to show at once rather than at the next 20-second update. John's state (idle,
# listening, thinking, talking, follow-up) for the edge glow and the hare's eyes, what's ringing (with its Stop and
# Snooze card), the sleeping period (the night clock) with the first alarm, the timers counting down, and a bigger
# screen John was asked to open.
import datetime
import threading
from nestor import timers
JOHN_STATES = ("idle", "listening", "thinking", "talking", "followup")
WALL_VIEWS = ("week", "weather", "fencing", "close")
ALARM_AHEAD_HOURS = 24  # The night clock shows the first alarm within this many hours
changed = threading.Condition()
version = 0
john_state = "idle"
john_window = 0  # How long the follow-up John is in listens for (0 when he isn't)
big_request = None  # The last bigger screen asked for: {"view": "week", "id": 3} (the id tells a new ask from an old)

# Tell everyone watching the feed that something changed
def poke():
    global version

    # Wake every waiting feed
    with changed:
        version += 1
        changed.notify_all()

# Set John's state ("idle", "listening", "thinking", "talking" or "followup"); window is how many seconds a follow-up
# listens, so the wall's glow can dim over it
def set_john(state, window=0):
    global john_state, john_window

    # Only a real change is sent on
    if state in JOHN_STATES and (state, window) != (john_state, john_window):
        john_state = state
        john_window = window if state == "followup" else 0
        poke()

# Open a bigger screen on the wall ("week", "weather" or "fencing"), or close it ("close"); returns what was asked
def show(view):
    global big_request

    # Only the wall's screens
    if view not in WALL_VIEWS:
        raise ValueError(f"the wall has no {view!r} screen; use one of {', '.join(WALL_VIEWS)}")
    big_request = {"view": view, "id": (big_request or {}).get("id", 0) + 1}
    poke()
    return big_request

# Wait until something changes (up to timeout seconds); returns the version now
def wait(seen, timeout):
    # Sleep until poked, unless something already changed
    with changed:
        changed.wait_for(lambda: version != seen, timeout)
        return version

# A countdown's name on its chip: its label, "Snoozed alarm", or its length ("10 min")
def chip_label(item):
    # A label wins, then a snoozed alarm, then the timer's length
    if item.get("label"):
        return item["label"].capitalize()
    elif item["kind"] == "alarm":
        return "Snoozed alarm"
    minutes = round(item.get("seconds", 0) / 60)
    return f"{minutes} min" if minutes else f"{item.get('seconds', 0)} s"

# What the ringing card says: a title ("Pasta timer is done", "7:00 AM · Gym") and the small label above it
def ring_card(item, now):
    clock = f"{now.hour % 12 or 12}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}"
    minutes = round(item.get("seconds", 0) / 60)

    # Timers name their label or length; alarms show the time and their label
    if item["kind"] == "timer":
        name = item["label"].capitalize() if item.get("label") else f"{minutes} min" if minutes else "Your"
        sub = f"Timer · {minutes} min" if minutes else "Timer"
        return {"kind": "timer", "title": f"{name} timer is done", "sub": sub}
    name = item["label"].capitalize() if item.get("label") else "Alarm"
    return {"kind": "alarm", "title": f"{clock} · {name}", "sub": "Snoozed alarm" if item.get("snoozed") else "Alarm"}

# Everything the live feed carries right now
def live_state(announcer, now=None):
    now = now or datetime.datetime.now()
    data = timers.timers_data(now)
    chips = []
    first_alarm = None

    # Timers and snoozed alarms count down on chips; the first other alarm shows on the night clock
    for item in data["items"]:
        rings = datetime.datetime.fromisoformat(item["rings"])

        # Only what's still to come
        if rings <= now:
            continue
        elif item["kind"] == "timer" or item.get("snoozed"):
            chips.append({"label": chip_label(item), "ends": item["rings"], "total": item.get("seconds") or 0})
        elif not first_alarm and rings - now <= datetime.timedelta(hours=ALARM_AHEAD_HOURS):
            first_alarm = f"{rings.hour % 12 or 12}:{rings.minute:02d} {'AM' if rings.hour < 12 else 'PM'}"
    ringing = data["ringing"]
    return {"john": john_state, "john_window": john_window, "ringing": ring_card(ringing, now) if ringing else None,
            "sleeping": bool(announcer.quiet_hours.is_quiet()), "alarm": first_alarm, "timers": chips,
            "big": big_request}
# The feed hears about every change to the timers and the ringing
timers.listeners.append(poke)
