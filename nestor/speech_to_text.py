# Speech-to-text for Hey John: faster-whisper on a PC, or Vosk on a small board (like the Tinker Board), where Whisper
# is too slow and overheats the chip. Each turns 16 kHz recorded samples into text.
import json
import logging
import os
import numpy
from nestor.config import PROJECT_DIR
SAMPLE_RATE = 16000
DEFAULT_VOSK_MODEL = "vosk-model-small-en-us-0.15"
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

# The speech-to-text John uses for whole requests, from the speech_to_text setting ("whisper" or "vosk")
def load_speech_to_text(settings):
    # Vosk on the board, Whisper everywhere else
    if settings.get("speech_to_text", "whisper") == "vosk":
        return VoskText(settings.get("vosk_model") or DEFAULT_VOSK_MODEL)
    return WhisperText(settings.get("whisper_model", "small.en"))

# The speech-to-text for checking short phrases for "Hey John": a tiny Whisper model on a PC; Vosk is quick enough to
# use the same model for both, so that one is passed back
def load_wake_speech_to_text(settings, main):
    # Whisper needs its tiny model for speed; Vosk is already quick
    if isinstance(main, WhisperText):
        return WhisperText(settings.get("john_wake_whisper", "tiny.en"))
    return main
