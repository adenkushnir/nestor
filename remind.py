# Adds a one-off reminder, e.g. remind 18:00 call mum, remind tomorrow 9:30 dentist, remind take the pizza out in 20m
import argparse
import datetime
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # Lets it run from any folder
from nestor.client import post_to_nestor
from nestor.config import load_config
from nestor.quiet import QuietHours
from nestor.reminders import add_reminder
from nestor.spoken import spoken_moment
from nestor.when import split_when_and_text
EXAMPLES = "e.g. remind 18:00 call mum, remind tomorrow 9:30 dentist, or remind take the pizza out in 20m"

# Read the reminder from the command line, save it, and confirm when it will be spoken
def main():
    parser = argparse.ArgumentParser(description="Add a reminder that the speaker says at its time.", epilog=EXAMPLES)
    parser.add_argument("words", nargs="+", help="when and what, in either order")
    args = parser.parse_args()
    settings = load_config()
    moment, text = split_when_and_text(args.words)

    # Both a time and something to remind about are needed
    if moment is None:
        sys.exit(f"I couldn't find a time in that. {EXAMPLES}")
    elif not text:
        sys.exit(f"What should I remind you about? {EXAMPLES}")

    # Hand it to the running Nestor; if it isn't running, save it where Nestor will find it
    try:
        sent = post_to_nestor("/reminders", {"text": text, "at": moment.isoformat(timespec="seconds")}, timeout=10)
    except ValueError as refusal:
        sys.exit(f"Nestor refused the reminder: {refusal}")

    # Nestor isn't running, so write it to the reminders file directly
    if not sent:
        add_reminder(text, moment)
    print(f"OK: \"{text}\", {spoken_moment(moment)}.")
    heads_up = datetime.timedelta(minutes=float(settings.get("reminder_heads_up_minutes", 15)))

    # Mention the heads-up when there's time for one
    if moment - datetime.datetime.now() > heads_up:
        print(f"You'll also get a heads-up {round(heads_up.total_seconds() / 60)} minutes before.")

    # Warn when the speaker will hold it until morning
    if QuietHours(settings.get("quiet_hours", "")).is_quiet(moment):
        print("Note: that's during quiet hours, so it will be held and spoken when they end.")

    # Without Nestor running at that time, nothing will be spoken
    if not sent:
        print("Nestor isn't running right now. Start it (python -m nestor) before then, or the reminder is missed.")

# Run only when started as a script
if __name__ == "__main__":
    main()
