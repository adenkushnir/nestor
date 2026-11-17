# Nestor's side of the link with the Datebook phone app: pairing, the snapshot Datebook sends (waiting plans, lists,
# notes, reminders and the train trip), and the queue of actions from the wall display and John for the phone to do
import datetime
import hashlib
import hmac
import logging
import os
import secrets
import threading
from nestor.config import DATA_DIR
from nestor.storage import read_json
from nestor.storage import write_json
PAIRING_PATH = os.path.join(DATA_DIR, "pairing.json")
PAIRED_PATH = os.path.join(DATA_DIR, "paired.json")
STATE_PATH = os.path.join(DATA_DIR, "datebook_state.json")
PAIRING_MINUTES = 10
PAIRING_TRIES = 5  # Wrong codes allowed before the code stops working
STALE_HOURS = 24  # A snapshot older than this may be out of date (the phone hasn't been home)
ACTION_MINUTES = 10  # Actions the phone hasn't picked up by then are dropped, so an old tap never pops up later
MAX_WAIT_SECONDS = 55
ACTIONS = ("add", "ignore", "done", "new_plan")
SNAPSHOT_PARTS = ("waiting", "lists", "notes", "reminders", "trip")
log = logging.getLogger(__name__)
pairing_lock = threading.Lock()
state_changed = threading.Condition()
state_version = 0
actions_changed = threading.Condition()
pending_actions = []

# A one-way fingerprint of a code or token, so the real one is never saved
def fingerprint(secret):
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()

# Make a new 6-digit pairing code, valid for 10 minutes, and return it
def new_pairing_code(now=None):
    now = now or datetime.datetime.now()
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = now + datetime.timedelta(minutes=PAIRING_MINUTES)
    write_json(PAIRING_PATH, {"code": fingerprint(code), "expires": expires.isoformat(timespec="seconds"), "tries": 0})
    return code

# Pair a phone with the code from new_pairing_code; returns (token, None), or (None, why it failed)
def pair(code, device_name, now=None):
    now = now or datetime.datetime.now()

    # One pairing at a time, so the tries count can't be raced
    with pairing_lock:
        pairing = read_json(PAIRING_PATH, None)

        # The code must exist, be fresh, not be used up, and match
        if not pairing:
            return None, "no pairing code; run python -m nestor --pair"
        elif datetime.datetime.fromisoformat(pairing["expires"]) <= now or pairing["tries"] >= PAIRING_TRIES:
            os.remove(PAIRING_PATH)
            return None, "the pairing code has run out; run python -m nestor --pair again"
        elif not hmac.compare_digest(pairing["code"], fingerprint(str(code).strip().replace(" ", ""))):
            pairing["tries"] += 1
            write_json(PAIRING_PATH, pairing)
            return None, "wrong pairing code"
        token = secrets.token_urlsafe(32)
        devices = read_json(PAIRED_PATH, [])
        devices.append({"name": str(device_name or "phone")[:60], "token": fingerprint(token),
                        "paired": now.isoformat(timespec="seconds")})
        write_json(PAIRED_PATH, devices)
        os.remove(PAIRING_PATH)
    log.info("Paired with %s", device_name or "a phone")
    return token, None

# True if the token belongs to a paired phone
def check_token(token):
    # Without a token there's nothing to match
    if not token:
        return False
    token_print = fingerprint(token)
    return any(hmac.compare_digest(device["token"], token_print) for device in read_json(PAIRED_PATH, []))

# Forget the phone with this token; returns True if it was paired
def unpair(token):
    # One change to the paired list at a time
    with pairing_lock:
        devices = read_json(PAIRED_PATH, [])
        remaining = [device for device in devices if not hmac.compare_digest(device["token"], fingerprint(token))]
        write_json(PAIRED_PATH, remaining)
    return len(remaining) < len(devices)

# The latest snapshot from Datebook, with when it arrived and whether it's stale (empty parts when nothing has come)
def read_state(now=None):
    now = now or datetime.datetime.now()
    state = read_json(STATE_PATH, {})
    updated = state.get("updated")
    state["connected"] = bool(updated)
    age = now - datetime.datetime.fromisoformat(updated) if updated else None
    state["stale"] = age is None or age > datetime.timedelta(hours=STALE_HOURS)

    # Missing parts read as empty, so readers don't have to check
    for part in SNAPSHOT_PARTS:
        state.setdefault(part, {} if part in ("lists", "trip") else [])
    return state

