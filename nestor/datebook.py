# Nestor's side of the link with the Datebook phone app: pairing, the snapshot Datebook sends (waiting plans, lists,
# notes, reminders and the train trip), and the queue of actions from the wall display and John for the phone to do
import datetime
import hashlib
import hmac
import logging
import os
import re
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
HOME_MINUTES = 5  # The phone counts as home if it called Nestor this recently (its waiting request repeats every ~50 s)
ACTIONS = ("add", "ignore", "done", "new_plan")
SNAPSHOT_PARTS = ("waiting", "lists", "notes", "reminders", "trip", "events", "fencing")
EVENT_FIELDS = ("id", "title", "start", "end", "all_day", "place", "calendar", "from", "bring", "confirmation",
                "track_url", "leave_by", "travel")
# A Canvas title from Datebook: the assignment, " · ", then the course code (school:subject:course:section) and its
# registrar name, e.g. "Final Group Presentation · 01:713:202:01 INTRO ORGANIZ LDRSHP"
COURSE = re.compile(r"^(.*?)\s*·\s*(\d{2}:\d{3}:\d{3})(?::[\d&]+)?\s+(.+?)\s*$")
CODE = re.compile(r"\d{2}:\d{3}:\d{3}")  # A course code key in class_names
log = logging.getLogger(__name__)
last_seen = None  # When a paired phone last called Nestor
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

# Pair a phone (or a computer, e.g. the PC's Claude connector) with the code from new_pairing_code; returns
# (token, None), or (None, why it failed)
def pair(code, device_name, now=None, kind="phone"):
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
        devices.append({"name": str(device_name or kind)[:60], "token": fingerprint(token),
                        "paired": now.isoformat(timespec="seconds"), "kind": "computer" if kind == "computer" else
                        "phone"})
        write_json(PAIRED_PATH, devices)
        os.remove(PAIRING_PATH)
    log.info("Paired with %s", device_name or "a phone")
    return token, None

# True if the token belongs to a paired phone or computer; a phone's match also notes that the phone is home right now
def check_token(token, now=None):
    global last_seen

    # Without a token there's nothing to match
    if not token:
        return False
    token_print = fingerprint(token)
    matches = [device for device in read_json(PAIRED_PATH, []) if hmac.compare_digest(device["token"], token_print)]

    # A paired phone calling in means it's on the home Wi-Fi (a computer calling in says nothing about the phone)
    if any(device.get("kind", "phone") == "phone" for device in matches):
        last_seen = now or datetime.datetime.now()
    return bool(matches)

# True if a paired phone has called Nestor in the last few minutes, i.e. it's on the home Wi-Fi
def phone_home(now=None):
    now = now or datetime.datetime.now()
    return last_seen is not None and now - last_seen <= datetime.timedelta(minutes=HOME_MINUTES)

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
    state["phone_home"] = phone_home(now)
    state["has_calendar"] = isinstance(state.get("events"), list)  # An older Datebook sends no calendar at all

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

# A title said aloud: "Unit #11 Homework (Project #10) – Replacing an Area" becomes "Unit 11 Homework, Project 10,
# Replacing an Area" (no #, *, brackets or dashes)
def tidy_title(title):
    text = re.sub(r"[#*]", "", str(title))
    text = re.sub(r"\s*[–—]\s*|\s+-\s+", ", ", text)
    text = re.sub(r"\s*\(([^)]*)\)\s*", r", \1, ", text)
    return re.sub(r"\s*,[\s,]*", ", ", " ".join(text.split())).strip(" ,")

# A class's registrar name made sayable when it has no nickname: "MOVIE VFX ONLINE" becomes "Movie VFX"
def tidy_class(name):
    words = [word for word in str(name).split() if word.upper() not in ("ONLINE", "HYBRID", "REMOTE")]
    return " ".join(word.capitalize() if len(word) > 3 else word for word in words)

# A registrar name made comparable: lower case, without "ONLINE" and the like
def class_key(name):
    return " ".join(word for word in str(name).lower().split() if word not in ("online", "hybrid", "remote"))

# Nicknames by registrar name ({"intermed macro anals": "Macro"}), so a calendar event titled with just the class's
# registrar name can be said by its nickname: from class_names entries keyed by registrar name, and from the course
# codes and names Datebook's assignments carry
def class_lookup(state, class_names=None):
    class_names = class_names or {}
    lookup = {class_key(key): nickname for key, nickname in class_names.items() if not CODE.fullmatch(str(key))}
    assignments = state.get("lists", {}).get("assignments") if isinstance(state.get("lists"), dict) else None

    # Each assignment's course code and registrar name
    for item in assignments or []:
        match = COURSE.match(str(item.get("title", ""))) if isinstance(item, dict) else None

        # Only Canvas assignments name a class
        if match:
            lookup.setdefault(class_key(match.group(3)), class_names.get(match.group(2)) or tidy_class(match.group(3)))
    return lookup

