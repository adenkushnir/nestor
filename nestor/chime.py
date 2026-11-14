# Generates the short two-note chime that plays before announcements (made in code, so no sound file in git)
import math
import os
import struct
import wave
from nestor.config import CACHE_DIR
CHIME_FILE = "chime.wav"
SAMPLE_RATE = 44100

# Write the chime WAV into the cache folder if it isn't there yet, and return its file name
def ensure_chime():
    os.makedirs(CACHE_DIR, exist_ok=True)
    chime_path = os.path.join(CACHE_DIR, CHIME_FILE)

    # Build the chime only once
    if not os.path.exists(chime_path):
        samples = bell_note(880.0, 0.2) + bell_note(1318.5, 0.45)
        with wave.open(chime_path, "wb") as chime_wav:
            chime_wav.setnchannels(1)
            chime_wav.setsampwidth(2)
            chime_wav.setframerate(SAMPLE_RATE)
            chime_wav.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))
    return CHIME_FILE

# Make one soft bell-like note: a sine wave with a quick fade-in and a long fade-out
def bell_note(frequency, seconds):
    sample_count = int(SAMPLE_RATE * seconds)
    samples = []

    # Each sample is the sine wave scaled by the fade envelope
    for i in range(sample_count):
        envelope = min(1.0, i / 300) * math.exp(-4.0 * i / sample_count)
        samples.append(int(11000 * envelope * math.sin(2 * math.pi * frequency * i / SAMPLE_RATE)))
    return samples
