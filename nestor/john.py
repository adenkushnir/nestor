# Hey John: listens on the microphone for "Hey John" (openWakeWord), records until you stop talking (a speech detector
# tells voices from noise and beeps), turns it into text on this computer (faster-whisper), asks the brain, and speaks
# the answer, then listens a few seconds for a follow-up
import logging
import os
import re
import threading
import time
import numpy
import openwakeword.utils
import pvrecorder
from faster_whisper import WhisperModel
from openwakeword.model import Model as WakeWordModel
from openwakeword.vad import VAD
from nestor import timers
from nestor.brain import Brain
from nestor.config import PROJECT_DIR
from nestor.microphone import FRAME_LENGTH
from nestor.microphone import find_microphone
from nestor.sounds import play_sound
from nestor.trains import RailData
SAMPLE_RATE = 16000  # openWakeWord and Whisper both work at 16 kHz
FRAME_SECONDS = FRAME_LENGTH / SAMPLE_RATE
FALLBACK_WAKE_WORD = "hey_jarvis"  # openWakeWord's built-in model, used until the "Hey John" model is trained
SILENCE_SECONDS = 0.8  # This long without speech after speaking ends the recording
MIN_SPEECH_SECONDS = 0.08  # One frame the detector is sure is a voice: enough for "no" or "stop"
FIRST_WAIT_SECONDS = 6  # After "Hey John", how long to wait for you to start talking
MAX_RECORD_SECONDS = 15
SPEAKER_QUIET_TIMEOUT = 120  # The longest John waits for the speaker to finish before listening for a follow-up
STOP_WORDS = {"stop", "cancel", "never mind", "nevermind", "nothing", "that's all", "thanks", "thank you"}
SNOOZE_WORDS = {"snooze", "snooze it", "snooze that", "snooze the alarm", "snooze the timer"}
ANSWER_TIMEOUT_SECONDS = 180
THINKING_AFTER_SECONDS = 2.5  # Play the thinking sound if Claude takes longer than this
WAKE_PHRASE = re.compile(r"\b(hey|hi|okay),?\s+(john|jarvis)\b[,.!?]*", re.IGNORECASE)
log = logging.getLogger(__name__)

# What was said without the wake phrase, which sometimes ends up in the recording ("What time is it? Hey John")
def without_wake_phrase(heard):
    return " ".join(WAKE_PHRASE.sub(" ", heard).split()).strip(" ,")

