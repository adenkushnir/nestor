# Nestor's local web server: serves audio to the speaker, takes messages from other programs, and offers reminders,
# the briefing and recent alerts as JSON (for the phone page, Datebook and the wall display)
import datetime
import json
import logging
import os
from flask import Flask
from flask import Response
from flask import jsonify
from flask import redirect
from flask import request
from flask import send_from_directory
from nestor import datebook
from nestor import reminders
from nestor import routines
from nestor import spotify
from nestor import timers
from nestor import wall_live
from nestor.announcer import MAX_TEXT_LENGTH
from nestor.announcer import read_history
from nestor.briefing import DAYS
from nestor.briefing import build_briefing
from nestor.config import CACHE_DIR
from nestor.config import load_secrets
from nestor.john_tools import JohnTools
from nestor.john_tools import connector_tool_definitions
from nestor.quiet import QuietHours
from nestor.spoken import speakable
from nestor.spoken import spoken_moment
from nestor.trains import RailData
from nestor.wall import Wall
from nestor.when import parse_when
WAIT_TIMEOUT_SECONDS = 180
MAX_REQUEST_BYTES = 1_000_000  # Datebook's snapshot is the biggest thing sent in
HEARTBEAT_SECONDS = 25  # The live feed sends a keep-alive this often, so idle connections aren't cut
LIVE_CHECK_SECONDS = 2  # The wall's live feed also looks for changes nobody announced (the sleeping period) this often
LOCAL_ADDRESSES = ("127.0.0.1", "::1")
PAGES_DIR = os.path.join(os.path.dirname(__file__), "pages")  # Web pages Nestor shows, like the wall screen's
WALL_DIR = os.path.join(PAGES_DIR, "wall")  # The wall display's page, pictures and fonts
log = logging.getLogger(__name__)

# Read the request's JSON object or form fields; returns (payload, error response or None). Bodies that aren't UTF-8
# are read as Windows text, because Git Bash's curl sends characters like "·" in the Windows code page.
def read_body():
    # Form posts (and requests without a JSON body) are read as they are
    if not request.is_json:
        return request.form, None
    raw = request.get_data()

    # UTF-8 first, Windows text if that fails
    try:
        body_text = raw.decode("utf-8")
    except UnicodeDecodeError:
        body_text = raw.decode("cp1252", errors="replace")

    # An empty body is an empty object
    if not body_text.strip():
        return {}, None

    # It has to be a JSON object
    try:
        payload = json.loads(body_text)
    except ValueError as error:
        return None, (jsonify(error=f"the body isn't valid JSON: {error}"), 400)

    # Lists, numbers and strings aren't accepted
    if not isinstance(payload, dict):
        return None, (jsonify(error="send a JSON object, like {\"text\": \"...\"}"), 400)
    return payload, None

# Pull the message text out of a JSON body or form; returns (text, payload, error response or None)
def read_message():
    payload, error = read_body()

    # A body that can't be read gets its own error
    if error:
        return "", payload, error
    text = str(payload.get("text") or "").strip()

    # Refuse empty or very long messages
    if not text:
        return text, payload, (jsonify(error="text is required"), 400)
    elif len(text) > MAX_TEXT_LENGTH:
        return text, payload, (jsonify(error=f"text is longer than {MAX_TEXT_LENGTH} characters"), 400)
    return text, payload, None

# True if the request asked to wait until speaking is done
def wants_wait(payload):
    return payload.get("wait") in (True, "true", "1")

# Read a date and time sent in ("2026-11-17T18:40:00", with or without a time zone) as local time; None if empty.
# Raises ValueError if it isn't a date and time.
def local_moment(text):
    # Empty means none
    if not text:
        return None
    moment = datetime.datetime.fromisoformat(str(text))

    # Times with a zone are turned into this computer's local time
    if moment.tzinfo:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment

# Which briefing the request asked for, "today" or "tomorrow"; None if it's neither
def asked_day(payload):
    day = str(payload.get("day") or "today").lower()
    return day if day in DAYS else None

