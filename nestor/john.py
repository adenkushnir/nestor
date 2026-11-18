# Hey John: listens on the microphone for "Hey John" (the words, checked by a tiny Whisper model whenever the speech
# detector hears a short phrase, or a trained openWakeWord model if there is one), records until you stop talking,
# turns it into text on this computer (faster-whisper), asks the brain, and speaks the answer, then listens a few
# seconds for a follow-up. "Hey John, what time is it?" can be said in one breath.
import logging
import os
import re
import threading
import time
from collections import deque
import numpy
import openwakeword.utils
import pvrecorder
from faster_whisper import WhisperModel
from openwakeword.model import Model as WakeWordModel
from openwakeword.vad import VAD
from nestor import govee
from nestor import routines
from nestor import spotify
from nestor import timers
from nestor.brain import Brain
from nestor.config import PROJECT_DIR
from nestor.microphone import FRAME_LENGTH
from nestor.microphone import find_microphone
from nestor.sounds import play_sound
from nestor.trains import RailData
SAMPLE_RATE = 16000  # openWakeWord and Whisper both work at 16 kHz
FRAME_SECONDS = FRAME_LENGTH / SAMPLE_RATE
BASE_MODELS = ["hey_jarvis"]  # Fetching any built-in model also brings openWakeWord's shared audio and speech models
WAKE_PHRASE_SECONDS = 8  # The longest phrase checked for "Hey John" (long enough for a command in the same breath)
SILENCE_SECONDS = 0.8  # This long without speech after speaking ends the recording
MIN_SPEECH_SECONDS = 0.08  # One frame the detector is sure is a voice: enough for "no" or "stop"
FIRST_WAIT_SECONDS = 6  # After "Hey John", how long to wait for you to start talking
MAX_RECORD_SECONDS = 15
LOOKING_SECONDS = 15  # After showing a look on the lights, how long John waits for what you think of it
SPEAKER_QUIET_TIMEOUT = 120  # The longest John waits for the speaker to finish before listening for a follow-up
STOP_WORDS = {"stop", "cancel", "never mind", "nevermind", "nothing", "that's all", "thanks", "thank you"}
LEAD_IN_FRAMES = 6  # Audio kept from just before speech is noticed in a ringing gap, so a short "stop" isn't clipped
RING_COMMAND_SECONDS = 2.5  # How long a command in a ringing gap can take
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
                "forty-five": 45, "forty five": 45, "fifty": 50, "sixty": 60}
ANSWER_TIMEOUT_SECONDS = 180
THINKING_AFTER_SECONDS = 2.5  # Play the thinking sound if Claude takes longer than this
WAKE_PHRASE = re.compile(r"\b(hey|hi|okay|ok),?\s+(john|jon|jarvis)\b[,.!?]*", re.IGNORECASE)
# "Hey John" at the start of a phrase, with at most one word before it (like "um")
WAKE_START = re.compile(r"^\W*(?:\w+\W+)?(hey|hi|okay|ok)\W+(john|jon)\b\W*", re.IGNORECASE)
# A request ending in ", John" (the comma is how speech-to-text writes talking to John, not about him)
WAKE_END = re.compile(r"^\W*(\w.*?)\s*,\s*(john|jon)\W*$", re.IGNORECASE)
# Morning and night greetings, which wake John even without a comma ("goodnight John")
GREETING_END = re.compile(r"^\W*((?:good\s*)?(?:morning|night)|start (?:my|the) (?:day|morning))\W+(john|jon)\W*$",
                          re.IGNORECASE)
MAX_REQUEST_WORDS = 15  # Longer phrases ending in ", John" are probably talk, not a request
MORNING = re.compile(r"^(good )?morning|start (my|the) (day|morning)|i'?m up$")
NIGHT = re.compile(r"^(good ?night|night|going to bed)$")
log = logging.getLogger(__name__)

# What was said without the wake phrase, which sometimes ends up in the recording ("What time is it? Hey John")
def without_wake_phrase(heard):
    return " ".join(WAKE_PHRASE.sub(" ", heard).split()).strip(" ,")

# If John was called, what was asked ("" if nothing more was said); None if he wasn't. He's called by "Hey John" at
# the start (allowing one word before it, like "um"), by a short request ending in ", John", or by "good morning John"
# / "goodnight John".
def after_wake_words(heard):
    start = WAKE_START.search(heard)
    end = WAKE_END.search(heard) or GREETING_END.search(heard)

    # "Hey John" first, then a request or greeting ending with John
    if start:
        return heard[start.end():].strip()
    elif end and len(end.group(1).split()) <= MAX_REQUEST_WORDS:
        return end.group(1).strip()
    return None

# The routine some words ask for straight away, with no need for Claude: "start_my_day" for "good morning" or
# "start my day", "goodnight" for "goodnight" or "night"; None for anything else
def routine_for(words):
    words = " ".join(re.sub(r"[^\w\s']", " ", words.lower()).split())

    # Morning, night, or neither
    if MORNING.fullmatch(words):
        return "start_my_day"
    elif NIGHT.fullmatch(words):
        return "goodnight"
    return None

