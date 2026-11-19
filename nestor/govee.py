# Govee lights over the home Wi-Fi (Govee's LAN API; "LAN Control" is switched on for each light in the Govee Home
# app): finds them, sets power, brightness and colour, plays Nestor-made moods (colours with an effect like breathing
# or candle flicker; each group of lights can play its own, and a group changed in another app leaves its mood), and
# shows signals (an alert flash, a leave-by pulse, John's glow, the sunrise and goodnight fades), going back
# afterwards to what was on
import json
import logging
import math
import os
import random
import socket
import threading
import time
from collections import deque
from nestor.config import DATA_DIR
from nestor.storage import read_json
from nestor.storage import write_json
SCAN_ADDRESS = ("239.255.255.250", 4001)  # Where lights listen for "who's there?"
REPLY_PORT = 4002  # Where lights answer
COMMAND_PORT = 4003  # Where each light takes commands
DEVICES_PATH = os.path.join(DATA_DIR, "govee_devices.json")
MOODS_PATH = os.path.join(DATA_DIR, "moods.json")
SCAN_EVERY_SECONDS = 600
FRAME_SECONDS = 0.25  # How often an animated mood changes (a few messages a second per light)
STATUS_WAIT_SECONDS = 0.8  # How long to wait for the lights to say what they're showing
EFFECTS = ("steady", "breathe", "drift", "flicker", "lightning", "party")
SPEEDS = {"slow": 2.0, "medium": 1.0, "fast": 0.5}  # Each effect's period is multiplied by this
NAMED_COLORS = {"red": (255, 0, 0), "orange": (255, 110, 0), "amber": (255, 150, 0), "gold": (255, 190, 40),
                "yellow": (255, 225, 0), "lime": (150, 255, 0), "green": (0, 220, 60), "teal": (0, 180, 160),
                "aqua": (14, 160, 210), "cyan": (0, 220, 255), "blue": (0, 60, 255), "indigo": (75, 0, 255),
                "purple": (140, 40, 255), "violet": (170, 90, 255), "pink": (255, 70, 170), "magenta": (255, 0, 200),
                "white": (255, 255, 255), "warm white": (255, 166, 87), "cool white": (220, 235, 255)}
ALERT_COLOR = (255, 255, 255)
LEAVE_BY_COLOR = (255, 150, 0)  # Amber
LEAVE_NOW_COLOR = (255, 0, 0)
JOHN_COLOR = (14, 134, 196)  # Datebook's aqua
SUNRISE_SECONDS = 120
GOODNIGHT_SECONDS = 60
ALL_LIGHTS_WORDS = ("all", "everything", "every", "all of", "all of them", "both", "both of", "both of them")
CHECK_SECONDS = 1.5  # How often lights in a mood are checked for changes made in another app
CHANGE_STRIKES = 2  # Checks in a row a light must show something else before it counts as changed elsewhere
RECENT_SECONDS = 4  # Frames sent this recently count as Nestor's when checking
HISTORY_FRAMES = 60
COLOR_SLACK = 3  # How far a reported colour part may be from what was sent (lights round a little)
BRIGHTNESS_SLACK = 2
lights = None  # The running GoveeLights, for John, the announcer and the routines
log = logging.getLogger(__name__)

# A light or group name made comparable: "The Living Room Lights" and "living room" are the same
def group_key(name):
    words = [word for word in str(name).lower().replace("-", " ").split() if word not in ("the", "light", "lights",
                                                                                          "lamp", "lamps", "my")]
    return " ".join(words)

# A light's status said simply for the log: "#ff8800 at 40%", "white 2700 K at 40%" or "off"
def describe_status(status):
    color = status.get("color") or {}
    kelvin = status.get("colorTemInKelvin") or 0
    level = status.get("brightness")

    # Off, white, or a colour
    if not status.get("onOff"):
        return "off"
    elif kelvin:
        return f"white {kelvin} K at {level}%"
    else:
        return "#{:02x}{:02x}{:02x}".format(*(int(color.get(part, 0)) for part in "rgb")) + f" at {level}%"

