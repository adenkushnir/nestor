# The microphone: finding the one to use, how loud a moment of sound is, and a test that shows your levels
import logging
import math
import time
import numpy
import pvrecorder
FRAME_LENGTH = 1280  # 80 ms of audio, the step openWakeWord works in
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

# Show, for a few seconds, how loud the microphone hears the room and how sure the speech detector is that it's a voice
# (quiet first, then talking), to check John will hear you from where you sit
def mic_test(settings, seconds=12):
    from openwakeword.vad import VAD  # Loaded here only: the test is the one place outside John that needs it
    detector = VAD()
    threshold = float(settings.get("john_speech_threshold", 0.4))
    recorder = pvrecorder.PvRecorder(frame_length=FRAME_LENGTH,
                                     device_index=find_microphone(settings.get("microphone", "")))
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