# The token a request carries in its "Authorization: Bearer ..." header (empty if none)
def bearer_token():
    header = request.headers.get("Authorization", "")
    return header[7:].strip() if header.startswith("Bearer ") else ""

# None if the request may use Datebook's data (it comes from this machine, e.g. the wall display, or carries a paired
# phone's token), otherwise the error response to send back
def refuse_unpaired():
    # Local pages need no token
    if request.remote_addr in LOCAL_ADDRESSES or datebook.check_token(bearer_token()):
        return None
    return jsonify(error="pair with Nestor first: python -m nestor --pair"), 401

# Build the Flask app around the announcer and the settings
def create_app(announcer, settings):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # Hide a log line for every audio request
    # Spotify sends the browser back here after signing in (Spotify only allows 127.0.0.1, not localhost)
    spotify_redirect = f"http://127.0.0.1:{int(settings.get('port', 8765))}/spotify/callback"
    connector_tools = []  # The connector's copy of John's tools, made on first use
    secrets = load_secrets()
    has_rail = secrets.get("NJT_USERNAME") and secrets.get("NJT_PASSWORD")
    wall = Wall(settings, RailData(secrets["NJT_USERNAME"], secrets["NJT_PASSWORD"]) if has_rail else None)

    # Serve generated audio (speech and chime) to the speaker
    @app.get("/media/<path:file_name>")
    def media(file_name):
        return send_from_directory(CACHE_DIR, file_name)

    # Speak a message straight away: JSON {"text": "...", "wait": false} or a form field "text"
    @app.post("/speak")
    def speak():
        text, payload, error = read_message()

        # Bad requests get their error back
        if error:
            return error
        done = announcer.say(text)

        # Optionally hold the reply until the message has been spoken
        if wants_wait(payload):
            done.wait(WAIT_TIMEOUT_SECONDS)
        return jsonify(queued=True)

    # Speak an alert from another program: {"text": "...", "source": "datebook", "expires": "2026-11-17T18:40:00",
    # "key": "..."}. Held during quiet hours; dropped once it expires; a repeated key is spoken only once.
    @app.post("/alert")
    def alert():
        text, payload, error = read_message()

        # Bad requests get their error back
        if error:
            return error
        source = str(payload.get("source") or "other")

        # The expiry must be a date and time
        try:
            expires = local_moment(payload.get("expires"))
        except ValueError:
            return jsonify(error="expires must be a date and time like 2026-11-17T18:40:00"), 400

        # Datebook sends its notifications as they look on the phone, so make them read well aloud
        if source == "datebook":
            text = speakable(text)
        status = announcer.alert(text, source=source, key=str(payload.get("key") or "") or None,
                                 expires=expires.isoformat(timespec="seconds") if expires else None)
        return jsonify(queued=status in ("spoken", "held"), held=status == "held", status=status)

    # Recent alerts, newest first (?limit=20)
    @app.get("/alerts")
    def alerts():
        limit = request.args.get("limit", default=20, type=int)
        return jsonify(alerts=list(reversed(read_history()))[:max(0, limit)])

    # All reminders: one-off, repeating, and today's
    @app.get("/reminders")
    def list_reminders():
        return jsonify(reminders.reminders_data())

    # Add a one-off reminder: {"text": "...", "at": "2026-11-15T18:00:00"} or {"text": "...", "when": "tomorrow 6pm"}
    @app.post("/reminders")
    def add_reminder():
        text, payload, error = read_message()

        # Bad requests get their error back
        if error:
            return error

        # An exact time, or words to work one out from
        try:
            moment = datetime.datetime.fromisoformat(payload["at"]) if payload.get("at") else None
        except ValueError:
            return jsonify(error="at must be a date and time like 2026-11-15T18:00:00"), 400

        # Fall back to the words in "when"
        if moment is None:
            moment = parse_when(str(payload.get("when") or ""))

        # The time must be readable and still ahead
        if moment is None or moment <= datetime.datetime.now():
            return jsonify(error="a future time is required, in 'at' or 'when'"), 400
        reminder = reminders.add_reminder(text, moment)
        quiet = QuietHours(settings.get("quiet_hours", "")).is_quiet(moment)
        return jsonify(reminder=reminder, spoken_time=spoken_moment(moment), during_quiet_hours=quiet), 201

    # Delete a one-off reminder by its id
    @app.delete("/reminders/<reminder_id>")
    def delete_reminder(reminder_id):
        # Unknown ids get a 404
        if not reminders.delete_reminder(reminder_id):
            return jsonify(error="no reminder with that id"), 404
        return jsonify(deleted=True)

    # The briefing as data and text, without speaking it (?day=tomorrow for the goodnight preview)
    @app.get("/briefing")
    def show_briefing():
        day = asked_day(request.args)

        # Only today and tomorrow have briefings
        if not day:
            return jsonify(error="day must be today or tomorrow"), 400
        return jsonify(build_briefing(settings, day=day))

    # Speak the briefing now ({"day": "tomorrow"} for the preview, {"wait": true} to reply after it has been spoken)
    @app.post("/briefing")
    def speak_briefing():
        payload, error = read_body()

        # A body that can't be read gets its error back
        if error:
            return error
        day = asked_day(payload)

        # Only today and tomorrow have briefings
        if not day:
            return jsonify(error="day must be today or tomorrow"), 400
        briefing = build_briefing(settings, day=day)
        done = announcer.say(briefing["text"])

        # Optionally hold the reply until the briefing has been spoken
        if wants_wait(payload):
            done.wait(WAIT_TIMEOUT_SECONDS)
        return jsonify(briefing)

    # "Start my day": end the sleeping period, speak the day ahead, then what was held overnight
    @app.post("/start-my-day")
    def start_day():
        return jsonify(routines.start_my_day(announcer, settings))

    # "Goodnight": speak tomorrow's preview, then start the sleeping period until quiet hours would end
    @app.post("/goodnight")
    def good_night():
        return jsonify(routines.goodnight(announcer, settings))

    # The timers and alarms set, and what's ringing
    @app.get("/timers")
    def list_timers():
        return jsonify(timers.timers_data())

    # Stop or snooze what's ringing
    @app.post("/timers/<what>")
    def stop_timer(what):
        # Only these two, and only in the full service
        if what not in ("stop", "snooze") or not timers.scheduler:
            return jsonify(error="POST /timers/stop or /timers/snooze, while Nestor is running"), 404
        done = timers.scheduler.stop() if what == "stop" else timers.scheduler.snooze()
        return jsonify(done=done)

    # Cancel a timer or alarm by its id
    @app.delete("/timers/<item_id>")
    def delete_timer(item_id):
        # Unknown ids get a 404
        if not timers.cancel(item_id):
            return jsonify(error="no timer or alarm with that id"), 404
        return jsonify(deleted=True)

    # What's playing on Spotify, for the wall screen: {"playing", "track", "artists", "album", "art", "progress_ms",
    # "duration_ms", "device", "signed_in"}
    @app.get("/music")
    def now_playing():
        # Without Spotify set up there's nothing playing to show
        if spotify.music:
            state = dict(spotify.music.now, signed_in=spotify.music.signed_in())
        else:
            state = dict(spotify.describe_player(None), signed_in=False)
        return refuse_unpaired() or jsonify(state)  # Only this machine (the wall screen) and a paired phone may look

    # Sign Nestor in to Spotify: open http://127.0.0.1:8765/spotify/login in a browser on this PC
    @app.get("/spotify/login")
    def spotify_login():
        # Only from this PC, and only once Spotify is set up in .env
        if request.remote_addr not in LOCAL_ADDRESSES:
            return jsonify(error="sign in from the PC Nestor runs on"), 403
        elif not spotify.music:
            return jsonify(error="put SPOTIFY_CLIENT_ID in .env and restart Nestor first"), 503
        return redirect(spotify.music.login_url(spotify_redirect))

    # Where Spotify comes back to with the sign-in code
    @app.get("/spotify/callback")
    def spotify_callback():
        # Spotify sends an error instead when the sign-in was cancelled
        if request.args.get("error") or not spotify.music:
            return f"Spotify sign-in didn't finish: {request.args.get('error') or 'Spotify is not set up'}", 400

        # A bad or old code is explained
        try:
            spotify.music.finish_login(request.args.get("code", ""), request.args.get("state", ""), spotify_redirect)
        except spotify.SpotifyError as error:
            return f"Spotify sign-in didn't finish: {error}", 400
        return "Nestor is signed in to Spotify. You can close this tab."

    # The tools Claude Code and Claude Desktop get through the connector (nestor_connector.py): John's, without his
    # memory, plus speaking and the home's status
    @app.get("/tools")
    def list_tools():
        return refuse_unpaired() or jsonify(tools=connector_tool_definitions())

    # Run one of those tools: the body is its input; answers {"result": "..."} or an error with the reason
    @app.post("/tools/<name>")
    def run_tool(name):
        payload, error = read_body()
        refused = refuse_unpaired()

        # Only this PC or a paired computer, a readable body, and a tool the connector has
        if refused or error:
            return refused or error
        elif name not in {tool["name"] for tool in connector_tool_definitions()}:
            return jsonify(error=f"no tool called {name}"), 404

        # The tools are made on first use (John's own copy lives in his brain)
        if not connector_tools:
            connector_tools.append(JohnTools(announcer, settings, RailData(load_secrets().get("NJT_USERNAME"),
                                                                           load_secrets().get("NJT_PASSWORD"))))

        # A failing tool sends back what went wrong
        try:
            return jsonify(result=connector_tools[0].call(name, payload))
        except Exception as tool_error:
            log.info("Claude's %s failed: %s", name, tool_error)
            return jsonify(error=str(tool_error)), 400

    # Quick check that Nestor is running and which speaker it uses
    @app.get("/health")
    def health():
        return jsonify(status="ok", speaker=announcer.speaker.name)

    # The wall display's page on the 7-inch screen
    @app.get("/screen")
    def screen():
        return send_from_directory(WALL_DIR, "index.html")

    # The wall display's scripts, pictures and fonts (only pictures and fonts are kept by the browser, so a changed
    # script shows as soon as the page reloads)
    @app.get("/screen/<path:file_name>")
    def screen_file(file_name):
        keep = file_name.startswith(("img/", "fonts/"))
        return send_from_directory(WALL_DIR, file_name, max_age=3600 if keep else 0)

    # Everything the wall display shows right now: weather, the next event, Later today, trains, music, men's foil
    @app.get("/wall/state")
    def wall_state():
        return refuse_unpaired() or jsonify(wall.state())

    # Stop John mid-conversation (a tap anywhere on the wall while he listens, thinks or talks); answers {"stopped"}
    @app.post("/john/stop")
    def stop_john():
        from nestor import john  # Imported here only: John's libraries load slowly, and only the full service has him
        refused = refuse_unpaired()

        # Only this machine (the wall) and paired devices may stop him
        if refused:
            return refused
        return jsonify(stopped=bool(john.current and john.current.cancel()))

    # The wall's live feed (Server-Sent Events): John's state, what's ringing, the sleeping period, the first alarm and
    # the timers, sent whenever they change
    @app.get("/wall/live")
    def wall_live_feed():
        refused = refuse_unpaired()

        # Only this machine (the wall) and paired devices may watch it
        if refused:
            return refused

        # Send the state at once and again whenever it changes, with a keep-alive comment in quiet spells
        def stream():
            version = -1
            sent = None
            quiet_since = datetime.datetime.now()

            # Runs until the page closes the connection
            while True:
                version = wall_live.wait(version, LIVE_CHECK_SECONDS)
                state = wall_live.live_state(announcer)

                # Something new goes out; otherwise a comment now and then keeps the connection open
                if state != sent:
                    sent = state
                    quiet_since = datetime.datetime.now()
                    yield f"event: live\ndata: {json.dumps(state)}\n\n"
                elif (datetime.datetime.now() - quiet_since).total_seconds() >= HEARTBEAT_SECONDS:
                    quiet_since = datetime.datetime.now()
                    yield ": still here\n\n"
        return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})

    # Pair a phone: {"code": "123456", "device": "Pixel 9"} with the code from python -m nestor --pair; answers
    # {"token": "..."}, which the phone sends with every Datebook call after that. A computer (the Claude connector)
    # adds "kind": "computer".
    @app.post("/pair")
    def pair():
        payload, error = read_body()

        # A body that can't be read gets its error back
        if error:
            return error
        token, problem = datebook.pair(payload.get("code") or "", payload.get("device") or "",
                                       kind=payload.get("kind") or "phone")

        # A wrong or old code gets the reason back
        if problem:
            return jsonify(error=problem), 403
        return jsonify(token=token), 201

    # Unpair the phone whose token this is
    @app.delete("/pair")
    def unpair():
        # Only a known token can be removed
        if not datebook.unpair(bearer_token()):
            return jsonify(error="that token isn't paired"), 404
        return jsonify(unpaired=True)

    # Datebook's latest snapshot, with "connected", "stale" and "updated"
    @app.get("/datebook/state")
    def datebook_state():
        return refuse_unpaired() or jsonify(datebook.read_state())

    # Datebook sends its whole snapshot (waiting, lists, notes, reminders, trip); it replaces the last one
    @app.put("/datebook/state")
    def save_datebook_state():
        refused = refuse_unpaired()

        # Only paired phones (or this machine) may change it
        if refused:
            return refused
        snapshot, error = read_body()

        # It has to be a JSON object
        if error or not request.is_json:
            return error or (jsonify(error="send the snapshot as a JSON object"), 400)
        datebook.save_state(snapshot)
        return jsonify(saved=True)

    # Live feed of Datebook's snapshot for the wall display (Server-Sent Events): the current one straight away,
    # then each new one as it arrives
    @app.get("/datebook/events")
    def datebook_events():
        refused = refuse_unpaired()

        # Only paired phones (or this machine) may watch it
        if refused:
            return refused

        # Send snapshots as they change, and a keep-alive comment when there's nothing new
        def stream():
            version = -1

            # Runs until the page closes the connection
            while True:
                version, state = datebook.next_state(version, HEARTBEAT_SECONDS)

                # A quiet spell gets a comment line, a change the new snapshot
                if state is None:
                    yield ": still here\n\n"
                else:
                    yield f"event: state\ndata: {json.dumps(state)}\n\n"
        return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache"})

    # Ask the phone to do something: {"action": "add" | "ignore" | "done", "id": 12} or
    # {"action": "new_plan", "text": "dinner with Sam Friday at 7"}
    @app.post("/datebook/actions")
    def add_datebook_action():
        refused = refuse_unpaired()

        # Only paired phones (or this machine) may queue actions
        if refused:
            return refused
        payload, error = read_body()

        # A body that can't be read gets its error back
        if error:
            return error

        # Bad actions get the reason back
        try:
            queued = datebook.add_action(payload.get("action"), payload.get("id"), payload.get("text"))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        return jsonify(queued=queued), 201

    # The phone collects waiting actions; ?wait=50 holds the request open up to 50 seconds until one arrives
    @app.get("/datebook/actions")
    def take_datebook_actions():
        refused = refuse_unpaired()

        # Only paired phones (or this machine) may take them
        if refused:
            return refused
        return jsonify(actions=datebook.take_actions(request.args.get("wait", default=0, type=float)))
    return app
