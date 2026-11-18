# Works out whether it is quiet hours (the sleeping period) right now: from a setting like "22:00-08:00" (which runs
# past midnight), unless "goodnight" or "start my day" moved it, which lasts until the schedule's next change
import datetime
import os
from nestor.config import DATA_DIR
from nestor.storage import read_json
from nestor.storage import write_json
SLEEP_PATH = os.path.join(DATA_DIR, "sleep.json")
DEFAULT_WAKE = datetime.time(8, 0)  # Without a quiet_hours setting, "goodnight" lasts until 8 AM

# Turn "HH:MM" into a time of day
def parse_clock(clock_text):
    hours, minutes = clock_text.strip().split(":")
    return datetime.time(int(hours), int(minutes))

# The sleeping period set by voice at a moment: "asleep" or "awake", or None once it has run out (the schedule decides)
def sleep_override(moment):
    saved = read_json(SLEEP_PATH, {})
    until = saved.get("until")

    # Only a mode that hasn't run out counts
    if saved.get("mode") in ("asleep", "awake") and until and datetime.datetime.fromisoformat(until) > moment:
        return saved["mode"]
    return None

# The next moment after now that is at the given time of day
def next_time_of_day(now, clock):
    moment = datetime.datetime.combine(now.date(), clock)
    return moment if moment > now else moment + datetime.timedelta(days=1)

# Quiet hours from a "start-end" setting; an empty setting means it is never quiet (unless "goodnight" was said)
class QuietHours:
    # Read the start and end times from the setting
    def __init__(self, setting):
        self.start = None
        self.end = None

        # No setting, no quiet hours
        if setting:
            start_text, end_text = setting.split("-")
            self.start = parse_clock(start_text)
            self.end = parse_clock(end_text)

    # True if the given moment (default: now) falls inside the sleeping period
    def is_quiet(self, moment=None):
        moment = moment or datetime.datetime.now()
        override = sleep_override(moment)

        # "Goodnight" and "start my day" win over the schedule until it next changes
        if override:
            return override == "asleep"
        return self.scheduled_quiet(moment)

    # True if the moment falls inside the quiet_hours schedule
    def scheduled_quiet(self, moment):
        # Never quiet without a setting
        if self.start is None:
            return False
        clock = moment.time()

        # A range like 22:00-08:00 wraps past midnight
        if self.start <= self.end:
            return self.start <= clock < self.end
        else:
            return clock >= self.start or clock < self.end

    # "Goodnight": start the sleeping period now, until quiet hours would next end; returns when it ends
    def go_to_sleep(self, now=None):
        now = now or datetime.datetime.now()
        until = next_time_of_day(now, self.end or DEFAULT_WAKE)
        write_json(SLEEP_PATH, {"mode": "asleep", "until": until.isoformat(timespec="seconds")})
        return until

    # "Start my day": end the sleeping period now, until quiet hours would next start; returns when that is (None
    # without a schedule, where it's never quiet anyway)
    def wake_up(self, now=None):
        now = now or datetime.datetime.now()

        # Without a schedule there's nothing to hold off
        if self.start is None:
            write_json(SLEEP_PATH, {})
            return None
        until = next_time_of_day(now, self.start)
        write_json(SLEEP_PATH, {"mode": "awake", "until": until.isoformat(timespec="seconds")})
        return until
