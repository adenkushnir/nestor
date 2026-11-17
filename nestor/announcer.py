# Queues messages and speaks them one batch at a time: chime, speech, then the speaker goes back to how it was.
# Alerts that arrive during quiet hours are saved and played once quiet hours end.
import datetime
import logging
import os
import queue
import threading
import time
from nestor import chime
from nestor import tts
from nestor.config import DATA_DIR
from nestor.quiet import QuietHours
from nestor.storage import read_json
from nestor.storage import write_json
MAX_TEXT_LENGTH = 1000
HELD_PATH = os.path.join(DATA_DIR, "held_alerts.json")
HISTORY_PATH = os.path.join(DATA_DIR, "alert_history.json")
HISTORY_KEPT = 200
REPEAT_HOURS = 12  # An alert with the same key as one in the last 12 hours is a repeat and isn't spoken again
log = logging.getLogger(__name__)

# Read the recent alerts, oldest first: dicts with time, text, source, status ("spoken", "held", "dropped" or
# "repeat"), held, and the key and expiry they came with (for the briefing and the wall display)
def read_history():
    return read_json(HISTORY_PATH, [])

# Add one alert to the history, keeping only the most recent ones
def add_to_history(text, source, status, key=None, expires=None):
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "text": text, "source": source, "status": status,
             "held": status == "held", "key": key, "expires": expires}
    write_json(HISTORY_PATH, (read_history() + [entry])[-HISTORY_KEPT:])

# True if an alert with this key came in during the last 12 hours (Datebook sends a notification again when it updates)
def is_repeat(key, now):
    since = (now - datetime.timedelta(hours=REPEAT_HOURS)).isoformat(timespec="seconds")
    return any(entry.get("key") == key and entry["time"] >= since for entry in read_history())

# Mark held alerts that expired before quiet hours ended as dropped in the history
def mark_dropped(texts):
    history = read_history()

    # The most recent held entry with each text is the one that was dropped
    for text in texts:
        # Search from the newest entry back
        for entry in reversed(history):
            # Only a held entry with the same text
            if entry["text"] == text and entry.get("status", "held" if entry.get("held") else "spoken") == "held":
                entry["status"] = "dropped"
                entry["held"] = False
                break
    write_json(HISTORY_PATH, history)

# True if an alert's expiry ("2026-11-17T18:40:00", or None for never) is still ahead
def still_fresh(expires, now):
    return not expires or datetime.datetime.fromisoformat(expires) > now

# Read the alerts held during quiet hours (saved to disk, so a restart overnight doesn't lose them), as dicts with
# text and expires; older saves held plain texts
def read_held():
    saved = read_json(HELD_PATH, [])
    return [entry if isinstance(entry, dict) else {"text": entry, "expires": None} for entry in saved]

# Save the list of held alerts
def write_held(held_alerts):
    write_json(HELD_PATH, held_alerts)

