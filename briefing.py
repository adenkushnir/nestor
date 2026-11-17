# Plays the briefing on the speaker (python briefing.py), or only shows it (--show for the text, --json for the data);
# --tomorrow gives the goodnight preview of tomorrow instead of the day ahead
import argparse
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # Lets it run from any folder
from nestor.briefing import build_briefing
from nestor.client import WAIT_TIMEOUT_SECONDS
from nestor.client import post_to_nestor
from nestor.config import load_config

# Speak without the service: start a temporary one, say the briefing, and shut it down
def speak_directly(settings, day):
    import logging
    from nestor.service import Service
    logging.basicConfig(level=logging.WARNING)
    service = Service(settings)
    service.announcer.say(build_briefing(settings, day=day)["text"]).wait(WAIT_TIMEOUT_SECONDS)
    service.stop()

# Show or speak the briefing, as asked on the command line
def main():
    parser = argparse.ArgumentParser(description="Play the briefing on the speaker.")
    parser.add_argument("--show", action="store_true", help="print the briefing instead of speaking it")
    parser.add_argument("--json", action="store_true", help="print the briefing data as JSON")
    parser.add_argument("--tomorrow", action="store_true", help="preview tomorrow instead of today")
    args = parser.parse_args()
    settings = load_config()
    day = "tomorrow" if args.tomorrow else "today"

    # Showing needs no speaker
    if args.show or args.json:
        briefing = build_briefing(settings, day=day)
        print(json.dumps(briefing, indent=1) if args.json else briefing["text"])

        # Explain a missing weather report
        if briefing["weather_problem"] and not args.json:
            print(f"(No weather: {briefing['weather_problem']})", file=sys.stderr)
        return

    # Prefer the running service, which already holds the speaker connection
    try:
        sent = post_to_nestor("/briefing", {"wait": True, "day": day})
    except ValueError as refusal:
        sys.exit(f"Nestor refused: {refusal}")

    # Nestor isn't running, so connect to the speaker directly
    if not sent:
        speak_directly(settings, day)

# Run only when started as a script
if __name__ == "__main__":
    main()
