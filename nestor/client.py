# Small client for scripts (speak.py, tell.py, the Claude Code hook) to send messages to the running Nestor service
import json
import os
import urllib.error
import urllib.request
from nestor.config import load_config
WAIT_TIMEOUT_SECONDS = 180

# Where the running Nestor is: the NESTOR_URL environment variable, nestor_url in config.yaml (e.g. the Tinker Board),
# or this computer
def nestor_address():
    settings = load_config()
    url = os.environ.get("NESTOR_URL") or settings.get("nestor_url")
    return (url or f"http://127.0.0.1:{int(settings.get('port', 8765))}").rstrip("/")

# Send a JSON payload to a Nestor endpoint; returns False if Nestor isn't running, raises ValueError if it refuses
def post_to_nestor(path, payload, timeout=WAIT_TIMEOUT_SECONDS + 10):
    body = json.dumps(payload).encode("utf-8")
    nestor_request = urllib.request.Request(nestor_address() + path, data=body,
                                            headers={"Content-Type": "application/json"})

    # A refused connection means Nestor isn't running; Nestor's own refusals carry a reason
    try:
        with urllib.request.urlopen(nestor_request, timeout=timeout):
            return True
    except urllib.error.HTTPError as error:
        raise ValueError(error.read().decode("utf-8", "replace"))
    except urllib.error.URLError as error:
        # Only "not running" is an expected failure
        if isinstance(error.reason, ConnectionRefusedError):
            return False
        raise
