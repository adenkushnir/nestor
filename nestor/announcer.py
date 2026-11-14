# Queues messages and speaks them one batch at a time: chime, speech, then the speaker goes back to how it was
import logging
import queue
import threading
from nestor import chime
from nestor import tts
MAX_TEXT_LENGTH = 1000
log = logging.getLogger(__name__)

# Speaks messages on the speaker in the order they arrive, never two at once
class Announcer:
    # Start the background worker that plays queued messages
    def __init__(self, speaker, settings, base_url):
        self.speaker = speaker
        self.base_url = base_url
        self.voice = settings.get("voice", "en-US-EmmaMultilingualNeural")
        self.voice_rate = settings.get("voice_rate", "+0%")
        self.announce_volume = float(settings.get("announce_volume", 0.5))
        self.chime_file = chime.ensure_chime() if settings.get("chime", True) else None
        self.jobs = queue.Queue()
        self.worker = threading.Thread(target=self.run, name="announcer", daemon=True)
        self.worker.start()

    # Queue a message and return an event that is set once it has been spoken (or has failed)
    def say(self, text):
        text = text.strip()[:MAX_TEXT_LENGTH]
        done = threading.Event()
        self.jobs.put((text, done))
        return done

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
                self.announce([text for text, done in batch])
            except Exception as error:
                log.error("Announcement failed: %s", error)
            finally:
                # Tell everyone waiting on these messages that they are finished
                for text, done in batch:
                    done.set()

    # Speak a list of messages: make the audio first, then chime, speak each, and restore the speaker
    def announce(self, texts):
        speech_files = [tts.make_speech(text, self.voice, self.voice_rate) for text in texts]
        saved = self.speaker.snapshot()

        # Whatever happens while playing, the volume and earlier media get restored
        try:
            self.speaker.set_volume(self.announce_volume)

            # The chime is optional in config.yaml
            if self.chime_file:
                self.speaker.play_and_wait(self.media_url(self.chime_file), "audio/wav")

            # Speak each message in turn
            for text, speech_file in zip(texts, speech_files):
                log.info("Speaking: %s", text)
                self.speaker.play_and_wait(self.media_url(speech_file), "audio/mpeg")
        finally:
            self.speaker.restore(saved)

    # Address the speaker uses to fetch a file from Nestor's web server
    def media_url(self, file_name):
        return f"{self.base_url}/media/{file_name}"
