# Speaks a heads-up before calendar events from Datebook ("In 10 minutes: CS lecture."), for events with a time of
# day and no leave-by from Datebook (that one already tells you when to go). Only while the phone is home.
import datetime
import logging
import os
import threading
import time
from nestor import datebook
from nestor.config import DATA_DIR
from nestor.storage import read_json
from nestor.storage import write_json
STATE_PATH = os.path.join(DATA_DIR, "event_alerts_state.json")
LATE_LIMIT = datetime.timedelta(minutes=10)  # Heads-ups missed by more than this (Nestor was off) are skipped
CHECK_SECONDS = 15
log = logging.getLogger(__name__)

# The heads-up sentence for an event: "In 10 minutes: CS lecture."
def heads_up_text(event, minutes):
    title = event["title"].rstrip(".!?")
    return f"In {minutes} minute: {title}." if minutes == 1 else f"In {minutes} minutes: {title}."

# The events whose heads-up moment (start minus heads_up) falls after start_check and up to end_check, as
# (moment, event) pairs; all-day events and events with a Datebook leave-by are left out
def due_heads_ups(state, start_check, end_check, heads_up):
    due = []

    # Look at every event Datebook sent
    for event in state.get("events") or []:
        cleaned = datebook.clean_event(event)

        # Only timed events without a leave-by
        if not cleaned or cleaned["all_day"] or cleaned["leave_by"]:
            continue
        moment = cleaned["begins"] - heads_up

        # Only heads-ups that came due in this check
        if start_check < moment <= end_check:
            due.append((moment, cleaned))
    return sorted(due, key=lambda pair: pair[0])

# Read when the heads-ups were last checked, so a restart doesn't repeat or skip them
def read_last_check():
    saved = read_json(STATE_PATH, {}).get("last_check")
    return datetime.datetime.fromisoformat(saved) if saved else None

# Save when the heads-ups were last checked
def write_last_check(moment):
    write_json(STATE_PATH, {"last_check": moment.isoformat(timespec="seconds")})

# Checks every 15 seconds and hands due event heads-ups to the announcer
class EventAlerts:
    # Start checking in the background
    def __init__(self, announcer, settings):
        self.announcer = announcer
        self.minutes = int(settings.get("event_heads_up_minutes", 10))
        threading.Thread(target=self.run, name="event-alerts", daemon=True).start()

    # Background loop: speak the heads-ups that came due since the last check
    def run(self):
        oldest_allowed = datetime.datetime.now() - LATE_LIMIT
        last_check = max(read_last_check() or oldest_allowed, oldest_allowed)

        # Runs for the life of the program; a failed check is logged and retried
        while True:
            now = datetime.datetime.now()

            # Report problems but keep checking
            try:
                self.speak_due(last_check, now)
                write_last_check(now)
                last_check = now
            except Exception as error:
                log.error("Event heads-up check failed: %s", error)
            time.sleep(CHECK_SECONDS)

    # Speak each heads-up between the last check and now, if the phone is home (nobody needs one in an empty house)
    def speak_due(self, last_check, now):
        state = datebook.read_state(now)

        # Turned off, or nobody home
        if self.minutes <= 0 or not state["phone_home"]:
            return

        # Each due event gets one heads-up; it expires when the event starts, and its key stops repeats
        for moment, event in due_heads_ups(state, last_check, now, datetime.timedelta(minutes=self.minutes)):
            self.announcer.alert(heads_up_text(event, self.minutes), source="calendar",
                                 expires=event["begins"].isoformat(timespec="seconds"),
                                 key=f"event:{event['id'] or event['title']}:{event['start']}")