# What's missing before John can run, as a list of problems; empty when ready
def missing_setup(settings, secrets):
    needs = [(bool(secrets.get("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY in .env (Nestor's own Claude key)")]
    return [problem for ready, problem in needs if not ready]

# Where the trained "Hey John" model file is (relative names are in the project folder)
def wake_word_path(settings):
    return os.path.join(PROJECT_DIR, settings.get("john_wake_word", "hey_john.onnx"))

# The wake word model to load and the phrase that wakes it: the trained "Hey John" file if it's there, otherwise
# openWakeWord's built-in "Hey Jarvis", so John can be used before his own model is trained
def wake_word_choice(settings):
    path = wake_word_path(settings)
    return (path, "Hey John") if os.path.exists(path) else (FALLBACK_WAKE_WORD, "Hey Jarvis")

# The Hey John listener, running in the background for the life of the service
class John:
    # Keep what John needs and start listening in the background
    def __init__(self, announcer, settings, secrets):
        self.announcer = announcer
        self.settings = settings
        self.secrets = secrets
        self.follow_up_seconds = float(settings.get("john_follow_up_seconds", 5))
        self.speech_chance = float(settings.get("john_speech_threshold", 0.4))
        threading.Thread(target=self.run, name="hey-john", daemon=True).start()

    # Set up the wake word, speech detector, microphone, speech-to-text and brain, then wait for "Hey John" forever
    def run(self):
        # Anything that stops John from starting is logged; the rest of Nestor keeps running
        try:
            model, self.phrase = wake_word_choice(self.settings)
            openwakeword.utils.download_models([FALLBACK_WAKE_WORD])  # The shared audio models (only the first time)
            self.wake_word = WakeWordModel(wakeword_models=[model], inference_framework="onnx")
            self.threshold = float(self.settings.get("john_wake_threshold", 0.5))
            self.speech = VAD()
            self.recorder = pvrecorder.PvRecorder(frame_length=FRAME_LENGTH,
                                                  device_index=find_microphone(self.settings.get("microphone", "")))
            log.info("Loading speech-to-text (%s); the first time downloads it",
                     self.settings.get("whisper_model", "small.en"))
            self.whisper = WhisperModel(self.settings.get("whisper_model", "small.en"), device="cpu",
                                        compute_type="int8")
            rail = RailData(self.secrets.get("NJT_USERNAME"), self.secrets.get("NJT_PASSWORD"))
            self.brain = Brain(self.announcer, self.settings, self.secrets["ANTHROPIC_API_KEY"], rail)
        except Exception as error:
            log.error("Hey John couldn't start: %s", error)
            return
        log.info("Hey John is listening on %s: say \"%s\"", self.recorder.selected_device, self.phrase)
        self.recorder.start()

        # Wait for the wake word, then hold a conversation; problems are logged and listening carries on
        while True:
            # Keep listening even if one conversation fails
            try:
                scores = self.wake_word.predict(numpy.array(self.recorder.read(), dtype=numpy.int16))

                # "Hey John" heard: talk, then clear the wake word's memory of the audio so it doesn't fire twice
                if max(scores.values()) >= self.threshold:
                    log.info("Heard the wake word (score %.2f)", max(scores.values()))
                    self.wake_word.reset()
                    self.talk()
                    self.wake_word.reset()
            except Exception as error:
                log.error("Hey John had a problem: %s", error)
                play_sound(self.announcer, "error")
                time.sleep(1)

            # Make sure the microphone is running again for the next "Hey John"
            if not self.recorder.is_recording:
                self.recorder.start()

    # Hold a conversation, pausing any ringing timer or alarm meanwhile so John can be heard
    def talk(self):
        ringing = timers.scheduler and timers.scheduler.ringing

        # Ringing is cut off at once and waits while John talks; it carries on afterwards unless it was stopped
        if ringing:
            timers.scheduler.paused.set()
            self.announcer.interrupt()

        # The ringing always resumes, even if the conversation fails
        try:
            self.conversation()
        finally:
            # Let ringing carry on
            if timers.scheduler:
                timers.scheduler.paused.clear()

    # One conversation: listen, answer, and keep going while follow-ups come within a few seconds
    def conversation(self):
        play_sound(self.announcer, "listening")
        wait_seconds = FIRST_WAIT_SECONDS

        # Each round is one thing said and John's answer
        while True:
            heard = self.listen(wait_seconds)

            # Nobody spoke: the conversation is over
            if heard is None:
                return
            words = heard.lower().strip(" .!?,")
            ringing = timers.scheduler and timers.scheduler.ringing

            # Snooze or stop what's ringing, or end on "never mind", without asking Claude ("snooze for 2 minutes"
            # goes to Claude, which knows how long)
            if ringing and words in SNOOZE_WORDS:
                timers.scheduler.snooze()
                return
            elif ringing and (words in STOP_WORDS or "stop" in words or words.endswith("off")):
                timers.scheduler.stop()
                return
            elif not heard or words in STOP_WORDS:
                return
            answer = self.answer(heard)

            # Speak the answer (some tools, like goodnight, speak for themselves) and wait until it's done
            if answer:
                self.announcer.say(answer, with_chime=False).wait(ANSWER_TIMEOUT_SECONDS)
            self.wait_for_quiet_speaker()
            self.recorder.start()
            wait_seconds = self.follow_up_seconds

    # Wait until the speaker has finished everything queued (like a briefing a tool started), so John doesn't hear it
    # and answer the speaker instead of you
    def wait_for_quiet_speaker(self):
        gives_up = time.time() + SPEAKER_QUIET_TIMEOUT

        # Check a few times a second
        while self.announcer.busy() and time.time() < gives_up:
            time.sleep(0.2)

    # Listen until something is said within wait_seconds: a recording that caught a voice but no words is followed
    # by another while there's time. Returns the words ("" if nothing was understood), or None if nobody spoke.
    def listen(self, wait_seconds):
        ends = time.time() + wait_seconds

        # Record, and record again if nothing was understood and time is left
        while True:
            samples = self.record(max(0.5, ends - time.time()))
            heard = without_wake_phrase(self.transcribe(samples)) if samples else ""

            # Words heard, nobody spoke, or out of time: stop listening
            if heard or not samples or time.time() >= ends:
                self.recorder.stop()
                play_sound(self.announcer, "done")
                log.info("Heard: %r", heard)
                return heard if samples else None

    # Record from the microphone until speech ends; returns the samples, or [] if nobody spoke within wait_seconds.
    # The speech detector judges each moment, so quiet words count and beeps, alarms and background noise don't.
    def record(self, wait_seconds):
        self.speech.reset_states()
        recorded = []
        speech_seconds = 0.0
        quiet_seconds = 0.0
        best_chance = 0.0
        started = time.time()

        # Read frames until speech has been followed by a pause, or the time runs out
        while time.time() - started < MAX_RECORD_SECONDS:
            frame = self.recorder.read()
            recorded.append(frame)
            chance = float(self.speech.predict(numpy.array(frame, dtype=numpy.int16)))
            best_chance = max(best_chance, chance)

            # Frames the detector thinks are a voice count as speech, the rest as a pause
            if chance >= self.speech_chance:
                speech_seconds += FRAME_SECONDS
                quiet_seconds = 0.0
            else:
                quiet_seconds += FRAME_SECONDS

            # Done once speech is followed by a pause; give up if nobody starts talking in time
            if speech_seconds >= MIN_SPEECH_SECONDS and quiet_seconds >= SILENCE_SECONDS:
                break
            elif speech_seconds < MIN_SPEECH_SECONDS and time.time() - started > wait_seconds:
                log.info("No speech heard (the most voice-like moment scored %.2f; speech needs %.2f)", best_chance,
                         self.speech_chance)
                return []
        log.info("Recorded %.1f s (speech %.1f s)", len(recorded) * FRAME_SECONDS, speech_seconds)
        return [sample for frame in recorded for sample in frame]

    # Turn recorded samples into text with faster-whisper ("" if nothing was said)
    def transcribe(self, samples):
        audio = numpy.array(samples, dtype=numpy.float32) / 32768.0
        segments, info = self.whisper.transcribe(audio, language="en", beam_size=1, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()

    # Ask the brain, playing the thinking sound if it takes a while, and the error sound if it fails
    def answer(self, heard):
        thinking = threading.Timer(THINKING_AFTER_SECONDS, play_sound, args=(self.announcer, "thinking"))
        thinking.start()

        # A failed answer is said out loud rather than left as silence
        try:
            return self.brain.ask(heard)
        except Exception as error:
            log.error("John couldn't answer: %s", error)
            play_sound(self.announcer, "error")
            return "Sorry, I couldn't reach Claude just now."
        finally:
            thinking.cancel()
