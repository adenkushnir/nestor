# Spotify on your phone and laptop, controlled by Nestor through Spotify's Web API: signs in once (PKCE, no secret),
# keeps track of what's playing for the wall screen, plays by name, and turns the music down while Nestor speaks
import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from nestor.config import DATA_DIR
from nestor.storage import read_json
from nestor.storage import write_json
API_URL = "https://api.spotify.com/v1"
AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = ("user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private "
          "playlist-read-collaborative")
TOKEN_PATH = os.path.join(DATA_DIR, "spotify_token.json")
DEVICE_PATH = os.path.join(DATA_DIR, "spotify_device.json")
TIMEOUT_SECONDS = 4  # Kept short, as announcements wait for the music to turn down
PLAYING_POLL_SECONDS = 5
IDLE_POLL_SECONDS = 20
KINDS = ("any", "song", "artist", "album", "playlist")
SEARCH_TYPES = {"song": "track", "artist": "artist", "album": "album", "playlist": "playlist"}
DEVICE_WORDS = {"laptop": "computer", "computer": "computer", "pc": "computer", "desktop": "computer",
                "phone": "smartphone", "speaker": "speaker", "tv": "tv"}
log = logging.getLogger(__name__)
music = None  # The running Spotify connection, once the service has made one

# Something Spotify refused, with a reason fit to say out loud
class SpotifyError(Exception):
    pass

# A random PKCE verifier and its challenge (the SHA-256 of the verifier, base64url without padding)
def pkce_pair():
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge

# A successful reply's JSON, or None when it has none: Spotify's player commands sometimes answer with an empty body
# or plain text instead of JSON, even though they worked
def read_reply(content):
    # Plain text from a command that worked counts as no content
    try:
        return json.loads(content) if content.strip() else None
    except ValueError:
        log.debug("Spotify answered with plain text: %r", content[:100])
        return None

# What's playing, from Spotify's player state (None or empty when nothing is): the shape the wall screen reads
def describe_player(state):
    # Nothing playing anywhere
    if not state or not state.get("item"):
        return {"playing": False, "track": "", "artists": [], "album": "", "art": "", "progress_ms": 0,
                "duration_ms": 0, "device": ((state or {}).get("device") or {}).get("name", "")}
    item = state["item"]
    album = item.get("album") or {}
    images = album.get("images") or item.get("images") or []
    return {"playing": bool(state.get("is_playing")), "track": item.get("name", ""),
            "artists": [artist.get("name", "") for artist in item.get("artists") or []], "album": album.get("name", ""),
            "art": images[0]["url"] if images else "", "progress_ms": state.get("progress_ms") or 0,
            "duration_ms": item.get("duration_ms") or 0, "device": (state.get("device") or {}).get("name", "")}

# The best search result for what was asked: an exact name first (your own playlists, then artist, album, playlist),
# otherwise the top song; None if nothing matched. found maps a kind to its list of results.
def best_match(query, found, kind="any"):
    wanted = query.strip().lower()

    # A kind that was asked for takes its top result (an exact name if there is one)
    if kind != "any":
        results = [result for result in found.get(kind) or [] if result]
        exact = [result for result in results if result.get("name", "").lower() == wanted]
        return (exact or results or [None])[0]

    # Otherwise an exact name wins, in this order
    for each_kind in ("own playlist", "artist", "album", "playlist"):
        exact = [result for result in found.get(each_kind) or [] if result and result.get("name", "").lower() == wanted]

        # The first exact name found
        if exact:
            return exact[0]
    songs = [result for result in found.get("song") or [] if result]
    return songs[0] if songs else None

# The device a spoken name means ("laptop", "my phone", or part of its name), from Spotify's device list
def find_device(devices, wanted):
    wanted = wanted.strip().lower().replace("my ", "").replace("the ", "")
    by_type = DEVICE_WORDS.get(wanted)

    # A kind of device or part of its name
    for device in devices:
        # The first one that fits
        if (by_type and device.get("type", "").lower() == by_type) or wanted in device.get("name", "").lower():
            return device
    return None

