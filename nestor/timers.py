# Timers and alarms ("set a timer for 10 minutes", "wake me at 7", "every weekday at 6:45"), kept in
# data/timers.json. They ring on the speaker in bursts (the alarm tone and a spoken line, then a short gap, so John can
# hear "stop" or "snooze"), up to 5 minutes for alarms and 1 minute for timers, at alarm_volume. The first burst says
# what's ringing; after that it's the tone only. Snooze is 9 minutes unless you say how long, and stopping an alarm
# during the sleeping period also starts the day.
import datetime
import logging
import os
import threading
import time
import uuid
from nestor import routines
from nestor.config import DATA_DIR
from nestor.reminders import parse_days
from nestor.sounds import ensure_sound
from nestor.spoken import spoken_clock
from nestor.spoken import spoken_duration
from nestor.spoken import spoken_moment
from nestor.storage import read_json
from nestor.storage import write_json
from nestor.when import parse_clock
TIMERS_PATH = os.path.join(DATA_DIR, "timers.json")
STATE_PATH = os.path.join(DATA_DIR, "timers_state.json")
LATE_LIMIT = datetime.timedelta(minutes=10)  # Timers and alarms missed by more than this (Nestor was off) are skipped
ALARM_RING_SECONDS = 300
TIMER_RING_SECONDS = 60
GAP_SECONDS = 4  # Quiet between bursts, so "Hey John, stop" can be heard
SNOOZE_MINUTES = 9
CHECK_SECONDS = 1
timers_lock = threading.Lock()
scheduler = None  # The running TimerScheduler, so John and the API can stop or snooze what's ringing
listeners = []  # Called whenever the timers change or something starts or stops ringing (the wall's live feed)
log = logging.getLogger(__name__)

# Tell the listeners that the timers or the ringing changed
def tell_listeners():
    # Each listener, once
    for listener in listeners:
        listener()

# All timers and alarms: dicts with id, kind ("timer" or "alarm"), label, and either at (one-off) or time and days
# (a repeating alarm, days as weekday numbers with Monday = 0)
def read_items():
    return read_json(TIMERS_PATH, [])

# Save the timers and alarms, and tell the listeners
def write_items(items):
    write_json(TIMERS_PATH, items)
    tell_listeners()

# Add an item to the saved list and return it
def save_item(item):
    # One change to the file at a time
    with timers_lock:
        write_items(read_items() + [item])
    return item

# Start a timer that rings after the given seconds; returns it
def add_timer(seconds, label="", now=None):
    now = now or datetime.datetime.now()
    at = now + datetime.timedelta(seconds=round(seconds))
    return save_item({"id": uuid.uuid4().hex[:6], "kind": "timer", "label": str(label).strip(),
                      "seconds": round(seconds), "at": at.isoformat(timespec="seconds")})

# Set an alarm: one-off at the next time of day it comes round (or on a date), or repeating on days like "weekdays"
# or "mon, wed"; returns it
def add_alarm(clock_text, label="", date_text="", days="", now=None):
    now = now or datetime.datetime.now()
    clock = parse_clock(str(clock_text))
    item = {"id": uuid.uuid4().hex[:6], "kind": "alarm", "label": str(label).strip()}

    # The time must be readable; then repeating alarms keep their time and days, and one-off alarms get a moment
    if clock is None:
        raise ValueError(f"couldn't read the time {clock_text!r}; use one like 07:00")
    elif str(days).strip():
        weekdays = parse_days([day.strip() for day in str(days).split(",")] if "," in str(days) else str(days).strip())
        item.update(time=clock.strftime("%H:%M"), days=weekdays)
    else:
        day = datetime.date.fromisoformat(date_text) if date_text else now.date()
        at = datetime.datetime.combine(day, clock)

        # A time already gone today means tomorrow; a date in the past can't be used
        if at <= now and not date_text:
            at += datetime.timedelta(days=1)
        elif at <= now:
            raise ValueError("that date and time have already passed")
        item.update(at=at.isoformat(timespec="seconds"))
    return save_item(item)

# The next moment after `after` that an item rings (None for a repeating alarm with no days)
def next_ring(item, after):
    # One-off timers and alarms ring once
    if "at" in item:
        return datetime.datetime.fromisoformat(item["at"])
    clock = parse_clock(item["time"])

    # Look at the coming week for the first day it's set for
    for days_ahead in range(8):
        moment = datetime.datetime.combine(after.date() + datetime.timedelta(days=days_ahead), clock)

        # The first matching day still to come
        if moment > after and moment.weekday() in item["days"]:
            return moment
    return None

# Cancel a timer or alarm by its id; returns True if there was one
def cancel(item_id):
    # One change to the file at a time
    with timers_lock:
        items = read_items()
        remaining = [item for item in items if item["id"] != item_id]
        write_items(remaining)
    return len(remaining) < len(items)

# The timers and alarms as data for John and the API: each with when it next rings, said aloud, and what's left
def timers_data(now=None):
    now = now or datetime.datetime.now()
    listed = []

    # Each item with its next ring
    for item in read_items():
        moment = next_ring(item, now - LATE_LIMIT)

        # Skip anything that no longer rings
        if moment:
            listed.append(dict(item, rings=moment.isoformat(timespec="seconds"), said_as=spoken_moment(moment, now),
                               left=spoken_duration(max(0, (moment - now).total_seconds()))))
    return {"items": sorted(listed, key=lambda item: item["rings"]),
            "ringing": scheduler.ringing if scheduler else None}