# How many minutes were asked for, e.g. "snooze for two minutes" or "snooze 10 min" (None if no number was said)
def spoken_minutes(words):
    digits = re.search(r"(\d+)\s*(minute|min)", words)
    named = [value for name, value in NUMBER_WORDS.items() if re.search(rf"\b{name}\s+minute", words)]

    # Digits first, then numbers in words, then "half an hour" and "an hour"
    if digits:
        return int(digits.group(1))
    elif named:
        return max(named)
    elif "half an hour" in words:
        return 30
    elif re.search(r"\ban hour\b", words):
        return 60
    return None

# What's missing before John can run, as a list of problems; empty when ready
def missing_setup(settings, secrets):
    needs = [(bool(secrets.get("ANTHROPIC_API_KEY")), "ANTHROPIC_API_KEY in .env (Nestor's own Claude key)")]
    return [problem for ready, problem in needs if not ready]

# Where the trained "Hey John" model file is (relative names are in the project folder)
def wake_word_path(settings):
    return os.path.join(PROJECT_DIR, settings.get("john_wake_word", "hey_john.onnx"))

# The trained "Hey John" model to use, or None to listen for the words instead (no training needed)
def wake_word_model(settings):
    path = wake_word_path(settings)
    return path if os.path.exists(path) else None

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
            model = wake_word_model(self.settings)
            openwakeword.utils.download_models(BASE_MODELS)  # The shared audio and speech models (only the first time)
            self.wake_word = WakeWordModel(wakeword_models=[model], inference_framework="onnx") if model else None
            self.threshold = float(self.settings.get("john_wake_threshold", 0.5))
            self.speech = VAD()
            self.wake_speech = VAD()  # Its own detector, for noticing phrases that might start with "Hey John"
            self.quick_whisper = None if model else WhisperModel(self.settings.get("john_wake_whisper", "tiny.en"),
                                                                 device="cpu", compute_type="int8")
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
        log.info("Hey John is listening on %s (%s)", self.recorder.selected_device,
                 "trained wake word model" if self.wake_word else "listening for the words")
        self.gap_speech = VAD()  # Its own detector, for "stop" between bursts of ringing
        recent = deque(maxlen=LEAD_IN_FRAMES)
        self.recorder.start()

        # Wait for the wake word, then hold a conversation; problems are logged and listening carries on
        while True:
            # Keep listening even if one conversation fails
            try:
                frame = self.recorder.read()
                recent.append(frame)

                # While something rings, a voice in the gap between bursts may be a plain "stop"; otherwise "Hey John"
                # starts a conversation (with whatever was said in the same breath)
                if self.voice_in_ringing_gap(frame):
                    self.ring_command(list(recent))
                    recent.clear()
                elif self.heard_wake_word(frame, recent):
                    self.talk(self.first_words)
                    recent.clear()
            except Exception as error:
                log.error("Hey John had a problem: %s", error)
                play_sound(self.announcer, "error")
                time.sleep(1)

            # Make sure the microphone is running again for the next "Hey John"
            if not self.recorder.is_recording:
                self.recorder.start()

    # True if "Hey John" was just heard. With a trained model, it scores each moment; otherwise, whenever the speech
    # detector hears a phrase (and the speaker isn't talking), a tiny Whisper model checks whether it starts with "Hey
    # John". Anything said after it in the same breath is kept in self.first_words.
    def heard_wake_word(self, frame, recent):
        self.first_words = None

        # A trained model decides by itself; the words need a voice first, and never the speaker's own
        if self.wake_word:
            score = max(self.wake_word.predict(numpy.array(frame, dtype=numpy.int16)).values())

            # Clear the model's memory of the audio, so it doesn't fire twice
            if score >= self.threshold:
                log.info("Heard the wake word (score %.2f)", score)
                self.wake_word.reset()
            return score >= self.threshold
        elif self.announcer.busy():
            self.wake_speech.reset_states()
            return False
        elif float(self.wake_speech.predict(numpy.array(frame, dtype=numpy.int16))) < self.speech_chance:
            return False
        self.wake_speech.reset_states()
        samples = self.record(1.0, lead_in=list(recent), max_seconds=WAKE_PHRASE_SECONDS, quietly=True)
        rest = after_wake_words(self.transcribe(samples, self.quick_whisper)) if samples else None

        # Not "Hey John": ignored (and not logged, as it's just people talking)
        if rest is None:
            return False

        # More was said in the same breath: hear it properly with the bigger model
        if rest:
            self.first_words = after_wake_words(self.transcribe(samples)) or without_wake_phrase(rest) or None
        log.info("Heard \"Hey John\"%s", f" and: {self.first_words!r}" if self.first_words else "")
        return True

    # Hold a conversation, pausing any ringing timer or alarm meanwhile so John can be heard; first_words is a
    # question already asked in the same breath as "Hey John"
    def talk(self, first_words=None):
        ringing = timers.scheduler and timers.scheduler.ringing

        # Ringing is cut off at once and waits while John talks; it carries on afterwards unless it was stopped
        if ringing:
            timers.scheduler.paused.set()
            self.announcer.interrupt()

        # The lights glow aqua while John listens and thinks
        if govee.lights:
            govee.lights.start_glow()

        # The ringing always resumes, the glow ends and the music comes back up, even if the conversation fails
        try:
            spotify.duck()  # Spotify on the phone or laptop goes quieter while John listens and answers
            self.conversation(first_words)
        finally:
            spotify.undo_duck()

            # Let ringing carry on
            if timers.scheduler:
                timers.scheduler.paused.clear()

            # The lights go back to what they showed
            if govee.lights:
                govee.lights.end_glow()

    # One conversation: listen (unless the question came with "Hey John"), answer, and keep going while follow-ups come
    # within a few seconds
    def conversation(self, first_words=None):
        heard = first_words
        wait_seconds = FIRST_WAIT_SECONDS

        # Asked in one breath: a "got it" tone and straight to the answer; otherwise the listening tone
        if heard:
            self.recorder.stop()
            play_sound(self.announcer, "done")
        else:
            play_sound(self.announcer, "listening")

        # Each round is one thing said and John's answer
        while True:
            heard = heard or self.listen(wait_seconds)

            # Nobody spoke: the conversation is over
            if heard is None:
                return
            words = heard.lower().strip(" .!?,")
            ringing = timers.scheduler and timers.scheduler.ringing

            # Snooze or stop what's ringing, end on "never mind", or run good morning / goodnight, without asking Claude
            if ringing and self.handle_ring_words(words):
                return
            elif not heard or words in STOP_WORDS:
                return
            elif routine_for(heard) == "start_my_day":
                routines.start_my_day(self.announcer, self.settings)
                return
            elif routine_for(heard) == "goodnight":
                routines.goodnight(self.announcer, self.settings)
                return
            answer = self.answer(heard)

            # Speak the answer (some tools, like goodnight, speak for themselves) and wait until it's done
            if answer:
                self.announcer.say(answer, with_chime=False).wait(ANSWER_TIMEOUT_SECONDS)
            self.wait_for_quiet_speaker()
            self.recorder.start()
            wait_seconds = LOOKING_SECONDS if self.brain.tools.showed_look else self.follow_up_seconds
            self.brain.tools.showed_look = False
            heard = None

            # No follow-up while music plays: the microphone would take the music for speech
            if spotify.music_playing():
                return

    # True if something is ringing, the speaker is in a quiet gap between bursts, and this moment sounds like a voice
    def voice_in_ringing_gap(self, frame):
        # Only between bursts of ringing; the detector starts fresh for each gap
        if not (timers.scheduler and timers.scheduler.ringing) or self.announcer.busy():
            self.gap_speech.reset_states()
            return False
        return float(self.gap_speech.predict(numpy.array(frame, dtype=numpy.int16))) >= self.speech_chance

    # A voice was heard while something rings: record the few words (with the moment before), and stop or snooze if
    # that's what was said; anything else is ignored
    def ring_command(self, lead_in):
        timers.scheduler.paused.set()  # No burst starts over the words

        # Ringing carries on afterwards unless the words stopped it
        try:
            samples = self.record(RING_COMMAND_SECONDS, lead_in=lead_in)
            words = without_wake_phrase(self.transcribe(samples)).lower().strip(" .!?,") if samples else ""
            log.info("Heard while ringing: %r", words)

            # Words that aren't stop or snooze don't end the ringing
            if not self.handle_ring_words(words):
                log.info("That wasn't stop or snooze, so it keeps ringing")
        finally:
            timers.scheduler.paused.clear()

    # Stop or snooze what's ringing if the words say so ("stop", "turn it off", "snooze for 5 minutes"); returns True
    # if they did
    def handle_ring_words(self, words):
        # Snooze (for as long as said), stop, or neither
        if "snooze" in words:
            return timers.scheduler.snooze(spoken_minutes(words) or timers.SNOOZE_MINUTES)
        elif words in STOP_WORDS or "stop" in words or words.endswith("off") or "enough" in words:
            return timers.scheduler.stop()
        else:
            return False

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
    # lead_in is audio already heard, where speech has started; quietly leaves out the log line (for phrases that may
    # just be people talking).
    def record(self, wait_seconds, lead_in=None, max_seconds=MAX_RECORD_SECONDS, quietly=False):
        self.speech.reset_states()
        recorded = list(lead_in or [])
        speech_seconds = MIN_SPEECH_SECONDS if lead_in else 0.0
        quiet_seconds = 0.0
        best_chance = 0.0
        started = time.time()

        # Read frames until speech has been followed by a pause, or the time runs out
        while time.time() - started < max_seconds:
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

        # Phrases that may just be people talking aren't logged
        if not quietly:
            log.info("Recorded %.1f s (speech %.1f s)", len(recorded) * FRAME_SECONDS, speech_seconds)
        return [sample for frame in recorded for sample in frame]

    # Turn recorded samples into text with faster-whisper ("" if nothing was said); model is the speech-to-text model
    # to use (the big one unless given)
    def transcribe(self, samples, model=None):
        audio = numpy.array(samples, dtype=numpy.float32) / 32768.0
        segments, info = (model or self.whisper).transcribe(audio, language="en", beam_size=1, vad_filter=True)
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
