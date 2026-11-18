# The microphone: finding the one to use, how loud a moment of sound is, and a test that shows your levels
import logging
import math
import time
import pvrecorder
FRAME_LENGTH = 1280  # 80 ms of audio, the step openWakeWord works in
MIN_SPEECH_LEVEL = 120  # Default loudness (RMS) below which nothing counts as speech; john_speech_level changes it
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

# Show the microphone's loudness for a few seconds (quiet first, then talking), to pick john_speech_level
def mic_test(settings, seconds=12):
    recorder = pvrecorder.PvRecorder(frame_length=FRAME_LENGTH,
                                     device_index=find_microphone(settings.get("microphone", "")))
    print(f"Microphone: {recorder.selected_device}")
    print("Stay quiet for the first 4 seconds, then talk normally from where you sit.")
    quiet_levels = []
    speech_levels = []
    recorder.start()
    started = time.time()

    # Print a bar for every few frames until the time is up
    while time.time() - started < seconds:
        level = loudness(recorder.read())
        part = quiet_levels if time.time() - started < 4 else speech_levels
        part.append(level)
        print(f"{'quiet ' if part is quiet_levels else 'talk  '}{level:7.0f} {'#' * min(60, int(level / 20))}")
    recorder.stop()
    recorder.delete()
    background = sum(quiet_levels) / max(1, len(quiet_levels))
    speaking = sorted(speech_levels)[int(len(speech_levels) * 0.8)] if speech_levels else 0
    print(f"Background: about {background:.0f}. Talking: about {speaking:.0f} at its louder moments.")
    print(f"A good john_speech_level is about {max(30, (background * 2 + speaking) / 3):.0f} "
          f"(now {float(settings.get('john_speech_level', MIN_SPEECH_LEVEL)):.0f}).")
