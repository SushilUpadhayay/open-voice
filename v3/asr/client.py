import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Dict, Optional, Tuple
import wave

HANDY_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Handy" / "handy.exe"
DEFAULT_MODEL = "handy-computer/nemotron-3.5-asr-streaming-0.6b-gguf/nemotron-3.5-asr-streaming-0.6b-Q8_0.gguf"


class NemotronASRClient:
    """
    Client for running Nemotron 3.5 ASR via the local transcribe-cpp / Vulkan GPU engine.
    Supports file-based transcription and live in-memory audio buffer decoding.
    """

    def __init__(
        self,
        handy_exe_path: Optional[Path] = None,
        model_id: str = DEFAULT_MODEL,
        sample_rate: int = 16000,
    ):
        self.handy_exe = Path(handy_exe_path) if handy_exe_path else HANDY_EXE
        self.model_id = model_id
        self.sample_rate = sample_rate

    def is_available(self) -> bool:
        return self.handy_exe.exists()

    @staticmethod
    def pcm_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
        """
        Wraps raw 16-bit mono PCM bytes in a standard RIFF/WAV container in memory.
        """
        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        return wav_io.getvalue()

    def transcribe_wav_file(self, wav_path: str | Path) -> Tuple[str, float, float]:
        """
        Transcribes a WAV file on disk.
        Returns:
            (transcript: str, latency_ms: float, rtf: float)
        """
        wav_file = Path(wav_path).resolve()
        if not wav_file.exists():
            raise FileNotFoundError(f"WAV file not found: {wav_file}")
        if not self.is_available():
            raise FileNotFoundError(f"Nemotron engine not found at: {self.handy_exe}")

        cmd = [
            str(self.handy_exe),
            "--transcribe-file", str(wav_file),
            "--model", self.model_id,
            "--json",
        ]

        start = time.perf_counter()
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        latency_ms = (time.perf_counter() - start) * 1000.0

        if result.returncode != 0:
            return "", latency_ms, 0.0

        try:
            data = json.loads(result.stdout.strip())
            text = data.get("text", "").strip()
            best_ms = data.get("best_ms", latency_ms)
            rtf = data.get("rtf", 1.0)
            return text, float(best_ms), float(rtf)
        except Exception:
            return result.stdout.strip(), latency_ms, 1.0

    def transcribe_pcm_bytes(self, pcm_bytes: bytes) -> Tuple[str, float, float]:
        """
        Transcribes raw in-memory PCM bytes by saving to a transient file.
        """
        if not pcm_bytes:
            return "", 0.0, 0.0

        wav_bytes = self.pcm_to_wav_bytes(pcm_bytes, self.sample_rate)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(wav_bytes)

        try:
            return self.transcribe_wav_file(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
