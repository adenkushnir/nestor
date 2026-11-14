# Queues messages and speaks them one batch at a time: chime, speech, then the speaker goes back to how it was.
# Alerts that arrive during quiet hours are saved and played once quiet hours end.
import json
import logging
import os
import queue
import threading
import time
from nestor import chime
from nestor import tts
from nestor.config import DATA_DIR
from nestor.quiet import QuietHours
MAX_TEXT_LENGTH = 1000
HELD_PATH = os.path.join(DATA_DIR, "held_alerts.json")
log = logging.getLogger(__name__)

# Read the alerts held during quiet hours (saved to disk, so a restart overnight doesn't lose them)
def read_held():
    # No file means nothing is held
    if not os.path.exists(HELD_PATH):
        return []
    with open(HELD_PATH, encoding="utf-8") as held_file:
        return json.load(held_file)

# Save the list of held alerts
def write_held(held_alerts):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HELD_PATH, "w", encoding="utf-8") as held_file:
        json.dump(held_alerts, held_file, indent=1)

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

    # Speak an alert now, or hold it during quiet hours; returns True if it was held
    def alert(self, text):
        # At night the alert is saved for the morning instead of spoken
        if self.quiet_hours.is_quiet():
            with self.held_lock:
                write_held(read_held() + [text.strip()[:MAX_TEXT_LENGTH]])
            log.info("Holding until quiet hours end: %s", text)
            return True
        self.say(text)
        return False

    # Background loop: once quiet hours are over, play any alerts that were held
    def release_held(self):
        # Check every 30 seconds for the life of the program
        while True:
            # Held alerts wait until quiet hours are over
            if not self.quiet_hours.is_quiet():
                with self.held_lock:
                    held_alerts = read_held()

                    # Empty the saved list now that they are about to play
                    if held_alerts:
                        write_held([])

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
