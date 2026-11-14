# Command-line tool that makes the speaker say something, e.g. python speak.py "dinner's ready"
import argparse
import logging
import sys
from nestor.client import WAIT_TIMEOUT_SECONDS
from nestor.client import post_to_nestor
from nestor.config import load_config

# Speak without the service: start a temporary one, say the text, and shut it down
def speak_directly(text, settings):
    from nestor.service import Service
    logging.basicConfig(level=logging.WARNING)
    service = Service(settings)
    service.announcer.say(text).wait(WAIT_TIMEOUT_SECONDS)
    service.stop()

# Read the command line and speak the text
def main():
    parser = argparse.ArgumentParser(description="Make the speaker say something.")
    parser.add_argument("text", nargs="+", help="what to say")
    parser.add_argument("--wait", action="store_true", help="return only after the message has been spoken")
    args = parser.parse_args()
    text = " ".join(args.text)

    # Prefer the running service, which already holds the speaker connection
    try:
        sent = post_to_nestor("/speak", {"text": text, "wait": args.wait})
    except ValueError as refusal:
        sys.exit(f"Nestor refused the message: {refusal}")

    # Nestor isn't running, so connect to the speaker directly
    if not sent:
        speak_directly(text, load_config())

# Run only when started as a script
if __name__ == "__main__":
    main()
