# John's short spoken clips in his own voice: the word he says when you call him and the line he says while a longer
# answer is on its way, a different one each time. Made once (the speech cache keeps them) and played like his tones.
import logging
import os
import random
import threading
from nestor import tts
from nestor.config import CACHE_DIR
from nestor.storage import read_json
from nestor.storage import write_json
# The clips, as one line each with no comma before the title, so they're said in one breath
CLIPS = {
    "start": ["Yes boss?", "Go on.", "Talk to me chief.", "I'm listening.", "Yes sir?", "What'll it be?",
              "Go ahead boss.", "Let's hear it."],
    "thinking": ["One sec chief.", "Let me look into that.", "Give me a moment.", "Hang on sir.", "Checking.",
                 "Bear with me boss.", "Let me dig into it."],
    "missed": ["Didn't catch that boss.", "Say again chief?", "Come again?", "One more time sir?",
               "Didn't quite get that."],
}
MP3_BYTES_PER_SECOND = 6000  # Edge voices come as 48 kbit/s mp3
LENGTHS_PATH =os.path.join(CACHE_DIR, "clip-lengths.json")  # Clip file name: seconds until its last word ends
AFTER_WORDS_SECONDS = 0.15  # A clip counts as played this long after its last word
last_played = {}  # Kind of clip: the text played last time, so the next is different
lengths_lock = threading.Lock()
log = logging.getLogger(__name__)

# Make one clip's mp3 (or reuse it from the cache); returns (file name, seconds until it's said). The mp3 carries
# about a second of silence after the words, so the clip is timed by where its last word ends.
def ensure_clip(announcer, text):
    file_name = tts.make_speech(text, announcer.voice, announcer.voice_rate, announcer.voice_pitch)

    # Each clip's timing is asked for once and remembered
    with lengths_lock:
        lengths = read_json(LENGTHS_PATH, {})

        # A clip not timed yet (without word timings, the whole file's length is used)
        if file_name not in lengths:
            whole_file = os.path.getsize(os.path.join(CACHE_DIR, file_name)) / MP3_BYTES_PER_SECOND
            lengths[file_name] = tts.speech_length(text, announcer.voice, announcer.voice_rate,
                                                   announcer.voice_pitch) or whole_file
            write_json(LENGTHS_PATH, lengths)
    return file_name, lengths[file_name] + AFTER_WORDS_SECONDS

# Make every clip ahead of time in the background, so the first "Hey John" doesn't wait for one
def prepare(announcer):
    # One clip after another; a clip that can't be made now is made when it's first played
    def make_all():
        # Each kind and each line
        for lines in CLIPS.values():
            for text in lines:
                # The speech service may be unreachable for a moment
                try:
                    ensure_clip(announcer, text)
                except Exception as error:
                    log.warning("Couldn't make John's clip %r: %s", text, error)
    threading.Thread(target=make_all, name="john-clips", daemon=True).start()

# Play a clip of this kind ("start", "thinking" or "missed"), never the same one twice in a row; returns the event set
# once it has played
def play_clip(announcer, kind):
    choices = [text for text in CLIPS[kind] if text != last_played.get(kind)]
    text = random.choice(choices)
    last_played[kind] = text
    file_name, seconds = ensure_clip(announcer, text)
    return announcer.sound(file_name, seconds, content_type="audio/mpeg")
