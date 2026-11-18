# John's memory: lasting facts Aden asks him to remember ("my locker code is 4412"), kept in data/memory.json
import datetime
import os
import threading
from nestor.config import DATA_DIR
from nestor.storage import read_json
from nestor.storage import write_json
MEMORY_PATH = os.path.join(DATA_DIR, "memory.json")
MAX_FACTS = 200
memory_lock = threading.Lock()

# All remembered facts, oldest first: dicts with fact and saved
def read_memory():
    return read_json(MEMORY_PATH, [])

# Remember a fact (a repeat of one already known isn't saved twice); returns the fact as saved
def remember(fact, now=None):
    now = now or datetime.datetime.now()
    fact = " ".join(str(fact).split())[:300]

    # One change to the memory file at a time
    with memory_lock:
        facts = read_memory()

        # Only new facts are added
        if fact and fact.lower() not in (known["fact"].lower() for known in facts):
            facts.append({"fact": fact, "saved": now.isoformat(timespec="seconds")})
            write_json(MEMORY_PATH, facts[-MAX_FACTS:])
    return fact

# Forget every fact that contains the given words; returns the facts that were forgotten
def forget(about):
    about = str(about).strip().lower()

    # One change to the memory file at a time
    with memory_lock:
        facts = read_memory()
        forgotten = [known["fact"] for known in facts if about and about in known["fact"].lower()]

        # Only rewrite the file when something was forgotten
        if forgotten:
            write_json(MEMORY_PATH, [known for known in facts if known["fact"] not in forgotten])
    return forgotten
