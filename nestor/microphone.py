# The microphone: finding the one to use, reading it (pvrecorder on a PC, Linux's arecord on boards pvrecorder doesn't
# support, like the Tinker Board), how loud a moment of sound is, and a test that shows your levels
import logging
import math
import re
import subprocess
import time
import numpy
FRAME_LENGTH = 1280  # 80 ms of audio, the step openWakeWord works in
log = logging.getLogger(__name__)

# pvrecorder isn't installed on the Tinker Board, which reads the microphone with arecord instead
try:
    import pvrecorder
except ImportError:
    pvrecorder = None

# Reads the microphone through Linux's arecord, in the same frames and with the same calls as pvrecorder
class ArecordMicrophone:
    # Pick the sound card whose name contains the setting (e.g. "USB"), or the system's default
    def __init__(self, setting):
        self.device, self.selected_device = arecord_device(setting)
        self.process = None

    # True while arecord is running
    @property
    def is_recording(self):
        return self.process is not None and self.process.poll() is None

    # Start recording: 16 kHz, 16-bit, mono, raw samples on its output
    def start(self):
        # Already running: nothing to do
        if self.is_recording:
            return
        self.process = subprocess.Popen(["arecord", "-q", "-D", self.device, "-f", "S16_LE", "-r", "16000", "-c", "1",
                                         "-t", "raw"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    # The next 80 ms of samples as a list of numbers (waits for them)
    def read(self):
        data = self.process.stdout.read(FRAME_LENGTH * 2)

        # arecord stopping early means the microphone went away
        if len(data) < FRAME_LENGTH * 2:
            raise OSError(f"The microphone {self.selected_device} stopped sending sound")
        return numpy.frombuffer(data, dtype=numpy.int16).tolist()

    # Stop recording (anything not yet read is dropped, like pvrecorder)
    def stop(self):
        # Only a running arecord needs stopping
        if self.process:
            self.process.kill()
            self.process.wait()
            self.process = None

    # Same as stop, for pvrecorder's delete()
    def delete(self):
        self.stop()

# The arecord device ("plughw:CARD=...,DEV=...") and name of the sound card whose name contains the setting, or the
# system's default
def arecord_device(setting):
    listing = subprocess.run(["arecord", "-l"], capture_output=True, text=True).stdout
    cards = re.findall(r"^card \d+: (\S+) \[([^\]]*)\], device (\d+):", listing, re.MULTILINE)

    # The first card whose short or full name contains the setting, ignoring case
    for card_id, name, device in cards:
        # A match is used as a plug device, which converts to the rate and format asked for
        if setting and (setting.lower() in name.lower() or setting.lower() in card_id.lower()):
            return f"plughw:CARD={card_id},DEV={device}", name

    # A setting that matches nothing falls back to the default, with a note of what there is
    if setting:
        log.warning("No microphone matches %r; using the default. Sound cards: %s", setting,
                    ", ".join(name for card_id, name, device in cards))
    return "default", "the default microphone"

# The microphone named by the setting: pvrecorder where it works, arecord where it doesn't (pvrecorder only knows
# some processors)
def open_microphone(setting):
    # Without pvrecorder, arecord is the only way
    if pvrecorder is None:
        return ArecordMicrophone(setting)

    # pvrecorder refuses unknown processors when listing devices
    try:
        return pvrecorder.PvRecorder(frame_length=FRAME_LENGTH, device_index=find_microphone(setting))
    except Exception as error:
        log.info("Reading the microphone with arecord (pvrecorder can't: %s)", error)
        return ArecordMicrophone(setting)

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

# Show, for a few seconds, how loud the microphone hears the room and how sure the speech detector is that it's a voice
# (quiet first, then talking), to check John will hear you from where you sit
def mic_test(settings, seconds=12):
    from openwakeword.vad import VAD  # Loaded here only: the test is the one place outside John that needs it
    detector = VAD()
    threshold = float(settings.get("john_speech_threshold", 0.4))
    recorder = open_microphone(settings.get("microphone", ""))
    print(f"Microphone: {recorder.selected_device}")
    print("Stay quiet for the first 4 seconds, then talk normally from where you sit (try short words like \"yes\").")
    quiet_hits = 0
    talk_hits = 0
    recorder.start()
    started = time.time()

    # One line per moment: loudness, and the speech detector's score as a bar
    while time.time() - started < seconds:
        frame = recorder.read()
        chance = float(detector.predict(numpy.array(frame, dtype=numpy.int16)))
        talking = time.time() - started >= 4
        quiet_hits += chance >= threshold and not talking
        talk_hits += chance >= threshold and talking
        print(f"{'talk ' if talking else 'quiet'} loud {loudness(frame):6.0f}  voice {chance:4.2f} "
              f"{'#' * int(chance * 40)}{'  <- speech' if chance >= threshold else ''}")
    recorder.stop()
    recorder.delete()
    print(f"Moments counted as speech: {quiet_hits} while quiet (should be about 0), {talk_hits} while talking "
          f"(should be many). Speech needs a voice score of {threshold:.2f} (john_speech_threshold).")