# Split a Canvas title from Datebook into what to say and the class's nickname: "Unit #11 Homework – Replacing an
# Area · 07:211:250:90 MOVIE VFX ONLINE" gives ("Unit 11 Homework, Replacing an Area", "Movie VFX"). class_names maps
# course codes ("07:211:250") to nicknames; lookup (from class_lookup) turns a title that is just a registrar name
# into the nickname. Other titles come back tidied, with no class.
def split_class(title, class_names=None, lookup=None):
    match = COURSE.match(str(title))

    # A Canvas title, a class's registrar name, or anything else
    if match:
        return tidy_title(match.group(1)), (class_names or {}).get(match.group(2)) or tidy_class(match.group(3))
    elif class_key(title) in (lookup or {}):
        return lookup[class_key(title)], ""
    else:
        return tidy_title(title), ""

# A copy of a snapshot item (an assignment, event or plan) with what to say: title_spoken and class
def with_spoken_title(item, class_names=None, lookup=None):
    title_spoken, class_name = split_class(item.get("title", ""), class_names, lookup)
    return dict(item, title_spoken=title_spoken, **{"class": class_name})

# A calendar event from the snapshot with every field present (empty when Datebook didn't send it) and its start and
# end read as date-times; None if it has no title or readable start
def clean_event(event):
    # Only events with a title and a start are any use
    if not isinstance(event, dict) or not event.get("title") or not read_moment(event.get("start")):
        return None
    cleaned = {field: event.get(field) or ("" if field != "all_day" else False) for field in EVENT_FIELDS}
    cleaned["all_day"] = bool(event.get("all_day")) or "T" not in str(event["start"])
    cleaned["begins"] = read_moment(event["start"])
    cleaned["ends"] = read_moment(event.get("end")) or cleaned["begins"]
    return cleaned

# The calendar events that happen on a day (all-day ones first, then by start time); an all-day event that runs for
# several days counts on each of them
def events_on(state, day):
    found = []

    # Keep the events that touch the day
    for event in state.get("events") or []:
        cleaned = clean_event(event)

        # Skip unreadable events
        if not cleaned:
            continue
        first_day = cleaned["begins"].date()
        last_day = max(cleaned["ends"].date(), first_day)

        # All-day events end at midnight after their last day, so that day doesn't count
        if cleaned["all_day"] and cleaned["ends"].date() > first_day and cleaned["ends"].time() == datetime.time(0):
            last_day = cleaned["ends"].date() - datetime.timedelta(days=1)

        # Only events running on the day
        if first_day <= day <= last_day:
            found.append(cleaned)
    return sorted(found, key=lambda event: (not event["all_day"], event["begins"]))

# What Datebook says about one day, for the briefing: calendar events that day, waiting plans (all of them, soonest
# first), bills and assignments due that day, and Datebook's reminders that day. Events, plans and due items carry
# title_spoken and class (from class_names, the nicknames for course codes).
def datebook_day(day, now=None, class_names=None):
    state = read_state(now)
    lists = state["lists"] if isinstance(state["lists"], dict) else {}
    lookup = class_lookup(state, class_names)
    waiting = [with_spoken_title(plan, class_names, lookup) for plan in state["waiting"]
               if isinstance(plan, dict) and plan.get("title")]
    waiting.sort(key=lambda plan: str(plan.get("start") or "9999"))
    due = []

    # Bills, then assignments, due that day
    for kind in ("bills", "assignments"):
        # Only items whose due date is the day
        for item in lists.get(kind) or []:
            # Items without a readable due date are skipped
            if isinstance(item, dict) and item.get("title") and str(item.get("due") or "")[:10] == day.isoformat():
                due.append(with_spoken_title({"kind": kind[:-1], "title": item["title"], "due": item["due"]},
                                             class_names, lookup))
    reminders = []

    # Datebook's reminders set for that day ("time" is empty for a reminder with no time of day)
    for reminder in state["reminders"]:
        # Only readable reminders on the day
        if isinstance(reminder, dict) and reminder.get("text") and \
                str(reminder.get("at") or "")[:10] == day.isoformat():
            reminders.append({"time": str(reminder["at"])[11:16], "text": reminder["text"]})
    events = [with_spoken_title({key: value for key, value in event.items() if key not in ("begins", "ends")},
                                class_names, lookup) for event in events_on(state, day)]
    return {"connected": state["connected"], "stale": state["stale"], "updated": state.get("updated"),
            "phone_home": state["phone_home"], "has_calendar": state["has_calendar"], "events": events,
            "waiting": waiting, "due": due,
            "reminders": reminders}
