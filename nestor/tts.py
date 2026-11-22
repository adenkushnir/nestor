# Turns text into speech mp3 files with Microsoft Edge neural voices, cached so repeated messages are instant
import asyncio
import hashlib
import os
import time
import edge_tts
from nestor.config import CACHE_DIR
CACHE_MAX_AGE_SECONDS = 24 * 60 * 60

# Create the speech mp3 for this text (or reuse a cached one) and return its file name in the cache folder; pitch
# like "-4Hz" makes the voice lower
def make_speech(text, voice, rate, pitch="+0Hz"):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_key = hashlib.sha1(f"{voice}|{rate}|{pitch}|{text}".encode("utf-8")).hexdigest()[:16]
    file_name = f"speech-{cache_key}.mp3"
    file_path = os.path.join(CACHE_DIR, file_name)

    # Reuse the cached file, or ask the TTS service for a new one
    if os.path.exists(file_path):
        os.utime(file_path)  # Mark as recently used so the cleanup keeps it
    else:
        download_speech(text, voice, rate, file_path, pitch)
    return file_name

# Ask the TTS service for the speech, trying twice because it occasionally returns no audio
def download_speech(text, voice, rate, file_path, pitch="+0Hz"):
    partial_path = file_path + ".part"

    # First try, then one retry; the second failure is passed on
    for attempt in range(2):
        # A failed attempt removes its half-written file
        try:
            asyncio.run(edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(partial_path))
            os.replace(partial_path, file_path)  # Only a complete file gets the real name
            return
        except Exception:
            # Remove the half-written file
            if os.path.exists(partial_path):
                os.remove(partial_path)

            # Give up after the second try
            if attempt == 1:
                raise

# How many seconds into the speech for this text the last word ends (the mp3 carries about a second of silence after
# it), asked from the TTS service
def speech_length(text, voice, rate, pitch="+0Hz"):
    # Read the word timings as the speech streams in
    async def last_word_end():
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
        end = 0.0

        # Audio chunks are skipped; each word says where it ends (in 100-nanosecond units)
        async for chunk in communicate.stream():
            # Only the word timings count
            if chunk["type"] == "WordBoundary":
                end = max(end, (chunk["offset"] + chunk["duration"]) / 10_000_000)
        return end
    return asyncio.run(last_word_end())

# Delete cached speech files older than a day so the cache folder doesn't grow forever
def clean_cache():
    # Nothing to clean before the first message
    if not os.path.isdir(CACHE_DIR):
        return
    oldest_allowed = time.time() - CACHE_MAX_AGE_SECONDS

    # Check every file in the cache
    for file_name in os.listdir(CACHE_DIR):
        file_path = os.path.join(CACHE_DIR, file_name)

        # Only old speech files go; the chime stays
        if file_name.startswith("speech-") and os.path.getmtime(file_path) < oldest_allowed:
            os.remove(file_path)
