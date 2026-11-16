# Reminders: one-off ones (added with remind.py or the API, saved in data/reminders.json) and repeating ones from
# reminders.yaml. Each is spoken a few minutes ahead and again at its time, as an alert (so quiet hours apply).
import datetime
import logging
import os
import threading
import time
import uuid
import yaml
from nestor.config import DATA_DIR
from nestor.config import PROJECT_DIR
from nestor.storage import read_json
from nestor.storage import write_json
from nestor.when import WEEKDAYS
from nestor.when import parse_clock
ONE_OFF_PATH = os.path.join(DATA_DIR, "reminders.json")
REPEATING_PATH = os.path.join(PROJECT_DIR, "reminders.yaml")
STATE_PATH = os.path.join(DATA_DIR, "reminders_state.json")
LATE_LIMIT = datetime.timedelta(minutes=10)  # Reminders missed by more than this (Nestor was off) are skipped
CHECK_SECONDS = 15
DAY_GROUPS = {"daily": list(range(7)), "every day": list(range(7)), "weekdays": list(range(5)), "weekends": [5, 6]}
file_lock = threading.Lock()
warned_entries = set()  # Bad reminders.yaml entries already reported, so they are logged once
log = logging.getLogger(__name__)

# Read the one-off reminders (a list of dicts with id, text, at and created)
def read_one_offs():
    return read_json(ONE_OFF_PATH, [])

# Save the one-off reminders, soonest first
def write_one_offs(reminders):
    write_json(ONE_OFF_PATH, sorted(reminders, key=lambda reminder: reminder["at"]))

# Add a one-off reminder for a moment and return it
def add_reminder(text, moment):
    reminder = {"id": uuid.uuid4().hex[:6], "text": text.strip(), "at": moment.isoformat(timespec="seconds"),
                "created": datetime.datetime.now().isoformat(timespec="seconds")}
    with file_lock:
        write_one_offs(read_one_offs() + [reminder])
    return reminder

# Delete a one-off reminder by its id; returns True if it was there
def delete_reminder(reminder_id):
    with file_lock:
        reminders = read_one_offs()
        kept = [reminder for reminder in reminders if reminder["id"] != reminder_id]
        write_one_offs(kept)
    return len(kept) < len(reminders)

# Turn a reminders.yaml "days" value ("daily", "weekdays", "tue", [tue, thu]) into weekday numbers
def parse_days(days):
    # Named groups, single days, and lists of days
    if isinstance(days, str) and days.lower() in DAY_GROUPS:
        return DAY_GROUPS[days.lower()]
    elif isinstance(days, str):
        days = [days]
    return [WEEKDAYS[str(day).lower()] for day in days]

# Log a problem with a reminders.yaml entry, once per entry
def warn_once(problem, entry):
    key = f"{problem}|{entry}"

    # Already reported
    if key in warned_entries:
        return
    warned_entries.add(key)
    log.warning("Skipping a reminders.yaml entry %s: %s", problem, entry)

# Read the repeating reminders from reminders.yaml as dicts with text, days, weekdays and time; bad entries are skipped
def read_repeating():
    # No file means no repeating reminders
    if not os.path.exists(REPEATING_PATH):
        return []

    # A broken file is reported, not fatal
    try:
        with open(REPEATING_PATH, encoding="utf-8") as repeating_file:
            entries = yaml.safe_load(repeating_file) or []
    except yaml.YAMLError as error:
        log.warning("reminders.yaml can't be read: %s", error)
        return []
    repeating = []

    # Check each entry and keep the good ones
    for entry in entries:
        # Skip entries with a missing or unreadable part
        try:
            clock = parse_clock(str(entry["time"]))
            weekdays = parse_days(entry.get("days", "daily"))
            text = str(entry["text"]).strip()
        except (KeyError, TypeError, AttributeError):
            warn_once("without text, time or valid days", entry)
            continue

        # The time must be readable too
        if not clock or not text:
            warn_once("with an unreadable time", entry)
            continue
        repeating.append({"text": text, "days": entry.get("days", "daily"), "weekdays": weekdays,
                          "time": clock.strftime("%H:%M")})
    return repeating