# Read a colour said or written as a name ("purple"), a hex code ("#ff8800") or "r,g,b"; None if it isn't one
def parse_color(text):
    text = str(text).strip().lower()
    hex_digits = text.lstrip("#")

    # A name, a hex code, three numbers, or nothing
    if text in NAMED_COLORS:
        return NAMED_COLORS[text]
    elif len(hex_digits) == 6 and all(digit in "0123456789abcdef" for digit in hex_digits):
        return tuple(int(hex_digits[i:i + 2], 16) for i in (0, 2, 4))
    elif text.count(",") == 2 and all(part.strip().isdigit() for part in text.split(",")):
        return tuple(min(255, int(part)) for part in text.split(","))
    return None

# The colour a share of the way from one colour to another (share 0 to 1)
def mix(first, second, share):
    return tuple(round(a + (b - a) * share) for a, b in zip(first, second))

# Roughly the colour of white light at a colour temperature (2000 K candle to 6500 K daylight), for lights that
# only take colours
def kelvin_color(kelvin):
    share = max(0.0, min(1.0, (kelvin - 2000) / 4500))
    return mix((255, 137, 14), (255, 249, 253), share)

# One frame of a mood for one light: (colour, brightness 1 to 100). t is seconds since the mood started, place is the
# light's position (so lights can differ), and flash says a lightning flash is happening now.
def mood_frame(mood, t, place, flash=False):
    colors = [color for color in (parse_color(text) for text in mood["colors"]) if color] or [NAMED_COLORS["white"]]
    brightness = max(1, min(100, int(mood.get("brightness", 70))))
    period = SPEEDS.get(mood.get("speed"), 1.0)
    effect = mood.get("effect", "steady")

    # Each effect's colour and brightness at this moment
    if effect == "breathe":
        wave = 0.5 - 0.5 * math.cos(2 * math.pi * t / (6 * period))
        return colors[int(t / (6 * period)) % len(colors)], max(1, round(brightness * (0.3 + 0.7 * wave)))
    elif effect == "drift":
        position = t / (8 * period) + place * 0.5
        share = position % 1
        smooth = share * share * (3 - 2 * share)
        return mix(colors[int(position) % len(colors)], colors[(int(position) + 1) % len(colors)], smooth), brightness
    elif effect == "flicker":
        return colors[random.randrange(len(colors))], max(1, round(brightness * random.uniform(0.55, 1.0)))
    elif effect == "lightning":
        return (NAMED_COLORS["white"], 100) if flash else (colors[0], max(1, round(brightness * 0.3)))
    elif effect == "party":
        return colors[(int(t / (1.2 * period)) + place) % len(colors)], brightness
    else:
        return colors[0], brightness

