import asyncio
from dataclasses import dataclass
import time
from typing import Optional

from .client import NemotronASRClient
from .vad import EnergyVAD


@dataclass
class ASRChunkResult:
    text: str
    latency_ms: float
    rtf: float
    is_pause: bool
    audio_duration_sec: float
    tps: float = 0.0


class NemotronStreamSession:
    """
    Manages live streaming audio buffering, VAD tracking, and Nemotron ASR decoding.
    All runtime ASR logic is contained here.
    """

    def __init__(
        self,
        asr_client: Optional[NemotronASRClient] = None,
        silence_pause_ms: float = 350.0,
        min_audio_bytes: int = 22400,       # 0.7s @ 16kHz 16-bit mono
        max_continuous_bytes: int = 96000,  # 3.0s continuous speech threshold
    ):
        self.asr = asr_client or NemotronASRClient()
        self.vad = EnergyVAD(min_silence_ms=silence_pause_ms)
        self.min_audio_bytes = min_audio_bytes
        self.max_continuous_bytes = max_continuous_bytes

        self.audio_buffer = bytearray()
        self.has_spoken = False
        self.last_transcribe_time = time.perf_counter()

    async def feed_audio(self, raw_pcm_bytes: bytes) -> Optional[ASRChunkResult]:
        """
        Feeds a chunk of 16kHz 16-bit mono PCM bytes.
        Returns:
            ASRChunkResult if transcription was triggered by pause or duration threshold,
            otherwise None.
        """
        if not raw_pcm_bytes:
            return None

        self.audio_buffer.extend(raw_pcm_bytes)
        chunk_ms = (len(raw_pcm_bytes) / 2) / 16.0

        is_speech = self.vad.is_speech_frame(raw_pcm_bytes)
        if is_speech:
            self.has_spoken = True

        is_pause = self.vad.update_and_check_pause(raw_pcm_bytes, chunk_ms)
        now = time.perf_counter()

        should_transcribe = False
        if self.has_spoken:
            # Condition 1: Speech followed by pause (>= 350ms) and buffer has enough audio
            if is_pause and len(self.audio_buffer) >= self.min_audio_bytes:
                should_transcribe = True
            # Condition 2: Continuous speech exceeded 3.0s (avoid latency buildup without chopping phrases)
            elif (now - self.last_transcribe_time >= 3.0) and len(self.audio_buffer) >= self.max_continuous_bytes:
                should_transcribe = True

        if should_transcribe:
            self.last_transcribe_time = now
            pcm_data = bytes(self.audio_buffer)
            self.audio_buffer.clear()
            self.has_spoken = False

            audio_duration = len(pcm_data) / 32000.0  # 16000 samples/sec * 2 bytes/sample

            # Execute Nemotron ASR decoding in worker thread
            raw_text, latency_ms, rtf = await asyncio.to_thread(
                self.asr.transcribe_pcm_bytes, pcm_data
            )

            if raw_text:
                words = len(raw_text.split())
                tokens = max(1, round(words * 1.33))
                tps = round(tokens / (latency_ms / 1000.0), 1) if latency_ms > 0 else 0.0
                return ASRChunkResult(
                    text=raw_text,
                    latency_ms=round(latency_ms, 1),
                    rtf=round(rtf, 2),
                    is_pause=is_pause,
                    audio_duration_sec=round(audio_duration, 2),
                    tps=tps,
                )

        return None

    async def flush(self) -> Optional[ASRChunkResult]:
        """
        Flushes and transcribes any remaining uncommitted audio buffer.
        """
        if len(self.audio_buffer) >= 9600:  # >= 0.3s
            pcm_data = bytes(self.audio_buffer)
            self.audio_buffer.clear()
            self.has_spoken = False
            self.vad.reset()

            audio_duration = len(pcm_data) / 32000.0
            raw_text, latency_ms, rtf = await asyncio.to_thread(
                self.asr.transcribe_pcm_bytes, pcm_data
            )

            if raw_text:
                words = len(raw_text.split())
                tokens = max(1, round(words * 1.33))
                tps = round(tokens / (latency_ms / 1000.0), 1) if latency_ms > 0 else 0.0
                return ASRChunkResult(
                    text=raw_text,
                    latency_ms=round(latency_ms, 1),
                    rtf=round(rtf, 2),
                    is_pause=True,
                    audio_duration_sec=round(audio_duration, 2),
                    tps=tps,
                )

        self.reset()
        return None

    def reset(self):
        self.audio_buffer.clear()
        self.has_spoken = False
        self.vad.reset()
        self.last_transcribe_time = time.perf_counter()
