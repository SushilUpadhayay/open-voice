from pathlib import Path
from typing import Tuple
import time
import requests


class IndicConformerClient:
    """Client for the Indic Conformer ASR endpoint."""

    def __init__(self, endpoint: str, timeout_seconds: int = 30):
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    def transcribe(self, audio_path: str | Path) -> Tuple[str, float]:
        """
        Sends a wav audio file to the Indic Conformer endpoint.

        Returns:
            Tuple of (transcribed_text, latency_ms)
        """
        file_path = Path(audio_path).resolve()
        if not file_path.exists():
            raise FileNotFoundError(f"Audio file not found: {file_path}")

        start_time = time.perf_counter()
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "audio/wav")}
            response = self.session.post(
                self.endpoint,
                files=files,
                timeout=self.timeout_seconds,
            )


        latency_ms = (time.perf_counter() - start_time) * 1000.0

        if response.status_code != 200:
            raise RuntimeError(
                f"ASR request failed with status {response.status_code}: {response.text}"
            )

        data = response.json()
        raw_text = data.get("text", "")
        # Trim leading/trailing whitespace
        trimmed_text = raw_text.strip()
        return trimmed_text, latency_ms