# Save a new snapshot from Datebook (it replaces the last one) and wake everyone waiting for a change
def save_state(snapshot, now=None):
    global state_version
    now = now or datetime.datetime.now()
    state = {part: snapshot.get(part) for part in SNAPSHOT_PARTS if part in snapshot}
    state["updated"] = now.isoformat(timespec="seconds")

    # Tell the wall display's live feeds about the change
    with state_changed:
        write_json(STATE_PATH, state)
        state_version += 1
        state_changed.notify_all()

# Wait up to timeout seconds for a snapshot newer than version; returns (latest version, state or None if none came)
def next_state(version, timeout):
    # Sleep until the version moves on or the time is up
    with state_changed:
        # Only wait if nothing newer is here already
        if state_version == version:
            state_changed.wait(timeout)

        # Nothing new means nothing to send
        if state_version == version:
            return version, None
        return state_version, read_state()

# Check an action from the wall display or John and queue it for the phone; raises ValueError if it's not valid
def add_action(action, item_id=None, text=None, now=None):
    now = now or datetime.datetime.now()

    # Each action needs what it acts on: a plan or follow-up id, or the words of a new plan
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {', '.join(ACTIONS)}")
    elif action == "new_plan" and not str(text or "").strip():
        raise ValueError("new_plan needs the plan's text")
    elif action != "new_plan" and item_id in (None, ""):
        raise ValueError(f"{action} needs the id of what it acts on")
    queued = {"id": secrets.token_hex(6), "action": action, "time": now.isoformat(timespec="seconds")}

    # Keep only what the action needs
    if action == "new_plan":
        queued["text"] = str(text).strip()[:1000]
    else:
        queued["item"] = item_id

    # Add it and wake the phone's waiting request
    with actions_changed:
        pending_actions.append(queued)
        actions_changed.notify_all()
    return queued

# Hand the phone every waiting action, waiting up to wait_seconds for one to arrive; actions older than 10 minutes
# are dropped instead
def take_actions(wait_seconds, now=None):
    # Wait for an action unless some are waiting already
    with actions_changed:
        # Long-poll: hold the phone's request open until something arrives or the time is up
        if not pending_actions:
            actions_changed.wait(max(0, min(wait_seconds, MAX_WAIT_SECONDS)))
        now = now or datetime.datetime.now()
        oldest = (now - datetime.timedelta(minutes=ACTION_MINUTES)).isoformat(timespec="seconds")
        taken = [action for action in pending_actions if action["time"] >= oldest]
        pending_actions.clear()
    return taken

# Read an ISO date or date-time from Datebook ("2026-11-20" or "2026-11-20T19:00"); None if it isn't one
def read_moment(text):
    # Bad or missing values are skipped rather than stopping the briefing
    try:
        return datetime.datetime.fromisoformat(str(text)[:19])
    except ValueError:
        return None

# What Datebook says about one day, for the briefing: waiting plans (all of them, soonest first), bills and
# assignments due that day, and Datebook's reminders that day
def datebook_day(day, now=None):
    state = read_state(now)
    lists = state["lists"] if isinstance(state["lists"], dict) else {}
    waiting = [plan for plan in state["waiting"] if isinstance(plan, dict) and plan.get("title")]
    waiting.sort(key=lambda plan: str(plan.get("start") or "9999"))
    due = []

    # Bills, then assignments, due that day
    for kind in ("bills", "assignments"):
        # Only items whose due date is the day
        for item in lists.get(kind) or []:
            # Items without a readable due date are skipped
            if isinstance(item, dict) and item.get("title") and str(item.get("due") or "")[:10] == day.isoformat():
                due.append({"kind": kind[:-1], "title": item["title"], "due": item["due"]})
    reminders = []

    # Datebook's reminders set for that day ("time" is empty for a reminder with no time of day)
    for reminder in state["reminders"]:
        # Only readable reminders on the day
        if isinstance(reminder, dict) and reminder.get("text") and str(reminder.get("at") or "")[:10] == day.isoformat():
            reminders.append({"time": str(reminder["at"])[11:16], "text": reminder["text"]})
    return {"connected": state["connected"], "stale": state["stale"], "updated": state.get("updated"),
            "waiting": waiting, "due": due, "reminders": reminders}
