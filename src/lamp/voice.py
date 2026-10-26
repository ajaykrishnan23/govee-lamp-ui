"""On-device speech-to-text fallback for browsers without built-in recognition."""
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class Transcriber:
    def __init__(self, model_size: str = "small.en"):
        self.model_size = model_size
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel  # slow import; only when first needed

                log.info("loading whisper model %s", self.model_size)
                self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, path: Path) -> str:
        segments, _ = self._load().transcribe(str(path), language="en", beam_size=1, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
