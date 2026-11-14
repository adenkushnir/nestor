# Command-line tool that makes the speaker say something, e.g. python speak.py "dinner's ready"
import argparse
import json
import logging
import sys
import urllib.error
import urllib.request
from nestor.config import load_config
WAIT_TIMEOUT_SECONDS = 180

# Send the text to the running Nestor service; returns False if the service isn't running
def send_to_service(text, port, wait):
    body = json.dumps({"text": text, "wait": wait}).encode("utf-8")
    speak_request = urllib.request.Request(f"http://127.0.0.1:{port}/speak", data=body,
                                           headers={"Content-Type": "application/json"})

    # Connection refused means Nestor isn't running; other errors are reported
    try:
        with urllib.request.urlopen(speak_request, timeout=WAIT_TIMEOUT_SECONDS + 10):
            return True
    except urllib.error.HTTPError as error:
        sys.exit(f"Nestor refused the message: {error.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as error:
        # Only a refused connection falls back to speaking directly
        if isinstance(error.reason, ConnectionRefusedError):
            return False
        raise

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
    settings = load_config()

    # Prefer the running service; it already holds the speaker connection
    if not send_to_service(text, int(settings.get("port", 8765)), args.wait):
        speak_directly(text, settings)

# Run only when started as a script
if __name__ == "__main__":
    main()
