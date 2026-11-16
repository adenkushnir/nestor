# Nestor's local web server: serves audio to the speaker, takes messages from other programs, and offers reminders,
# the briefing and recent alerts as JSON (for the phone page, Datebook and the wall display)
import datetime
import logging
from flask import Flask
from flask import jsonify
from flask import request
from flask import send_from_directory
from nestor import reminders
from nestor.announcer import MAX_TEXT_LENGTH
from nestor.announcer import read_history
from nestor.briefing import build_briefing
from nestor.config import CACHE_DIR
from nestor.quiet import QuietHours
from nestor.spoken import spoken_moment
from nestor.when import parse_when
WAIT_TIMEOUT_SECONDS = 180

# Pull the message text out of a JSON body or form; returns (text, payload, error response or None)
def read_message():
    payload = request.get_json(silent=True) or request.form
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

# Build the Flask app around the announcer and the settings
def create_app(announcer, settings):
    app = Flask(__name__)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # Hide a log line for every audio request

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

    # Speak an alert from another program ({"text": "...", "source": "datebook"}); held during quiet hours
    @app.post("/alert")
    def alert():
        text, payload, error = read_message()

        # Bad requests get their error back
        if error:
            return error
        return jsonify(queued=True, held=announcer.alert(text, source=str(payload.get("source") or "other")))

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

    # The briefing as data and text, without speaking it
    @app.get("/briefing")
    def show_briefing():
        return jsonify(build_briefing(settings))

    # Speak the briefing now ({"wait": true} to reply after it has been spoken)
    @app.post("/briefing")
    def speak_briefing():
        payload = request.get_json(silent=True) or request.form
        briefing = build_briefing(settings)
        done = announcer.say(briefing["text"])

        # Optionally hold the reply until the briefing has been spoken
        if wants_wait(payload):
            done.wait(WAIT_TIMEOUT_SECONDS)
        return jsonify(briefing)

    # Quick check that Nestor is running and which speaker it uses
    @app.get("/health")
    def health():
        return jsonify(status="ok", speaker=announcer.speaker.name)
    return app
