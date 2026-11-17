# Reads and writes Nestor's saved state as JSON files in data/, safely: a write never leaves a half-written file,
# and a damaged file is reported and treated as empty rather than stopping Nestor
import json
import logging
import os
log = logging.getLogger(__name__)

# Read a JSON file, or return the default if it is missing or damaged
def read_json(path, default):
    # A missing file just means nothing saved yet
    if not os.path.exists(path):
        return default

    # A damaged file is reported and ignored
    try:
        with open(path, encoding="utf-8") as json_file:
            return json.load(json_file)
    except (OSError, ValueError) as error:
        log.warning("Ignoring unreadable %s: %s", os.path.basename(path), error)
        return default

# Write a JSON file: first to a temporary file, then swapped in, so readers never see half a file
def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary_path = path + ".tmp"
    with open(temporary_path, "w", encoding="utf-8") as json_file:
        json.dump(data, json_file, indent=1)
    os.replace(temporary_path, path)
