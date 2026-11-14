# Works out whether it is quiet hours right now, from a setting like "22:00-08:00" (which runs past midnight)
import datetime

# Turn "HH:MM" into a time of day
def parse_clock(clock_text):
    hours, minutes = clock_text.strip().split(":")
    return datetime.time(int(hours), int(minutes))

# Quiet hours from a "start-end" setting; an empty setting means it is never quiet
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

    # True if the given moment (default: now) falls inside quiet hours
    def is_quiet(self, moment=None):
        # Never quiet without a setting
        if self.start is None:
            return False
        clock = (moment or datetime.datetime.now()).time()

        # A range like 22:00-08:00 wraps past midnight
        if self.start <= self.end:
            return self.start <= clock < self.end
        else:
            return clock >= self.start or clock < self.end