# A Spotify account connection: the sign-in token, what's playing (checked every few seconds), and the commands
class Spotify:
    # Load the saved sign-in (if any) and start checking what's playing in the background
    def __init__(self, client_id, duck_volume=20):
        global music
        self.client_id = client_id
        self.duck_volume = duck_volume  # How loud (percent) music goes while Nestor speaks, if it was louder
        self.token = read_json(TOKEN_PATH, {})  # {"access_token", "refresh_token", "expires_at"}
        self.pending = {}  # Sign-ins in progress: state: PKCE verifier
        self.state = None  # The last player state Spotify gave
        self.now = describe_player(None)
        self.token_lock = threading.Lock()
        self.duck_lock = threading.Lock()
        self.duck_depth = 0  # How many things (John, announcements) want the music down right now
        self.ducked = None  # How the music was turned down, to undo it: ("volume", device id, volume) or ("paused", id)
        self.wake = threading.Event()  # Set to check what's playing straight away
        threading.Thread(target=self.keep_checking, name="spotify", daemon=True).start()
        music = self
        log.info("Spotify is %s", "signed in" if self.signed_in() else
                 "waiting for a sign-in: open http://127.0.0.1:8765/spotify/login in a browser on this PC")

    # Whether Nestor is signed in to Spotify
    def signed_in(self):
        return bool(self.token.get("refresh_token"))

    # The Spotify sign-in page to open in a browser; it comes back to redirect_uri
    def login_url(self, redirect_uri):
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(16)
        self.pending = {state: verifier}
        return AUTHORIZE_URL + "?" + urllib.parse.urlencode({
            "client_id": self.client_id, "response_type": "code", "redirect_uri": redirect_uri, "scope": SCOPES,
            "state": state, "code_challenge_method": "S256", "code_challenge": challenge})

    # Finish signing in with the code Spotify sent back; raises SpotifyError if it doesn't match a sign-in we started
    def finish_login(self, code, state, redirect_uri):
        verifier = self.pending.pop(state, None)

        # Only a sign-in started here can finish here
        if not verifier:
            raise SpotifyError("that sign-in link is old; open the sign-in page again")
        self.save_token(self.token_request({"grant_type": "authorization_code", "code": code,
                                            "redirect_uri": redirect_uri, "code_verifier": verifier}))
        self.wake.set()

    # Ask Spotify's account service for a token (sign-in or refresh)
    def token_request(self, fields):
        body = urllib.parse.urlencode(dict(fields, client_id=self.client_id)).encode()
        request = urllib.request.Request(TOKEN_URL, data=body, method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})

        # Spotify's reason is passed on when it refuses
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
                return json.loads(reply.read())
        except urllib.error.HTTPError as error:
            raise SpotifyError(f"Spotify refused the sign-in ({error.code}): {error.read()[:200]!r}") from None
        except (urllib.error.URLError, TimeoutError) as error:
            raise SpotifyError(f"couldn't reach Spotify: {error}") from None

    # Keep a new token in data/ (Spotify may send a new refresh token too; otherwise the old one stays)
    def save_token(self, reply):
        self.token = {"access_token": reply["access_token"],
                      "refresh_token": reply.get("refresh_token") or self.token.get("refresh_token"),
                      "expires_at": time.time() + int(reply.get("expires_in", 3600)) - 60}
        write_json(TOKEN_PATH, self.token)

    # A working access token, refreshed when it's about to run out
    def access_token(self):
        with self.token_lock:
            # Not signed in yet
            if not self.signed_in():
                raise SpotifyError("Spotify isn't set up yet: open http://127.0.0.1:8765/spotify/login on the PC")

            # Refresh shortly before it runs out
            if time.time() >= self.token.get("expires_at", 0):
                self.save_token(self.token_request({"grant_type": "refresh_token",
                                                    "refresh_token": self.token["refresh_token"]}))
            return self.token["access_token"]

    # Call the Web API; returns the reply's JSON (None when there's no content). Raises SpotifyError with Spotify's
    # reason, e.g. when no device is playing.
    def api(self, method, path, params=None, body=None, retry=True):
        url = API_URL + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode() if body is not None else (b"" if method in ("PUT", "POST") else None)
        request = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + self.access_token(), "Content-Type": "application/json"})

        # A run-out token is refreshed once; other refusals are explained
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as reply:
                return read_reply(reply.read())
        except urllib.error.HTTPError as error:
            # A token that stopped working is replaced and the call tried again
            if error.code == 401 and retry:
                self.token["expires_at"] = 0
                return self.api(method, path, params, body, retry=False)
            raise SpotifyError(self.reason(error)) from None
        except (urllib.error.URLError, TimeoutError) as error:
            raise SpotifyError(f"couldn't reach Spotify: {error}") from None

    # Spotify's refusal said simply
    def reason(self, error):
        # Spotify's own message, if it sent one
        try:
            message = json.loads(error.read()).get("error", {}).get("message", "")
        except (ValueError, AttributeError):
            message = ""

        # The common ones in plain words
        if error.code == 404:
            return "Spotify isn't open on any device right now; open it on your phone or laptop first"
        elif error.code == 403:
            return f"that device doesn't allow it ({message or 'not allowed'})"
        elif error.code == 429:
            return "Spotify asked Nestor to slow down; try again in a minute"
        else:
            return f"Spotify said {error.code}: {message or 'no reason given'}"

    # Check what's playing every few seconds (more often while music plays), for the wall screen and John
    def keep_checking(self):
        # Runs for the life of the program
        while True:
            # A failed check is logged quietly and tried again later
            try:
                # Only once signed in
                if self.signed_in():
                    self.refresh_now()
            except SpotifyError as error:
                log.debug("Couldn't check Spotify: %s", error)
            except Exception as error:
                log.warning("Spotify check failed: %s", error)
            self.wake.wait(PLAYING_POLL_SECONDS if self.now["playing"] else IDLE_POLL_SECONDS)
            self.wake.clear()

    # Ask Spotify what's playing now, and remember the device it's on
    def refresh_now(self):
        self.state = self.api("GET", "/me/player", {"additional_types": "episode"})
        self.now = describe_player(self.state)
        device = (self.state or {}).get("device") or {}

        # The device in use becomes the one to start on next time nothing is playing
        if device.get("id") and device["id"] != read_json(DEVICE_PATH, {}).get("id"):
            write_json(DEVICE_PATH, {"id": device["id"], "name": device.get("name", "")})
        return self.now

    # Which device to play on: the named one, else the one playing now, else the last one used if it's still open.
    # Returns (device id, name, already active); raises SpotifyError if none can be used.
    def pick_device(self, wanted=""):
        devices = self.api("GET", "/me/player/devices").get("devices") or []

        # A device asked for by name
        if wanted:
            device = find_device(devices, wanted)

            # It has to be open
            if not device:
                names = ", ".join(device.get("name", "") for device in devices) or "none"
                raise SpotifyError(f"no Spotify device called {wanted!r} is open (open ones: {names})")
            return device["id"], device.get("name", ""), bool(device.get("is_active"))
        active = [device for device in devices if device.get("is_active")]
        last_id = read_json(DEVICE_PATH, {}).get("id")
        last = [device for device in devices if device.get("id") == last_id]

        # Where it's playing, where it last played, or the only one open
        if active:
            return active[0]["id"], active[0].get("name", ""), True
        elif last:
            return last[0]["id"], last[0].get("name", ""), False
        elif len(devices) == 1:
            return devices[0]["id"], devices[0].get("name", ""), False
        else:
            raise SpotifyError("Spotify isn't open on any device right now; open it on your phone or laptop first")

    # Search for a song, artist, album or playlist (kind "any" tries all, and your own playlists first). Returns
    # {"uri", "name", "by", "kind"}; raises SpotifyError if nothing matched.
    def find(self, query, kind="any"):
        found = {}

        # Your own playlists come first for "any" and "playlist"
        if kind in ("any", "playlist"):
            found["own playlist"] = self.own_playlists()
        types = [SEARCH_TYPES[kind]] if kind in SEARCH_TYPES else list(SEARCH_TYPES.values())
        reply = self.api("GET", "/search", {"q": query, "type": ",".join(types), "limit": 5})

        # Each kind's results, under the names used here
        for each_kind, search_type in SEARCH_TYPES.items():
            found.setdefault(each_kind, [])
            found[each_kind] += (reply.get(search_type + "s") or {}).get("items") or []

        # A playlist asked for by name prefers your own
        if kind == "playlist":
            found["playlist"] = found["own playlist"] + found["playlist"]
        match = best_match(query, found, kind)

        # Nothing at all
        if not match:
            raise SpotifyError(f"Spotify found nothing for {query!r}")
        by = [artist.get("name", "") for artist in match.get("artists") or []]
        by = by or [((match.get("owner") or {}).get("display_name") or "")]
        return {"uri": match["uri"], "name": match.get("name", ""), "by": [name for name in by if name],
                "kind": match.get("type", "")}

    # Your playlists (name and uri), up to 200
    def own_playlists(self):
        playlists = []

        # Spotify gives 50 at a time
        for offset in range(0, 200, 50):
            page = self.api("GET", "/me/playlists", {"limit": 50, "offset": offset}) or {}
            playlists += [item for item in page.get("items") or [] if item]

            # The last page
            if not page.get("next"):
                break
        return playlists

    # Play something by name on a device (the one playing, or the last one used), or just carry on / move the music
    # there when query is empty. Returns what's playing.
    def play(self, query="", kind="any", device=""):
        device_id, device_name, active = self.pick_device(device)
        self.forget_pause()

        # Nothing named: carry on where it was, moving to that device if needed
        if not query:
            # A device that isn't playing takes the music over; otherwise it just carries on
            if not active:
                self.api("PUT", "/me/player", body={"device_ids": [device_id], "play": True})
            else:
                self.api("PUT", "/me/player/play", {"device_id": device_id})
            self.wake.set()
            return {"done": "resumed"}
        match = self.find(query, kind)
        body = {"uris": [match["uri"]]} if match["kind"] == "track" else {"context_uri": match["uri"]}
        self.api("PUT", "/me/player/play", {"device_id": device_id}, body)
        self.wake.set()
        return {"playing": match["name"], "kind": match["kind"]}  # No song title or device: John doesn't say them

    # Whether music is playing right now (checked fresh, as it decides whether John listens for a follow-up)
    def is_playing(self):
        # A failed check counts as the last thing known
        try:
            return self.refresh_now()["playing"]
        except SpotifyError:
            return self.now["playing"]

    # Pause, resume, next or previous on the device that's playing
    def control(self, action):
        # Resuming may need a device; the rest act on the one playing
        if action == "resume":
            return self.play()
        self.forget_pause()
        paths = {"pause": ("PUT", "/me/player/pause"), "next": ("POST", "/me/player/next"),
                 "previous": ("POST", "/me/player/previous")}
        method, path = paths[action]
        self.api(method, path)
        self.wake.set()
        return {"done": action}

    # What's playing right now, fresh from Spotify
    def what_is_playing(self):
        return self.refresh_now()

    # A pause or play asked for by voice replaces any pause made for speaking (so it isn't undone afterwards)
    def forget_pause(self):
        with self.duck_lock:
            # Only a pause made for speaking is forgotten; a lowered volume still goes back up
            if self.ducked and self.ducked[0] == "paused":
                self.ducked = None

    # Turn the music down while Nestor speaks or John listens (or pause it on devices whose volume can't be set).
    # Calls nest: only the first turns it down, and only the last undo() turns it back up.
    def duck(self):
        with self.duck_lock:
            self.duck_depth += 1

            # Already down, or nothing is playing
            if self.duck_depth > 1 or not self.now["playing"]:
                return
            device = (self.state or {}).get("device") or {}
            volume = device.get("volume_percent")

            # Spotify being slow or refusing never holds up Nestor
            try:
                # Quieter if the device allows it and isn't already quiet; otherwise paused
                if device.get("supports_volume", True) and volume is not None:
                    # Only louder music is turned down
                    if volume > self.duck_volume:
                        self.api("PUT", "/me/player/volume", {"volume_percent": self.duck_volume,
                                                              "device_id": device.get("id")})
                        self.ducked = ("volume", device.get("id"), volume)
                else:
                    self.api("PUT", "/me/player/pause", {"device_id": device.get("id")})
                    self.ducked = ("paused", device.get("id"))
            except SpotifyError as error:
                log.info("Couldn't turn the music down: %s", error)

    # Undo one duck(); the last one puts the volume back (or resumes)
    def undo_duck(self):
        with self.duck_lock:
            self.duck_depth = max(0, self.duck_depth - 1)

            # Still wanted down, or nothing to undo
            if self.duck_depth or not self.ducked:
                return
            ducked, self.ducked = self.ducked, None

            # Spotify being slow or refusing never holds up Nestor
            try:
                # Back to the old volume, or playing again
                if ducked[0] == "volume":
                    self.api("PUT", "/me/player/volume", {"volume_percent": ducked[2], "device_id": ducked[1]})
                else:
                    self.api("PUT", "/me/player/play", {"device_id": ducked[1]})
            except SpotifyError as error:
                log.info("Couldn't turn the music back up: %s", error)
            self.wake.set()

# Turn the music down, if Spotify is connected (for the announcer and John)
def duck():
    # Only with Spotify set up
    if music:
        music.duck()

# Turn the music back up, if Spotify is connected
def undo_duck():
    # Only with Spotify set up
    if music:
        music.undo_duck()

# Whether Spotify is playing music right now (False when Spotify isn't set up)
def music_playing():
    return bool(music and music.signed_in() and music.is_playing())
