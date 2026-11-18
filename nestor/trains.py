# NJ Transit trains from the RailData API (the same developer account as Datebook): signs in and reuses its token
# (NJ Transit allows only 5 new tokens a day), reads a station's live departure board, and picks the next trains
# that stop at your destination
import datetime
import json
import logging
import os
import urllib.error
import urllib.request
import uuid
from nestor.config import DATA_DIR
from nestor.storage import read_json
from nestor.storage import write_json
RAIL_DATA_URL = "https://raildata.njtransit.com/api/TrainData/"
TOKEN_PATH = os.path.join(DATA_DIR, "njt_token.json")
STATIONS_PATH = os.path.join(DATA_DIR, "njt_stations.json")
STATIONS_DAYS = 30  # The station list is fetched again after this many days
TIMEOUT_SECONDS = 15
BOARD_TIME = "%d-%b-%Y %I:%M:%S %p"  # Like "13-Nov-2037 05:12:00 PM", in New Jersey time
log = logging.getLogger(__name__)

# Read a RailData time like "13-Nov-2037 05:12:00 PM" (None when missing or unreadable)
def board_time(text):
    # Missing or odd times stay unknown
    try:
        return datetime.datetime.strptime(str(text).strip(), BOARD_TIME)
    except ValueError:
        return None

# Read one station's departure board: a list of trains (dicts with id, line, destination, departs, track,
# minutes_late, status and stops, each stop a dict with code, name and time)
def parse_board(reply):
    trains = []

    # Each train on the board
    for item in json.loads(reply).get("ITEMS") or []:
        stops = [{"code": str(stop.get("STATION_2CHAR") or "").strip(), "name": str(stop.get("STATIONNAME") or ""),
                  "time": board_time(stop.get("DEP_TIME")) or board_time(stop.get("TIME"))}
                 for stop in item.get("STOPS") or []]
        seconds_late = str(item.get("SEC_LATE") or "0").strip()
        trains.append({"id": str(item.get("TRAIN_ID") or "").strip(), "line": str(item.get("LINE") or "").strip(),
                       "destination": str(item.get("DESTINATION") or "").strip(),
                       "departs": board_time(item.get("SCHED_DEP_DATE")), "track": str(item.get("TRACK") or "").strip(),
                       "minutes_late": round(int(seconds_late) / 60) if seconds_late.lstrip("-").isdigit() else 0,
                       "status": str(item.get("STATUS") or "").strip(), "stops": stops})
    return trains

# When a train reaches a station (by its two-letter code) after leaving, or None if it doesn't stop there
def arrival_at(train, code):
    # Look through the train's stops for that station
    for stop in train["stops"]:
        # Only a stop after the train has left counts
        if stop["code"] == code and stop["time"] and (not train["departs"] or stop["time"] > train["departs"]):
            return stop["time"]
    return None

# The next trains on a board that stop at the destination (cancelled ones included, so they can be mentioned)
def trains_to(board, to_code, count=3):
    return [train for train in board if arrival_at(train, to_code)][:count]

# One train said aloud: "8:12 PM from track 2, on time" or "8:35 PM, 5 minutes late" or "8:48 PM, cancelled"
def spoken_train(train, spoken_clock):
    words = spoken_clock(train["departs"].time()) if train["departs"] else "a train with no time yet"
    track = f" from track {train['track']}" if train["track"] else ""

    # A cancelled train says so; otherwise its track and whether it's late
    if "cancel" in train["status"].lower():
        return f"{words}, cancelled"
    elif train["minutes_late"] > 0:
        return f"{words}{track}, {train['minutes_late']} minutes late"
    elif train["status"].lower() == "on time":
        return f"{words}{track}, on time"
    else:
        return f"{words}{track}"

# Find a station's two-letter code from its code or (part of) its name, e.g. "NY", "New York", "new brunswick"
def find_station(stations, wanted):
    wanted = str(wanted).strip().lower()
    exact = [code for code, name in stations.items() if wanted in (code.lower(), name.lower())]
    partial = [code for code, name in stations.items() if wanted and wanted in name.lower()]

    # An exact code or name wins; otherwise the shortest name containing the words ("new york" is New York Penn)
    if exact:
        return exact[0]
    return min(partial, key=lambda code: len(stations[code])) if partial else None

# Send a RailData request as a multipart form; returns the reply's text, or raises with NJ Transit's reason
def post(method, fields):
    boundary = f"nestor-{uuid.uuid4().hex}"
    parts = "".join(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
                    for name, value in fields.items())
    request = urllib.request.Request(RAIL_DATA_URL + method, data=(parts + f"--{boundary}--\r\n").encode("utf-8"),
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                                              "Accept": "text/plain"})

    # A refusal comes back as an HTTP error whose body explains it
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"NJ Transit {method} failed: {error.read().decode('utf-8', 'replace')[:200]}")

# Talks to RailData with the developer account from .env (NJT_USERNAME and NJT_PASSWORD)
class RailData:
    # Keep the account details
    def __init__(self, username, password):
        self.username = username
        self.password = password

    # Call a RailData method with the saved token, getting a new token once if the saved one was refused
    def call(self, method, fields):
        token = read_json(TOKEN_PATH, {}).get("token") or self.new_token()
        reply = post(method, dict(fields, token=token))

        # A token NJ Transit no longer accepts gets replaced, once
        if "invalid token" in reply.lower():
            reply = post(method, dict(fields, token=self.new_token()))
        return reply

    # Sign in and save the new token (NJ Transit allows only 5 of these a day)
    def new_token(self):
        # Without an account there's nothing to sign in with
        if not self.username or not self.password:
            raise RuntimeError("no NJ Transit account: add NJT_USERNAME and NJT_PASSWORD to .env")
        token = json.loads(post("getToken", {"username": self.username, "password": self.password})).get("UserToken")

        # A sign-in without a token means the account was refused
        if not token:
            raise RuntimeError("NJ Transit didn't accept the account in .env")
        write_json(TOKEN_PATH, {"token": token, "saved": datetime.datetime.now().isoformat(timespec="seconds")})
        log.info("Got a new NJ Transit token")
        return token

    # The station codes and names ({"NB": "New Brunswick", ...}), saved for a month
    def stations(self, now=None):
        now = now or datetime.datetime.now()
        saved = read_json(STATIONS_PATH, {})

        # Use the saved list while it's fresh
        if saved.get("stations") and now - datetime.datetime.fromisoformat(saved["saved"]) < datetime.timedelta(
                days=STATIONS_DAYS):
            return saved["stations"]
        stations = {str(station.get("STATION_2CHAR")).strip(): str(station.get("STATIONNAME")).strip()
                    for station in json.loads(self.call("getStationList", {}))}
        write_json(STATIONS_PATH, {"stations": stations, "saved": now.isoformat(timespec="seconds")})
        return stations

    # A station's live departure board (see parse_board)
    def departures(self, station_code):
        return parse_board(self.call("getTrainSchedule", {"station": station_code}))
