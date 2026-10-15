import io
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Dict, Optional, Tuple
import wave

HANDY_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Handy" / "handy.exe"
DEFAULT_MODEL = "handy-computer/parakeet-unified-en-0.6b-gguf/parakeet-unified-en-0.6b-Q8_0.gguf"
MODEL_STATUS_CACHE_SECONDS = 30.0

logger = logging.getLogger(__name__)


class HandyASRClient:
    """
    Client for running the configured local Handy ASR model via Vulkan or CPU.
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
        self._model_status_checked_at = 0.0
        self._model_downloaded = False

    def is_available(self) -> bool:
        return self.handy_exe.exists() and self.is_model_downloaded()

    def is_model_downloaded(self) -> bool:
        """Check whether the configured Handy model is installed, caching briefly."""
        now = time.monotonic()
        if now - self._model_status_checked_at < MODEL_STATUS_CACHE_SECONDS:
            return self._model_downloaded
        if not self.handy_exe.exists():
            self._model_downloaded = False
            self._model_status_checked_at = now
            return False

        result = subprocess.run(
            [str(self.handy_exe), "--list-models", "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            timeout=20,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Unable to check Handy's model list: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )

        try:
            models = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Handy returned an invalid model list") from exc

        self._model_downloaded = any(
            model.get("id") == self.model_id and model.get("is_downloaded")
            for model in models
        )
        self._model_status_checked_at = now
        return self._model_downloaded

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
        if not self.handy_exe.exists():
            raise FileNotFoundError(f"Handy ASR engine not found at: {self.handy_exe}")
        if not self.is_model_downloaded():
            raise FileNotFoundError(
                f"ASR model '{self.model_id}' is not downloaded in Handy."
            )

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
            detail = result.stderr.strip() or result.stdout.strip()
            logger.error(
                "ASR transcription failed exit_code=%s model=%s error=%s",
                result.returncode,
                self.model_id,
                detail,
            )
            raise RuntimeError(
                f"ASR transcription failed (exit code {result.returncode}): {detail}"
            )

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


NemotronASRClient = HandyASRClient
