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
        self.chime_file = chime.ensure_chime() if settings.get("chime", True) else None
        self.quiet_hours = QuietHours(settings.get("quiet_hours", ""))
        self.held_lock = threading.Lock()
        self.jobs = queue.Queue()
        self.tapped_at = 0.0  # When someone last tapped the speaker to stop what was playing (time.time())
        self.playing = False  # True while a batch is being played
        threading.Thread(target=self.run, name="announcer", daemon=True).start()
        threading.Thread(target=self.release_held, name="quiet-hours", daemon=True).start()

    # Queue one message, or a list to play together, and return an event set once spoken (or failed);
    # with_chime=False leaves out the chime (John's answers come straight after his own sounds). Nestor speaks at the
    # speaker's own volume (every change makes the speaker's sound); volume (0.0 to 1.0) is only for special cases.
    def say(self, texts, with_chime=True, volume=None):
        # A single message is a list of one
        if isinstance(texts, str):
            texts = [texts]
        texts = [text.strip()[:MAX_TEXT_LENGTH] for text in texts if text.strip()]
        done = threading.Event()
        self.jobs.put((texts, done, with_chime, volume))
        return done

    # Queue a short sound (a WAV in the cache folder that lasts the given seconds) with no chime, and return an event
    # set once it has played
    def sound(self, file_name, seconds, volume=None):
        done = threading.Event()
        self.jobs.put(([{"sound": file_name, "seconds": seconds}], done, False, volume))
        return done

    # True while something is playing or waiting to play (John doesn't listen then, so he doesn't hear the speaker)
    def busy(self):
        return self.playing or not self.jobs.empty()

    # Cut short whatever is playing and drop what's waiting to play (used when John is called over a ringing alarm)
    def interrupt(self):
        # Empty the queue, telling anyone waiting that their messages are finished
        while not self.jobs.empty():
            items, done, wants_chime, volume = self.jobs.get_nowait()
            done.set()
        self.speaker.interrupted.set()

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
            self.release_now()
            time.sleep(30)

    # If it isn't quiet hours, play the alerts held overnight (dropping the ones that went stale) and return the event
    # set once they have played; None if there was nothing to play
    def release_now(self):
        # Held alerts wait until quiet hours are over
        if self.quiet_hours.is_quiet():
            return None

        # Take the held alerts, so they are played only once
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

        # Nothing left to play
        if not held_alerts:
            return None
        count_words = "one message" if len(held_alerts) == 1 else f"{len(held_alerts)} messages"
        return self.say([f"While you were asleep, {count_words} came in."] + held_alerts)

    # Worker loop: wait for messages, and play everything that is waiting as one batch
    def run(self):
        # Runs for the life of the program
        while True:
            batch = [self.jobs.get()]

            # Pick up any other messages that arrived meanwhile, so the music is interrupted only once
            while not self.jobs.empty():
                batch.append(self.jobs.get_nowait())
            volumes = [volume for items, done, wants_chime, volume in batch if volume is not None]
            self.playing = True

            # A failed batch is logged and the worker carries on with the next one
            try:
                self.announce([item for items, done, wants_chime, volume in batch for item in items],
                              any(wants_chime for items, done, wants_chime, volume in batch),
                              max(volumes) if volumes else None)
            except Exception as error:
                log.error("Announcement failed: %s", error)
            finally:
                self.playing = False

                # Tell everyone waiting on these messages that they are finished
                for items, done, wants_chime, volume in batch:
                    done.set()

    # Play a list of messages and sounds: make the audio first, then the chime (if wanted), each item in turn, and
    # restore the speaker. A message is text; a sound is {"sound": file name, "seconds": length}. A tap on the speaker
    # or interrupt() ends the batch early.
    def announce(self, items, wants_chime=True, volume=None):
        # An empty batch has nothing to say
        if not items:
            return
        audio = [item if isinstance(item, dict) else {"text": item, "speech": tts.make_speech(item, self.voice,
                 self.voice_rate)} for item in items]
        saved = self.speaker.snapshot()
        self.speaker.interrupted.clear()

        # Whatever happens while playing, the volume (if changed) and earlier media get restored
        try:
            # The volume only changes when asked for, since each change makes the speaker's sound
            if volume is not None:
                self.speaker.set_volume(volume)

            # The chime is optional in config.yaml, and left out for John's sounds and answers
            if self.chime_file and wants_chime:
                self.speaker.play_and_wait(self.media_url(self.chime_file), "audio/wav",
                                           expected_seconds=chime.CHIME_SECONDS)

            # Play each sound or message in turn, stopping if someone taps the speaker or John cuts in
            for item in audio:
                # Sounds are short WAVs timed by their known length; messages are speech
                if "sound" in item:
                    result = self.speaker.play_and_wait(self.media_url(item["sound"]), "audio/wav",
                                                        expected_seconds=item["seconds"])
                else:
                    log.info("Speaking: %s", item["text"])
                    result = self.speaker.play_and_wait(self.media_url(item["speech"]), "audio/mpeg")

                # A tap is remembered (it stops a ringing alarm); either way the rest of the batch is skipped
                if result == "tapped":
                    self.tapped_at = time.time()
                    break
                elif result == "interrupted":
                    break
        finally:
            self.speaker.restore(saved, restore_volume=volume is not None)

    # Address the speaker uses to fetch a file from Nestor's web server
    def media_url(self, file_name):
        return f"{self.base_url}/media/{file_name}"
