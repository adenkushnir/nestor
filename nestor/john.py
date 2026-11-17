# Hey John: listens on the microphone for "Hey John" (openWakeWord), records until you stop talking, turns it into text
# on this computer (faster-whisper), asks the brain, and speaks the answer, then listens a few seconds for a follow-up
import logging
import math
import os
import threading
import time
import numpy
import openwakeword.utils
import pvrecorder
from faster_whisper import WhisperModel
from openwakeword.model import Model as WakeWordModel
from nestor.brain import Brain
from nestor.config import PROJECT_DIR
from nestor.sounds import play_sound
SAMPLE_RATE = 16000  # openWakeWord and Whisper both work at 16 kHz
FRAME_LENGTH = 1280  # 80 ms of audio, the step openWakeWord works in
FALLBACK_WAKE_WORD = "hey_jarvis"  # openWakeWord's built-in model, used until the "Hey John" model is trained
MIN_SPEECH_LEVEL = 350  # Loudness (RMS) below this never counts as speech
SPEECH_OVER_NOISE = 2.5  # Speech must be this many times louder than the room's background
SILENCE_SECONDS = 0.9  # This much quiet after speaking ends the recording
MIN_SPEECH_SECONDS = 0.6  # Shorter sounds (like John's own beep) don't end the wait for speech
FIRST_WAIT_SECONDS = 6  # After "Hey John", how long to wait for you to start talking
MAX_RECORD_SECONDS = 15
STOP_WORDS = {"stop", "cancel", "never mind", "nevermind", "nothing", "that's all", "thanks", "thank you"}
ANSWER_TIMEOUT_SECONDS = 180
THINKING_AFTER_SECONDS = 2.5  # Play the thinking sound if Claude takes longer than this
log = logging.getLogger(__name__)

# The loudness of one frame of 16-bit samples (root mean square)
def loudness(frame):
    return math.sqrt(sum(sample * sample for sample in frame) / len(frame)) if frame else 0.0

# The index of the microphone whose name contains the setting (e.g. "USB"), or -1 for the computer's default
def find_microphone(setting):
    names = pvrecorder.PvRecorder.get_available_devices()

    # Match the setting against each microphone's name, ignoring case
    for index, name in enumerate(names):
        # The first microphone whose name contains the setting
        if setting and setting.lower() in name.lower():
            return index

    # A setting that matches nothing falls back to the default, with a note of what there is
    if setting:
        log.warning("No microphone matches %r; using the default. Microphones: %s", setting, ", ".join(names))
    return -1

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
        self.follow_up_seconds = float(settings.get("john_follow_up_seconds", 8))
        self.noise = MIN_SPEECH_LEVEL / SPEECH_OVER_NOISE
        threading.Thread(target=self.run, name="hey-john", daemon=True).start()

    # Set up the wake word, microphone, speech-to-text and brain, then wait for "Hey John" forever
    def run(self):
        # Anything that stops John from starting is logged; the rest of Nestor keeps running
        try:
            model, self.phrase = wake_word_choice(self.settings)
            openwakeword.utils.download_models([FALLBACK_WAKE_WORD])  # The shared audio models (only the first time)
            self.wake_word = WakeWordModel(wakeword_models=[model], inference_framework="onnx")
            self.threshold = float(self.settings.get("john_wake_threshold", 0.5))
            self.recorder = pvrecorder.PvRecorder(frame_length=FRAME_LENGTH,
                                                  device_index=find_microphone(self.settings.get("microphone", "")))
            log.info("Loading speech-to-text (%s); the first time downloads it",
                     self.settings.get("whisper_model", "small.en"))
            self.whisper = WhisperModel(self.settings.get("whisper_model", "small.en"), device="cpu",
                                        compute_type="int8")
            self.brain = Brain(self.announcer, self.settings, self.secrets["ANTHROPIC_API_KEY"])
        except Exception as error:
            log.error("Hey John couldn't start: %s", error)
            return
        log.info("Hey John is listening on %s: say \"%s\"", self.recorder.selected_device, self.phrase)
        self.recorder.start()

        # Wait for the wake word, then hold a conversation; problems are logged and listening carries on
        while True:
            # Keep listening even if one conversation fails
            try:
                frame = self.recorder.read()
                self.learn_noise(frame)

                scores = self.wake_word.predict(numpy.array(frame, dtype=numpy.int16))

                # "Hey John" heard: talk, then clear the wake word's memory of the audio so it doesn't fire twice
                if max(scores.values()) >= self.threshold:
                    log.info("Heard the wake word (score %.2f)", max(scores.values()))
                    self.wake_word.reset()
                    self.conversation()
                    self.wake_word.reset()
            except Exception as error:
                log.error("Hey John had a problem: %s", error)
                play_sound(self.announcer, "error")
                time.sleep(1)

            # Make sure the microphone is running again for the next "Hey John"
            if not self.recorder.is_recording:
                self.recorder.start()

    # Keep a slow average of the room's background loudness, so speech is judged against it
    def learn_noise(self, frame):
        self.noise = 0.98 * self.noise + 0.02 * loudness(frame)

    # One conversation: listen, answer, and keep going while follow-ups come within a few seconds
    def conversation(self):
        play_sound(self.announcer, "listening")
        wait_seconds = FIRST_WAIT_SECONDS

        # Each round is one thing said and John's answer
        while True:
            samples = self.record(wait_seconds)
            self.recorder.stop()
            play_sound(self.announcer, "done")

            # Nothing said: the conversation is over
            if not samples:
                return
            heard = self.transcribe(samples)
            log.info("Heard: %r", heard)

            # Silence, or "stop" / "never mind", ends it without asking Claude
            if not heard or heard.lower().strip(" .!?,") in STOP_WORDS:
                return
            answer = self.answer(heard)

            # Speak the answer (some tools, like goodnight, speak for themselves) and wait until it's done
            if answer:
                self.announcer.say(answer, with_chime=False).wait(ANSWER_TIMEOUT_SECONDS)
            self.recorder.start()
            wait_seconds = self.follow_up_seconds

    # Record from the microphone until speech ends; returns the samples, or [] if nobody spoke within wait_seconds
    def record(self, wait_seconds):
        frame_seconds = FRAME_LENGTH / SAMPLE_RATE
        threshold = max(MIN_SPEECH_LEVEL, self.noise * SPEECH_OVER_NOISE)
        recorded = []
        speech_seconds = 0.0
        quiet_seconds = 0.0
        started = time.time()

        # Read frames until enough speech has been followed by quiet, or the time runs out
        while time.time() - started < MAX_RECORD_SECONDS:
            frame = self.recorder.read()
            recorded.append(frame)

            # Loud frames count as speech, quiet ones as a pause
            if loudness(frame) >= threshold:
                speech_seconds += frame_seconds
                quiet_seconds = 0.0
            else:
                quiet_seconds += frame_seconds

            # Done once real speech is followed by a pause; give up if nobody starts talking in time
            if speech_seconds >= MIN_SPEECH_SECONDS and quiet_seconds >= SILENCE_SECONDS:
                break
            elif speech_seconds < MIN_SPEECH_SECONDS and time.time() - started > wait_seconds:
                return []
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