# Speaks messages on the speaker in the order they arrive, never two at once
class Announcer:
    # Start the worker that plays queued messages, and the one that releases held alerts in the morning
    def __init__(self, speaker, settings, base_url):
        self.speaker = speaker
        self.base_url = base_url
        self.voice = settings.get("voice", "en-US-EmmaMultilingualNeural")
        self.voice_rate = settings.get("voice_rate", "+0%")
        self.announce_volume = float(settings.get("announce_volume", 0.5))
        self.chime_file = chime.ensure_chime() if settings.get("chime", True) else None
        self.quiet_hours = QuietHours(settings.get("quiet_hours", ""))
        self.held_lock = threading.Lock()
        self.jobs = queue.Queue()
        threading.Thread(target=self.run, name="announcer", daemon=True).start()
        threading.Thread(target=self.release_held, name="quiet-hours", daemon=True).start()

    # Queue one message, or a list to play together, and return an event set once spoken (or failed)
    def say(self, texts):
        # A single message is a list of one
        if isinstance(texts, str):
            texts = [texts]
        texts = [text.strip()[:MAX_TEXT_LENGTH] for text in texts if text.strip()]
        done = threading.Event()
        self.jobs.put((texts, done))
        return done

    # Speak an alert now, or hold it during quiet hours; source says where it came from ("github", "reminder",
    # "datebook", ...). expires ("2026-11-17T18:40:00") drops it if it can't be spoken by then, and key skips repeats.
    # Returns what happened: "spoken", "held", "dropped" or "repeat".
    def alert(self, text, source="other", expires=None, key=None):
        text = text.strip()[:MAX_TEXT_LENGTH]
        now = datetime.datetime.now()

        # Every alert goes in the history; at night it is also saved for the morning instead of spoken
        with self.held_lock:
            # Skip repeats and alerts that are already too late, otherwise hold or speak
            if key and is_repeat(key, now):
                status = "repeat"
                log.info("Skipping a repeat: %s", text)
            elif not still_fresh(expires, now):
                status = "dropped"
                log.info("Dropping an alert that came in too late: %s", text)
            elif self.quiet_hours.is_quiet():
                status = "held"
                write_held(read_held() + [{"text": text, "expires": expires}])
                log.info("Holding until quiet hours end: %s", text)
            else:
                status = "spoken"
                self.say(text)
            add_to_history(text, source, status, key, expires)
        return status

    # Background loop: once quiet hours are over, play any alerts that were held
    def release_held(self):
        # Check every 30 seconds for the life of the program
        while True:
            # Held alerts wait until quiet hours are over
            if not self.quiet_hours.is_quiet():
                with self.held_lock:
                    held_alerts = read_held()

                    # Empty the saved list now that they are about to play, and drop the ones that went stale
                    if held_alerts:
                        write_held([])
                        now = datetime.datetime.now()
                        stale = [alert["text"] for alert in held_alerts if not still_fresh(alert["expires"], now)]
                        held_alerts = [alert["text"] for alert in held_alerts if still_fresh(alert["expires"], now)]

                        # Note the stale ones in the history
                        if stale:
                            mark_dropped(stale)
                            log.info("Dropped %d held alerts that went stale overnight", len(stale))

                # Introduce the held alerts, then play them all as one batch
                if held_alerts:
                    count_words = "one message" if len(held_alerts) == 1 else f"{len(held_alerts)} messages"
                    self.say([f"While you were asleep, {count_words} came in."] + held_alerts)
            time.sleep(30)

    # Worker loop: wait for messages, and play everything that is waiting as one batch
    def run(self):
        # Runs for the life of the program
        while True:
            batch = [self.jobs.get()]

            # Pick up any other messages that arrived meanwhile, so the music is interrupted only once
            while not self.jobs.empty():
                batch.append(self.jobs.get_nowait())

            # A failed batch is logged and the worker carries on with the next one
            try:
                self.announce([text for texts, done in batch for text in texts])
            except Exception as error:
                log.error("Announcement failed: %s", error)
            finally:
                # Tell everyone waiting on these messages that they are finished
                for texts, done in batch:
                    done.set()

    # Speak a list of messages: make the audio first, then chime, speak each, and restore the speaker
    def announce(self, texts):
        # An empty batch has nothing to say
        if not texts:
            return
        speech_files = [tts.make_speech(text, self.voice, self.voice_rate) for text in texts]
        saved = self.speaker.snapshot()

        # Whatever happens while playing, the volume and earlier media get restored
        try:
            self.speaker.set_volume(self.announce_volume)

            # The chime is optional in config.yaml
            if self.chime_file:
                self.speaker.play_and_wait(self.media_url(self.chime_file), "audio/wav",
                                           expected_seconds=chime.CHIME_SECONDS)

            # Speak each message in turn
            for text, speech_file in zip(texts, speech_files):
                log.info("Speaking: %s", text)
                self.speaker.play_and_wait(self.media_url(speech_file), "audio/mpeg")
        finally:
            self.speaker.restore(saved)

    # Address the speaker uses to fetch a file from Nestor's web server
    def media_url(self, file_name):
        return f"{self.base_url}/media/{file_name}"
