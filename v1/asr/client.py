import json
from pathlib import Path
import subprocess
from typing import Optional, Tuple

from dictation.asr.client import (
    DEFAULT_MODEL,
    NemotronASRClient as DictationNemotronASRClient,
)


class NemotronASRAdapter:
    """Adapts the local dictation ASR client to V1's ASR contract."""

    def __init__(
        self,
        model_id: Optional[str] = None,
        sample_rate: int = 16000,
        client: Optional[DictationNemotronASRClient] = None,
    ):
        model_id = model_id or DEFAULT_MODEL
        self.client = client or DictationNemotronASRClient(
            model_id=model_id,
            sample_rate=sample_rate,
        )
        self._model_verified = False

    def _ensure_model_downloaded(self) -> None:
        if self._model_verified:
            return
        if not self.client.handy_exe.exists():
            raise FileNotFoundError(
                f"Handy ASR engine not found at: {self.client.handy_exe}"
            )
        if not self.client.is_model_downloaded():
            raise FileNotFoundError(
                f"ASR model '{self.client.model_id}' is not downloaded in Handy. "
                "Download it in Handy's model settings before transcribing audio."
            )
        self._model_verified = True

    def transcribe(self, audio_path: str | Path) -> Tuple[str, float]:
        """Transcribe a WAV file and return V1's (text, latency_ms) tuple."""
        self._ensure_model_downloaded()
        text, latency_ms, _ = self.client.transcribe_wav_file(audio_path)
        return text, latency_ms

    def transcribe_pcm_bytes(self, pcm_bytes: bytes) -> Tuple[str, float]:
        """Transcribe raw 16-bit mono PCM bytes without a caller-managed WAV file."""
        self._ensure_model_downloaded()
        text, latency_ms, _ = self.client.transcribe_pcm_bytes(pcm_bytes)
        return text, latency_ms
