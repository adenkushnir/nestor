# Claude Code hook: when a reply took a while, the speaker says "Claude finished in Red Piste after 4 minutes".
# Runs on the UserPromptSubmit (start the clock) and Stop (check the time) events. It prints nothing and never fails,
# so it can't get in Claude Code's way.
import json
import os
import re
import sys
import time
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)
from nestor.client import post_to_nestor
from nestor.config import DATA_DIR
from nestor.config import load_config
from nestor.spoken import spoken_duration
from nestor.spoken import spoken_project
TURN_DIR = os.path.join(DATA_DIR, "claude_turns")
STALE_SECONDS = 24 * 60 * 60

# File holding the start time of a session's current turn
def turn_path(session_id):
    safe_id = re.sub(r"[^A-Za-z0-9-]", "", session_id) or "unknown"
    return os.path.join(TURN_DIR, f"{safe_id}.txt")

# Note that a turn has started, and tidy away start times from sessions that ended long ago
def record_start(session_id):
    os.makedirs(TURN_DIR, exist_ok=True)

    # Remove leftovers older than a day
    for file_name in os.listdir(TURN_DIR):
        file_path = os.path.join(TURN_DIR, file_name)

        # Only stale files go
        if time.time() - os.path.getmtime(file_path) > STALE_SECONDS:
            os.remove(file_path)
    with open(turn_path(session_id), "w", encoding="utf-8") as turn_file:
        turn_file.write(str(time.time()))

# Seconds since the session's turn started (None if unknown), forgetting the start time
def take_elapsed(session_id):
    path = turn_path(session_id)

    # No start time means the turn began before the hook was set up
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as turn_file:
        started = float(turn_file.read().strip())
    os.remove(path)
    return time.time() - started

# React to one hook event from Claude Code
def handle(event):
    session_id = str(event.get("session_id", ""))
    event_name = event.get("hook_event_name")

    # Start the clock on a new prompt; on stop, announce if the turn was long enough
    if event_name == "UserPromptSubmit":
        record_start(session_id)
    elif event_name == "Stop":
        elapsed = take_elapsed(session_id)
        settings = load_config()
        min_seconds = float(settings.get("claude_min_minutes", 1)) * 60

        # Quick replies you were watching don't need an announcement
        if elapsed is not None and elapsed >= min_seconds:
            project = spoken_project(event.get("cwd") or os.getcwd(), settings)
            message = f"Claude finished in {project} after {spoken_duration(elapsed)}."
            post_to_nestor("/alert", {"text": message, "source": "claude"}, timeout=3)

# Read the event from standard input and handle it, swallowing every error
def main():
    # Whatever goes wrong (Nestor not running, bad input), the hook stays silent and succeeds
    try:
        handle(json.load(sys.stdin))
    except Exception:
        pass
    sys.exit(0)

# Run only when started by Claude Code
if __name__ == "__main__":
    main()