# What a ringing item says: "Your 10 minute timer is done." / "Your pasta timer is done." / "It's 7 AM. Gym."
def ring_line(item, now):
    # Timers name their label or length; alarms say the time and their label
    if item["kind"] == "timer" and item["label"]:
        return f"Your {item['label']} timer is done."
    elif item["kind"] == "timer":
        length = spoken_duration(item.get("seconds", 0))
        length = length.replace("minutes", "minute").replace("seconds", "second").replace("hours", "hour")
        return f"Your {length} timer is done."
    else:
        return f"It's {spoken_clock(now.time())}." + (f" {item['label']}." if item["label"] else "")

# The timers and alarms that came due after last_check and up to now
def due_items(last_check, now):
    return [item for item in read_items() if next_ring(item, last_check) and
            last_check < next_ring(item, last_check) <= now]

# Read when timers were last checked, so a restart doesn't repeat or skip them
def read_last_check():
    saved = read_json(STATE_PATH, {}).get("last_check")
    return datetime.datetime.fromisoformat(saved) if saved else None

# Rings timers and alarms when they come due, and stops or snoozes the one ringing
class TimerScheduler:
    # Start checking every second in the background
    def __init__(self, announcer, settings):
        global scheduler
        self.announcer = announcer
        self.settings = settings
        self.ringing = None  # The item ringing now, if any
        self.stop_request = None  # "stop" or "snooze" while ringing
        self.snooze_minutes = SNOOZE_MINUTES
        self.volume = float(settings.get("alarm_volume", 0.75))
        self.paused = threading.Event()  # Set while John is talking, so the ringing waits
        scheduler = self
        threading.Thread(target=self.run, name="timers", daemon=True).start()

    # Background loop: ring what came due since the last check, and clear finished one-offs
    def run(self):
        oldest_allowed = datetime.datetime.now() - LATE_LIMIT
        last_check = max(read_last_check() or oldest_allowed, oldest_allowed)

        # Runs for the life of the program; a failed check is logged and retried
        while True:
            now = datetime.datetime.now()

            # Report problems but keep checking
            try:
                due = due_items(last_check, now)
                write_json(STATE_PATH, {"last_check": now.isoformat(timespec="seconds")})
                last_check = now

                # Ring each due item in turn, then forget the one-offs
                for item in due:
                    self.ring(item)

                    # Repeating alarms stay; one-offs are done
                    if "at" in item:
                        cancel(item["id"])
            except Exception as error:
                log.error("Timer check failed: %s", error)
            time.sleep(CHECK_SECONDS)

    # Ring one item in bursts until it's stopped or snoozed, or its time runs out
    def ring(self, item):
        self.ringing = item
        self.stop_request = None
        tell_listeners()
        tone, tone_seconds = ensure_sound("alarm")
        limit = ALARM_RING_SECONDS if item["kind"] == "alarm" else TIMER_RING_SECONDS
        started = time.time()
        speaker = self.announcer.speaker
        volume_before = speaker.volume()
        spoken_once = False
        log.info("Ringing: %s", ring_line(item, datetime.datetime.now()))
        speaker.set_volume(self.volume)  # Once for the whole ringing, since every change makes the speaker's sound

        # Ring until stopped, and always put the volume back afterwards
        try:
            # Burst, gap, burst... (waiting while John is talking)
            while self.stop_request is None and time.time() - started < limit:
                # Hold off while John is in a conversation
                if self.paused.is_set():
                    time.sleep(0.2)
                    continue
                done = self.announcer.sound(tone, tone_seconds)

                # Only the first burst says what's ringing, so the room is quieter for "stop"
                if spoken_once:
                    done.wait(60)
                else:
                    self.announcer.say(ring_line(item, datetime.datetime.now()), with_chime=False).wait(60)
                    spoken_once = True
                self.wait_for_stop(GAP_SECONDS)
        finally:
            self.ringing = None
            tell_listeners()
            speaker.set_volume(volume_before)
        self.after_ringing(item)

    # Wait up to the given seconds, ending early if the ringing is stopped
    def wait_for_stop(self, seconds):
        ends = time.time() + seconds

        # Check a few times a second
        while self.stop_request is None and time.time() < ends:
            time.sleep(0.1)

    # What happens once ringing ends: a snooze sets the alarm again; stopping an alarm in the sleeping period starts
    # the day
    def after_ringing(self, item):
        # Snooze, a stopped alarm at night, or nothing more
        if self.stop_request == "snooze":
            at = datetime.datetime.now() + datetime.timedelta(minutes=self.snooze_minutes)
            save_item(dict(item, id=uuid.uuid4().hex[:6], at=at.isoformat(timespec="seconds"), time=None, days=None,
                           snoozed=True, seconds=self.snooze_minutes * 60))
            self.announcer.say(f"Snoozing for {spoken_duration(self.snooze_minutes * 60)}.", with_chime=False)
        elif self.stop_request == "stop" and item["kind"] == "alarm" and self.announcer.quiet_hours.is_quiet():
            routines.start_my_day(self.announcer, self.settings)

    # Stop what's ringing; returns True if something was
    def stop(self):
        # Only a ringing item can be stopped
        if self.ringing is None:
            return False
        self.stop_request = "stop"
        return True

    # Snooze what's ringing, for 9 minutes unless told otherwise; returns True if something was
    def snooze(self, minutes=SNOOZE_MINUTES):
        # Only a ringing item can be snoozed
        if self.ringing is None:
            return False
        self.snooze_minutes = max(1, minutes)
        self.stop_request = "snooze"
        return True