# Every reminder moment after start and up to end, as (moment, kind, text), kind "ahead" (heads-up) or "now"
def occurrences(start, end, heads_up):
    found = []

    # One-off reminders; no heads-up if it was set too late for one
    for reminder in read_one_offs():
        at = datetime.datetime.fromisoformat(reminder["at"])
        created = datetime.datetime.fromisoformat(reminder["created"])
        moments = [("now", at)] if at - heads_up < created else [("ahead", at - heads_up), ("now", at)]
        found += [(moment, kind, reminder["text"]) for kind, moment in moments if start < moment <= end]

    # Repeating reminders, on each day the range covers (plus one, for heads-ups just before midnight)
    for reminder in read_repeating():
        day = start.date()

        # Walk the days in the range
        while day <= (end + heads_up).date():
            # Only on the reminder's days of the week
            if day.weekday() in reminder["weekdays"]:
                at = datetime.datetime.combine(day, parse_clock(reminder["time"]))
                found += [(moment, kind, reminder["text"]) for kind, moment in
                          (("ahead", at - heads_up), ("now", at)) if start < moment <= end]
            day += datetime.timedelta(days=1)
    return sorted(found)

# Today's reminders in time order, for the briefing and the API: [{"time": "18:00", "text": "..."}]
def todays_reminders(today=None):
    today = today or datetime.date.today()
    start = datetime.datetime.combine(today, datetime.time(0, 0)) - datetime.timedelta(microseconds=1)
    end = datetime.datetime.combine(today, datetime.time(23, 59, 59))
    return [{"time": moment.strftime("%H:%M"), "text": text}
            for moment, kind, text in occurrences(start, end, datetime.timedelta(0)) if kind == "now"]

# Everything about reminders as JSON-ready data (for the API, the phone page and Datebook's wall display)
def reminders_data():
    repeating = [{"text": reminder["text"], "days": reminder["days"], "time": reminder["time"]}
                 for reminder in read_repeating()]
    return {"one_off": read_one_offs(), "repeating": repeating, "today": todays_reminders()}

# Read when the scheduler last checked, so a restart doesn't repeat or skip reminders
def read_last_check():
    saved = read_json(STATE_PATH, {}).get("last_check")
    return datetime.datetime.fromisoformat(saved) if saved else None

# Save when the scheduler last checked
def write_last_check(moment):
    write_json(STATE_PATH, {"last_check": moment.isoformat(timespec="seconds")})

# Checks every 15 seconds and hands due reminders to the announcer
class ReminderScheduler:
    # Start checking in the background
    def __init__(self, announcer, settings):
        self.announcer = announcer
        self.heads_up = datetime.timedelta(minutes=float(settings.get("reminder_heads_up_minutes", 15)))
        threading.Thread(target=self.run, name="reminders", daemon=True).start()

    # Background loop: speak what came due since the last check, and clear one-offs that are over
    def run(self):
        oldest_allowed = datetime.datetime.now() - LATE_LIMIT
        last_check = max(read_last_check() or oldest_allowed, oldest_allowed)

        # Runs for the life of the program; a failed check is logged and retried
        while True:
            now = datetime.datetime.now()

            # Report problems but keep checking
            try:
                self.speak_due(last_check, now)
                self.clear_finished(now)
                write_last_check(now)
                last_check = now
            except Exception as error:
                log.error("Reminder check failed: %s", error)
            time.sleep(CHECK_SECONDS)

    # Speak each reminder moment between the last check and now
    def speak_due(self, last_check, now):
        heads_up_minutes = round(self.heads_up.total_seconds() / 60)

        # Heads-ups say how long is left; the reminder itself says what it is
        for moment, kind, text in occurrences(last_check, now, self.heads_up):
            # The heads-up and the reminder are worded differently
            if kind == "ahead":
                self.announcer.alert(f"In {heads_up_minutes} minutes: {text}.", source="reminder")
            else:
                self.announcer.alert(f"Reminder: {text}.", source="reminder")

    # Remove one-off reminders whose time has passed (they have just been spoken, or were missed while Nestor was off)
    def clear_finished(self, now):
        with file_lock:
            reminders = read_one_offs()
            upcoming = [reminder for reminder in reminders if datetime.datetime.fromisoformat(reminder["at"]) > now]

            # Only rewrite the file when something finished
            if len(upcoming) < len(reminders):
                write_one_offs(upcoming)
