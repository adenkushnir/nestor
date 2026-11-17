# John's short sounds, like Google Assistant's: listening, done, thinking and error (made in code, so no sound files
# in git)
import os
import struct
import wave
from nestor.chime import SAMPLE_RATE
from nestor.chime import bell_note
from nestor.config import CACHE_DIR
# Each sound: its notes as (frequency, seconds), and how loud it is compared with the chime
SOUNDS = {
    "listening": ([(659.3, 0.11), (987.8, 0.24)], 1.0),  # Rising: "I'm listening"
    "done": ([(987.8, 0.11), (659.3, 0.24)], 0.9),  # Falling: "got it" / stopped listening
    "thinking": ([(784.0, 0.16), (784.0, 0.16), (784.0, 0.22)], 0.45),  # Three soft taps while Claude works
    "error": ([(392.0, 0.18), (311.1, 0.34)], 1.0),  # Two low notes: something went wrong
}

# Write a sound's WAV into the cache folder if it isn't there yet; returns (file name, length in seconds)
def ensure_sound(name):
    notes, loudness = SOUNDS[name]
    file_name = f"sound-{name}.wav"
    sound_path = os.path.join(CACHE_DIR, file_name)
    seconds = sum(length for frequency, length in notes)

    # Build each sound only once
    if not os.path.exists(sound_path):
        os.makedirs(CACHE_DIR, exist_ok=True)
        samples = [int(sample * loudness) for frequency, length in notes for sample in bell_note(frequency, length)]
        with wave.open(sound_path, "wb") as sound_wav:
            sound_wav.setnchannels(1)
            sound_wav.setsampwidth(2)
            sound_wav.setframerate(SAMPLE_RATE)
            sound_wav.writeframes(b"".join(struct.pack("<h", sample) for sample in samples))
    return file_name, seconds

# Play one of John's sounds on the speaker (queued like any announcement); returns the event set once it has played
def play_sound(announcer, name):
    file_name, seconds = ensure_sound(name)
    return announcer.sound(file_name, seconds)
