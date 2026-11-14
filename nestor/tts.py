# Turns text into speech mp3 files with Microsoft Edge neural voices, cached so repeated messages are instant
import asyncio
import hashlib
import os
import time
import edge_tts
from nestor.config import CACHE_DIR
CACHE_MAX_AGE_SECONDS = 24 * 60 * 60

# Create the speech mp3 for this text (or reuse a cached one) and return its file name in the cache folder
def make_speech(text, voice, rate):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_key = hashlib.sha1(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:16]
    file_name = f"speech-{cache_key}.mp3"
    file_path = os.path.join(CACHE_DIR, file_name)

    # Reuse the cached file, or ask the TTS service for a new one
    if os.path.exists(file_path):
        os.utime(file_path)  # Mark as recently used so the cleanup keeps it
    else:
        download_speech(text, voice, rate, file_path)
    return file_name

# Ask the TTS service for the speech, trying twice because it occasionally returns no audio
def download_speech(text, voice, rate, file_path):
    partial_path = file_path + ".part"

    # First try, then one retry; the second failure is passed on
    for attempt in range(2):
        # A failed attempt removes its half-written file
        try:
            asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(partial_path))
            os.replace(partial_path, file_path)  # Only a complete file gets the real name
            return
        except Exception:
            # Remove the half-written file
            if os.path.exists(partial_path):
                os.remove(partial_path)

            # Give up after the second try
            if attempt == 1:
                raise

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