# The lights: commands, moods (each group of lights can play its own) and signals. Everything does nothing if no
# lights are found.
class GoveeLights:
    # Open the reply port, find the lights in the background, and start the mood player and the watch for changes made
    # in other apps. groups names sets of lights by their Govee device ids, e.g. {"wall": ["2F:3A:..."], "living room":
    # ["04:DC:...", "04:5B:..."]}; plain_lights is the group plain "lights" means and signal_lights the group alerts
    # and John's glow use ("" for every light).
    def __init__(self, groups=None, plain_lights="", signal_lights=""):
        global lights
        self.devices = read_json(DEVICES_PATH, {})  # IP address: {"sku", "device"}
        self.groups = {group_key(name): set(ids) for name, ids in (groups or {}).items()}
        self.plain_lights = group_key(plain_lights)
        self.signal_lights = group_key(signal_lights)
        self.status = {}  # IP address: what the light last said it shows
        self.status_times = {}
        self.moods = []  # The moods playing, each {"mood", "ips" (its lights), "started", "flash_until"}
        self.moods_lock = threading.RLock()
        self.sent = {}  # IP address: (colour, brightness) last sent by the mood player, to skip repeats
        self.history = {}  # IP address: recent (time, colour, brightness) sent, to tell Nestor's frames from an app's
        self.strikes = {}  # IP address: checks in a row where the light showed something Nestor didn't send
        self.kelvins = {}  # IP address: the white setting it reported while showing Nestor's mood
        self.signalling = set()  # Lights a signal, John's glow or a fade is using right now (moods skip them)
        self.busy = threading.Lock()  # Held while a signal, the glow or a fade plays
        self.glow_stop = threading.Event()
        self.glowing = False
        self.glow_restore = True  # Whether ending the glow puts the lights back (not if something new was set)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(("0.0.0.0", REPLY_PORT))
        lights = self
        threading.Thread(target=self.listen, name="govee-replies", daemon=True).start()
        threading.Thread(target=self.keep_scanning, name="govee-scan", daemon=True).start()
        threading.Thread(target=self.play_moods, name="govee-moods", daemon=True).start()
        threading.Thread(target=self.watch_for_changes, name="govee-watch", daemon=True).start()

    # Send one command to one light
    def send(self, ip, command, data):
        self.socket.sendto(json.dumps({"msg": {"cmd": command, "data": data}}).encode("utf-8"), (ip, COMMAND_PORT))

    # Turn every light (or just the given IP addresses) on or off
    def power(self, on, ips=None):
        # Each light
        for ip in ips if ips is not None else self.devices:
            self.send(ip, "turn", {"value": 1 if on else 0})

    # The IP addresses of the lights a name means: "both", "all" or "everything" for every light, plain "lights" (or
    # nothing) for the plain_lights group, otherwise a group's. Raises ValueError for a name that isn't a group.
    def ips_for(self, name=""):
        key = group_key(name)

        # Every light, plain "lights", a group, or a name Nestor doesn't know
        if key in ALL_LIGHTS_WORDS:
            return set(self.devices)
        elif not key:
            return self.ips_for(self.plain_lights) if self.plain_lights else set(self.devices)
        elif key in self.groups:
            return {ip for ip, info in self.devices.items() if info.get("device") in self.groups[key]}
        else:
            known = ", ".join(sorted(self.groups)) or "just all of them"
            raise ValueError(f"no lights called {name!r}; there's {known}")

    # The lights alerts and John's glow use (every light if that group isn't known)
    def signal_ips(self):
        # An unknown group falls back to every light
        try:
            return self.ips_for(self.signal_lights) if self.signal_lights else set(self.devices)
        except ValueError:
            return set(self.devices)

    # The lights that go together with one light: its group's, or just itself if it's in none
    def group_ips(self, ip):
        device = self.devices.get(ip, {}).get("device")

        # The first group it's in
        for name, ids in self.groups.items():
            # Its group
            if device in ids:
                return self.ips_for(name)
        return {ip}

    # The names of the groups whose lights are all among these
    def group_names(self, ips):
        return sorted(name for name in self.groups if self.ips_for(name) and self.ips_for(name) <= set(ips))

    # Every light playing a mood now
    def mood_ips(self):
        return set().union(*(entry["ips"] for entry in self.moods))

    # The playing mood that covers any of these lights (its entry), or None
    def mood_entry(self, ips):
        matches = [entry for entry in self.moods if entry["ips"] & set(ips)]
        return matches[0] if matches else None

    # The mood playing on the lights a name means; with no name and a single mood playing, that one. Returns its
    # entry, or None.
    def mood_for(self, which=""):
        # No lights named and just one mood: it's the one meant
        if not group_key(which) and len(self.moods) == 1:
            return self.moods[0]
        return self.mood_entry(self.ips_for(which))

    # Take lights out of the moods they're in (a mood left with no lights stops)
    def leave_moods(self, ips):
        ips = set(ips)

        # One change to the moods at a time
        with self.moods_lock:
            self.moods = [dict(entry, ips=entry["ips"] - ips) for entry in self.moods if entry["ips"] - ips]

        # Those lights start fresh next time
        for ip in ips:
            self.sent.pop(ip, None)
            self.strikes.pop(ip, None)
            self.kelvins.pop(ip, None)

    # What the lights are showing now, for Claude: the moods playing (with their groups) and each light's group, mood,
    # power, brightness and colour, read fresh from the lights
    def describe(self):
        captured = self.capture()
        described = []

        # Each light, by its group
        for ip, info in sorted(self.devices.items()):
            status = captured.get(ip)
            groups = [name for name, ids in self.groups.items() if info.get("device") in ids]
            entry = self.mood_entry({ip})
            light = {"group": groups[0] if groups else "", "model": info.get("sku", ""),
                     "mood": entry["mood"]["name"] if entry else ""}

            # A light that didn't answer is marked so
            if not status:
                light["answered"] = False
            elif not status.get("onOff"):
                light["on"] = False
            else:
                color = status.get("color") or {}
                kelvin = status.get("colorTemInKelvin") or 0
                light.update(on=True, brightness=status.get("brightness"), white_kelvin=kelvin,
                             color="" if kelvin else "#{:02x}{:02x}{:02x}".format(*(color.get(part, 0)
                                                                                    for part in "rgb")))
            described.append(light)
        return {"moods": [{"mood": entry["mood"], "groups": self.group_names(entry["ips"])} for entry in self.moods],
                "lights": described, "plain_lights_means": self.plain_lights or "all",
                "signals_use": self.signal_lights or "all"}

    # Set one light's colour and brightness (white light given as kelvin goes to lights that know it, as a colour
    # to the rest)
    def show(self, ip, color, brightness, kelvin=0):
        self.send(ip, "colorwc", {"color": dict(zip("rgb", color)), "colorTemInKelvin": kelvin})
        self.send(ip, "brightness", {"value": max(1, min(100, round(brightness)))})

    # Read every reply the lights send: answers to "who's there?" and what each one shows
    def listen(self):
        # Runs for the life of the program
        while True:
            # A garbled reply is skipped
            try:
                data, address = self.socket.recvfrom(4096)
                message = json.loads(data).get("msg", {})
            except (OSError, ValueError):
                continue

            # A light saying it's there, or what it shows
            if message.get("cmd") == "scan":
                found = message.get("data", {})
                self.devices[found.get("ip", address[0])] = {"sku": found.get("sku"), "device": found.get("device")}
            elif message.get("cmd") == "devStatus":
                self.status[address[0]] = message.get("data", {})
                self.status_times[address[0]] = time.time()

    # Ask the lights who's there now and then (they can change address), and remember them
    def keep_scanning(self):
        scan = json.dumps({"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}}).encode("utf-8")

        # For the life of the program
        while True:
            known = len(self.devices)

            # A network problem only delays the next scan
            try:
                self.socket.sendto(scan, SCAN_ADDRESS)
                time.sleep(3)
                write_json(DEVICES_PATH, self.devices)

                # Say once how many lights there are
                if len(self.devices) != known or not known:
                    log.info("Govee lights found: %s", ", ".join(f"{info['sku']} at {ip}" for ip, info in
                                                                 sorted(self.devices.items())) or "none")
            except OSError as error:
                log.warning("Couldn't look for Govee lights: %s", error)
            time.sleep(SCAN_EVERY_SECONDS)

    # What some lights (every light unless given) show right now, asked fresh, as {IP address: status}
    def capture(self, ips=None):
        ips = set(self.devices) if ips is None else set(ips)
        asked = time.time()

        # Ask each light
        for ip in ips:
            self.send(ip, "devStatus", {})
        gives_up = asked + STATUS_WAIT_SECONDS

        # Wait until they've all answered, or a moment has passed
        while time.time() < gives_up and any(self.status_times.get(ip, 0) < asked for ip in ips):
            time.sleep(0.05)
        return {ip: dict(self.status[ip]) for ip in ips if self.status_times.get(ip, 0) >= asked}

    # Put the lights back the way capture() found them
    def restore(self, captured):
        # Each light that answered
        for ip, status in captured.items():
            color = tuple(status.get("color", {}).get(part, 255) for part in "rgb")

            # Off stays off; on gets its colour (or white) and brightness back
            if not status.get("onOff"):
                self.send(ip, "turn", {"value": 0})
            else:
                self.send(ip, "turn", {"value": 1})
                self.show(ip, color, status.get("brightness", 100), status.get("colorTemInKelvin", 0))

    # Background loop: show each mood's next frame on its own lights (lights a signal is using sit it out)
    def play_moods(self):
        # For the life of the program
        while True:
            time.sleep(FRAME_SECONDS)
            now = time.time()

            # Each mood playing
            for entry in list(self.moods):
                mood = entry["mood"]
                speed = SPEEDS.get(mood.get("speed"), 1.0)

                # Lightning strikes now and then
                if mood.get("effect") == "lightning" and now > entry["flash_until"] and random.random() < 0.04 / speed:
                    entry["flash_until"] = now + FRAME_SECONDS * 1.5
                self.show_frame(entry, now - entry["started"], now < entry["flash_until"])

    # Show one frame of a mood on its lights, sending each light only what changed
    def show_frame(self, entry, t, flash=False):
        # Each of its lights, at its own place in the effect
        for place, ip in enumerate(sorted(entry["ips"])):
            color, brightness = mood_frame(entry["mood"], t, place, flash)

            # Only changes are sent, to keep Wi-Fi traffic low; a light a signal is using waits
            if ip not in self.signalling and self.sent.get(ip) != (color, brightness):
                self.show(ip, color, brightness)
                self.sent[ip] = (color, brightness)
                self.history.setdefault(ip, deque(maxlen=HISTORY_FRAMES)).append((time.time(), color, brightness))

    # Start a mood on these lights (they leave any mood they were in; John's glow gives way if it's on them). Returns
    # the mood.
    def start_mood(self, mood, ips):
        ips = set(ips)

        # The glow stops if the mood takes its lights
        if ips & self.signal_ips():
            self.end_glow(restore=False)

        # One change to the moods at a time
        with self.moods_lock:
            self.leave_moods(ips)
            self.power(True, ips)
            entry = {"mood": dict(mood), "ips": ips, "started": time.time(), "flash_until": 0.0}
            self.moods = self.moods + [entry]
        self.show_frame(entry, 0)
        return entry["mood"]

    # Show a mood (a dict with name, colors, effect, speed and brightness) on the lights a name means: plain "lights",
    # "the wall", "both"... Returns the mood.
    def set_mood(self, mood, which=""):
        return self.start_mood(mood, self.ips_for(which))

    # Set lights directly (any of: on or off, a colour, white at a colour temperature, a brightness). which names
    # them like set_mood; they leave any mood while the other lights carry on with theirs.
    def set_lights(self, on=None, color=None, kelvin=0, brightness=0, which=""):
        ips = self.ips_for(which)

        # The glow stops if these are its lights
        if ips & self.signal_ips():
            self.end_glow(restore=False)
        self.leave_moods(ips)

        # Off is just off; anything else turns them on first
        if on is False:
            self.power(False, ips)
            return
        self.power(True, ips)

        # A colour or white, if one was asked for
        if color or kelvin:
            # Each light
            for ip in ips:
                self.send(ip, "colorwc", {"color": dict(zip("rgb", color or kelvin_color(kelvin))),
                                          "colorTemInKelvin": kelvin if not color else 0})

        # A brightness, if one was asked for (otherwise each keeps its own)
        if brightness:
            # Each light
            for ip in ips:
                self.send(ip, "brightness", {"value": max(1, min(100, brightness))})

    # Tweak the mood playing on the lights a name means ("warmer", "slower", "dimmer"): changes holds only what
    # changes; returns the new mood. Raises ValueError if no mood is playing there.
    def adjust_mood(self, changes, which=""):
        entry = self.mood_for(which)

        # Only a playing mood can be tweaked
        if not entry:
            raise ValueError("no mood is showing on those lights to change")
        return self.start_mood(dict(entry["mood"], **changes), entry["ips"])

    # Whether a light's status is something Nestor's mood sent it lately (small rounding allowed). Nothing sent yet
    # counts as a match.
    def matches_sent(self, ip, status):
        sent = list(self.history.get(ip, []))

        # Off is never a mood; with nothing sent there's nothing to compare
        if not status.get("onOff"):
            return False
        elif not sent:
            return True
        recent = [frame for frame in sent if time.time() - frame[0] <= RECENT_SECONDS] + sent[-1:]
        color = tuple(int((status.get("color") or {}).get(part, -99)) for part in "rgb")
        brightness = int(status.get("brightness", -99))
        kelvin = status.get("colorTemInKelvin") or 0
        same_color = any(all(abs(shown - sent_part) <= COLOR_SLACK for shown, sent_part in zip(color, frame[1]))
                         for frame in recent)
        same_brightness = any(abs(brightness - frame[2]) <= BRIGHTNESS_SLACK for frame in recent)
        return same_color and same_brightness and self.kelvins.setdefault(ip, kelvin) == kelvin

    # Background loop: every moment or two, check the lights playing a mood still show what Nestor sent. A light
    # showing something else twice in a row was changed in another app (like Google Home), so its group leaves the
    # mood and keeps what the app set.
    def watch_for_changes(self):
        # For the life of the program
        while True:
            time.sleep(CHECK_SECONDS)
            watched = self.mood_ips() - self.signalling

            # Only lights in a mood that no signal is using
            if not watched:
                continue
            captured = self.capture(watched)

            # Each light that answered
            for ip, status in captured.items():
                # Nestor's own frame resets the count; anything else adds to it
                if self.matches_sent(ip, status):
                    self.strikes[ip] = 0
                else:
                    self.strikes[ip] = self.strikes.get(ip, 0) + 1

                # Twice in a row, and still in a mood: it was changed elsewhere
                if self.strikes.get(ip, 0) >= CHANGE_STRIKES and ip in self.mood_ips():
                    group = self.group_ips(ip)
                    log.info("The %s changed in another app (now %s); %s the mood",
                             " and ".join(self.group_names(group)) or ip, describe_status(status),
                             "it leaves" if len(group) == 1 else "they leave")
                    self.leave_moods(group)

    # Play a short signal on the signal lights, then go back to what was showing (a mood picks up again by itself);
    # skipped if another signal is playing. frames is a list of (colour, brightness, seconds).
    def signal(self, frames):
        ips = self.signal_ips()

        # One signal at a time, and none during John's glow (it already says he's listening)
        if not ips or self.glowing or not self.busy.acquire(blocking=False):
            return

        # Always give the lights back, even if a command fails
        try:
            self.signalling = set(ips)
            captured = self.capture(ips - self.mood_ips())

            # Each step of the signal
            for color, brightness, seconds in frames:
                # Every signal light at once
                for ip in ips:
                    self.show(ip, color, brightness)
                time.sleep(seconds)
            self.restore(captured)
        finally:
            self.hand_back(ips)
            self.busy.release()

    # After a signal: the mood player sends those lights their frame again
    def hand_back(self, ips):
        # Each light the signal used
        for ip in ips:
            self.sent.pop(ip, None)
            self.strikes.pop(ip, None)
        self.signalling = set()

    # Flash for an alert: white for most, an amber pulse for a leave-by, red for "leave now"
    def alert(self, text, source="", key=""):
        # Which signal fits the alert
        if "leave now" in text.lower():
            frames = [(LEAVE_NOW_COLOR, 100, 0.35), ((0, 0, 0), 1, 0.25)] * 3
        elif str(key).startswith("leave_by|"):
            frames = [(LEAVE_BY_COLOR, level, 0.15) for level in (20, 50, 80, 100, 80, 50, 20)] * 2
        else:
            frames = [(ALERT_COLOR, 100, 0.3), (ALERT_COLOR, 15, 0.3)] * 2
        threading.Thread(target=self.signal, args=(frames,), name="govee-alert", daemon=True).start()

    # Glow Datebook's aqua on the signal lights while John listens and thinks, until end_glow()
    def start_glow(self):
        # Only with lights, and not on top of another signal
        if not self.signal_ips() or self.glowing or not self.busy.acquire(blocking=False):
            return
        self.glowing = True
        self.glow_restore = True
        self.glow_stop.clear()
        threading.Thread(target=self.glow, name="govee-glow", daemon=True).start()

    # The glow itself: a gentle aqua breathing until it's told to stop, then the lights go back
    def glow(self):
        ips = self.signal_ips()

        # Always hand the lights back
        try:
            self.signalling = set(ips)
            captured = self.capture(ips - self.mood_ips())
            started = time.time()

            # Breathe until stopped
            while not self.glow_stop.is_set():
                level = 45 + 35 * (0.5 - 0.5 * math.cos(2 * math.pi * (time.time() - started) / 3))

                # Every signal light
                for ip in ips:
                    self.show(ip, JOHN_COLOR, level)
                self.glow_stop.wait(0.4)

            # Go back, unless something new (a mood, a colour) was set on these lights while glowing
            if self.glow_restore:
                self.restore(captured)
        finally:
            self.hand_back(ips)
            self.glowing = False
            self.busy.release()

    # Stop John's glow; restore=False leaves the lights to whatever was just set instead
    def end_glow(self, restore=True):
        self.glow_restore = restore
        self.glow_stop.set()

        # Wait briefly for the glow to hand the lights back
        if self.glowing:
            ends = time.time() + 2
            while self.glowing and time.time() < ends:
                time.sleep(0.05)

    # "Good morning": a 2-minute sunrise on every light, from dim candle orange to bright daylight
    def sunrise(self):
        threading.Thread(target=self.fade, args=("sunrise",), name="govee-sunrise", daemon=True).start()

    # "Goodnight": every light that's on fades down over a minute, then all turn off
    def goodnight(self):
        threading.Thread(target=self.fade, args=("goodnight",), name="govee-goodnight", daemon=True).start()

    # Play the sunrise or goodnight fade on every light (waits for any short signal to finish first; moods stop)
    def fade(self, which):
        # Without lights there's nothing to fade; the fade waits its turn behind a signal
        if not self.devices or not self.busy.acquire(timeout=10):
            return

        # Always hand the lights back
        try:
            self.leave_moods(set(self.devices))
            self.signalling = set(self.devices)
            start = self.capture()

            # Sunrise: candle to daylight while brightening; goodnight: each light dims from where it was, then off
            if which == "sunrise":
                self.power(True)
                steps = SUNRISE_SECONDS // 2

                # One step every 2 seconds, brightening faster at the end like a real sunrise
                for step in range(steps + 1):
                    share = step / steps
                    kelvin = round(2000 + 4500 * share)

                    # Every light
                    for ip in self.devices:
                        self.send(ip, "colorwc", {"color": dict(zip("rgb", kelvin_color(kelvin))),
                                                  "colorTemInKelvin": kelvin})
                        self.send(ip, "brightness", {"value": max(1, round(100 * share ** 1.6))})
                    time.sleep(2)
            else:
                steps = GOODNIGHT_SECONDS // 2

                # One step every 2 seconds down to the dimmest, then off
                for step in range(steps + 1):
                    # Every light that was on
                    for ip, status in start.items():
                        # Lights already off stay off
                        if status.get("onOff"):
                            self.send(ip, "brightness", {"value": max(1, round(status.get("brightness", 100) *
                                                                            (1 - step / steps)))})
                    time.sleep(2)
                self.power(False)
        finally:
            self.hand_back(set(self.devices))
            self.busy.release()

# The saved moods, newest last: dicts with name, colors, effect, speed, brightness and saved
def read_moods():
    return read_json(MOODS_PATH, [])

# Save a mood under a name (replacing one with the same name, and keeping its "asks for colours" setting); returns it
def save_mood(mood, name):
    saved = dict(mood, name=str(name).strip(), saved=time.strftime("%Y-%m-%dT%H:%M:%S"))
    replaced = [old for old in read_moods() if old["name"].lower() == saved["name"].lower()]
    moods = [old for old in read_moods() if old["name"].lower() != saved["name"].lower()]

    # A mood that asked for colours still does after being saved again
    if replaced and replaced[0].get("ask_colors"):
        saved["ask_colors"] = True
    write_json(MOODS_PATH, moods + [saved])
    return saved

# Turn a saved mood's "asks for colours" setting on or off (its saved colours are kept, and only used when it's off);
# returns the mood, or None if there's no such mood
def set_ask_colors(name, ask):
    mood = find_mood(name)

    # Only a saved mood can change
    if not mood:
        return None
    mood["ask_colors"] = bool(ask)
    write_json(MOODS_PATH, [mood if old["name"] == mood["name"] else old for old in read_moods()])
    return mood

# A saved mood by name (case doesn't matter, and part of the name is enough), or None
def find_mood(name):
    wanted = str(name).strip().lower()
    moods = read_moods()
    exact = [mood for mood in moods if mood["name"].lower() == wanted]
    partial = [mood for mood in moods if wanted and wanted in mood["name"].lower()]
    return (exact or partial or [None])[0]

# Delete a saved mood by name; returns True if there was one
def delete_mood(name):
    mood = find_mood(name)

    # Only a saved mood can be deleted
    if not mood:
        return False
    write_json(MOODS_PATH, [old for old in read_moods() if old["name"] != mood["name"]])
    return True
