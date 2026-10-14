import io
import time
import wave
from pathlib import Path
from typing import Tuple
import requests


class IndicASRClient:
    """
    Client for Indic Conformer ASR endpoint.
    Handles WAV file packaging and transcription requests.
    """

    def __init__(self, endpoint: str, timeout_seconds: int = 20, sample_rate: int = 16000):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.sample_rate = sample_rate
        self.session = requests.Session()

    def pcm_to_wav_bytes(self, pcm_bytes: bytes) -> bytes:
        """Encodes raw 16kHz 16-bit mono PCM into a standard WAV byte stream."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(pcm_bytes)
        return buffer.getvalue()

    def transcribe_wav_bytes(self, wav_bytes: bytes, filename: str = "stream_chunk.wav") -> Tuple[str, float]:
        """
        Sends in-memory WAV bytes to the Indic Conformer endpoint.
        Returns:
            Tuple of (transcribed_text, latency_ms)
        """
        start = time.perf_counter()
        files = {"file": (filename, wav_bytes, "audio/wav")}

        try:
            response = self.session.post(
                self.endpoint,
                files=files,
                timeout=self.timeout_seconds,
            )
            latency_ms = (time.perf_counter() - start) * 1000.0

            if response.status_code != 200:
                return "", latency_ms

            data = response.json()
            raw_text = data.get("text", "")
            return raw_text.strip(), latency_ms
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000.0
            # Return empty on network timeout/failure
            return "", latency_ms

    def transcribe_file(self, file_path: str | Path) -> Tuple[str, float]:
        """Transcribes a physical WAV file."""
        with open(file_path, "rb") as f:
            wav_bytes = f.read()
        return self.transcribe_wav_bytes(wav_bytes, filename=Path(file_path).name)
