# Speech-to-text for Hey John: faster-whisper on a PC, or Vosk on a small board (like the Tinker Board), where Whisper
# is too slow and overheats the chip, or OpenAI in the cloud for what's asked after "Hey John" (the board's Vosk still
# listens for "Hey John" itself). Each turns 16 kHz recorded samples into text.
import io
import json
import logging
import os
import time
import wave
import numpy
from nestor.config import PROJECT_DIR
SAMPLE_RATE = 16000
DEFAULT_VOSK_MODEL = "vosk-model-small-en-us-0.15"
DEFAULT_OPENAI_MODEL = "gpt-transcribe"
OPENAI_TIMEOUT_SECONDS = 8  # Slower than this and the board's own speech-to-text hears it instead
# Words John hears often that a speech model might otherwise spell wrong
KEYWORDS = ["John", "Nestor", "Datebook", "NJ Transit", "New Brunswick", "Penn Station", "Govee", "Spotify", "snooze",
            "foil"]
log = logging.getLogger(__name__)

# faster-whisper with one of its models (e.g. "small.en"); writes punctuation, so "..., John" can be told apart
class WhisperText:
    punctuates = True

    # Load the model (the first time downloads it)
    def __init__(self, model_name):
        from faster_whisper import WhisperModel  # Imported here only: it doesn't install on the board
        self.name = f"Whisper {model_name}"
        self.model = WhisperModel(model_name, device="cpu", compute_type="int8")

    # The words in the samples ("" if nothing was said)
    def transcribe(self, samples):
        audio = numpy.array(samples, dtype=numpy.float32) / 32768.0
        segments, info = self.model.transcribe(audio, language="en", beam_size=1, vad_filter=True)
        return " ".join(segment.text.strip() for segment in segments).strip()

# Vosk with a model folder (relative names are in the project folder); lowercase words, no punctuation
class VoskText:
    punctuates = False

    # Load the model from its folder (downloaded by hand, see board/README.md)
    def __init__(self, model_folder):
        import vosk  # Imported here only: the PC doesn't need it
        vosk.SetLogLevel(-1)
        path = os.path.join(PROJECT_DIR, model_folder)

        # Without the folder Vosk would fail with an unclear error
        if not os.path.isdir(path):
            raise FileNotFoundError(f"The Vosk model folder {path} isn't there (see board/README.md)")
        self.name = f"Vosk {os.path.basename(path)}"
        self.vosk = vosk
        self.model = vosk.Model(path)

    # The words in the samples ("" if nothing was said)
    def transcribe(self, samples):
        recognizer = self.vosk.KaldiRecognizer(self.model, SAMPLE_RATE)
        recognizer.AcceptWaveform(numpy.array(samples, dtype=numpy.int16).tobytes())
        return json.loads(recognizer.FinalResult()).get("text", "").strip()

# OpenAI's speech-to-text in the cloud (gpt-transcribe): accurate and quick even on a small board, and it writes
# punctuation. If the service can't be reached in time, the board's own speech-to-text (fallback) hears it instead.
class OpenAIText:
    punctuates = True

    # Connect with Nestor's own OpenAI key
    def __init__(self, model_name, api_key, fallback):
        from openai import OpenAI  # Imported here only: it's needed only when John hears in the cloud
        self.name = f"OpenAI {model_name}, or {fallback.name} if it can't be reached"
        self.model_name = model_name
        self.client = OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT_SECONDS, max_retries=0)
        self.fallback = fallback

    # The words in the samples ("" if nothing was said)
    def transcribe(self, samples):
        started = time.time()

        # No internet, a slow answer or a problem with the key: the board hears it instead
        try:
            result = self.client.audio.transcriptions.create(model=self.model_name,
                                                             file=("speech.wav", wav_bytes(samples), "audio/wav"),
                                                             languages=["en"], keywords=KEYWORDS)
        except Exception as error:
            log.warning("OpenAI couldn't hear it (%s); %s hears it instead", error, self.fallback.name)
            return self.fallback.transcribe(samples)
        log.info("OpenAI heard it in %.1f s", time.time() - started)
        return (result.text or "").strip()

# The samples as a mono 16 kHz WAV file in memory
def wav_bytes(samples):
    buffer = io.BytesIO()

    # 16-bit samples, one channel
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(numpy.array(samples, dtype=numpy.int16).tobytes())
    return buffer.getvalue()

# The speech-to-text John uses for whole requests, from the speech_to_text setting ("whisper", "vosk" or "openai");
# "openai" needs OPENAI_API_KEY in .env and uses Vosk without it
def load_speech_to_text(settings, secrets=None):
    choice = settings.get("speech_to_text", "whisper")
    vosk_model = settings.get("vosk_model") or DEFAULT_VOSK_MODEL

    # The cloud (with Vosk to fall back on), Vosk on the board, or Whisper everywhere else
    if choice == "openai" and (secrets or {}).get("OPENAI_API_KEY"):
        model_name = settings.get("openai_speech_model") or DEFAULT_OPENAI_MODEL
        return OpenAIText(model_name, secrets["OPENAI_API_KEY"], VoskText(vosk_model))
    elif choice in ("openai", "vosk"):
        # Without a key the cloud can't be used
        if choice == "openai":
            log.warning("speech_to_text is \"openai\" but .env has no OPENAI_API_KEY, so John hears with Vosk")
        return VoskText(vosk_model)
    return WhisperText(settings.get("whisper_model", "small.en"))

# The speech-to-text for checking short phrases for "Hey John": a tiny Whisper model on a PC; Vosk is quick enough to
# use the same model for both, so that one is passed back. With OpenAI, "Hey John" is still listened for on the board,
# so only what's said after it goes to the cloud.
def load_wake_speech_to_text(settings, main):
    # Whisper needs its tiny model for speed; OpenAI listens with its fallback; Vosk is already quick
    if isinstance(main, WhisperText):
        return WhisperText(settings.get("john_wake_whisper", "tiny.en"))
    elif isinstance(main, OpenAIText):
        return main.fallback
    return main
