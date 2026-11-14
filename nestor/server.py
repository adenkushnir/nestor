# Nestor's local web server: serves audio to the speaker and takes messages from other programs
import logging
from flask import Flask
from flask import jsonify
from flask import request
from flask import send_from_directory
from nestor.announcer import MAX_TEXT_LENGTH
from nestor.config import CACHE_DIR
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

# Build the Flask app around the announcer
def create_app(announcer):
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
        if payload.get("wait") in (True, "true", "1"):
            done.wait(WAIT_TIMEOUT_SECONDS)
        return jsonify(queued=True)

    # Speak an alert from another program; during quiet hours it is held until they end
    @app.post("/alert")
    def alert():
        text, payload, error = read_message()

        # Bad requests get their error back
        if error:
            return error
        return jsonify(queued=True, held=announcer.alert(text))

    # Quick check that Nestor is running and which speaker it uses
    @app.get("/health")
    def health():
        return jsonify(status="ok", speaker=announcer.speaker.name)
    return app
