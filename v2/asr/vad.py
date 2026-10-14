import math
import struct
from typing import List


class EnergyVAD:
    """
    Lightweight energy and zero-crossing rate Voice Activity Detector.
    Runs in 0ms on raw 16kHz PCM audio frames (16-bit signed integer or float32).
    Tracks continuous silence duration to trigger micro-pauses.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        energy_threshold: float = 0.008,
        min_silence_ms: int = 350,
    ):
        self.sample_rate = sample_rate
        self.energy_threshold = energy_threshold
        self.min_silence_ms = min_silence_ms
        self.silence_frames_count = 0
        self.frame_duration_ms = 20  # default 20ms analysis frames

    def is_speech_frame(self, pcm_data: bytes | List[float]) -> bool:
        """
        Calculates Root-Mean-Square (RMS) energy of an audio frame.
        """
        if isinstance(pcm_data, bytes):
            # Assume 16-bit mono PCM
            count = len(pcm_data) // 2
            if count == 0:
                return False
            samples = struct.unpack(f"<{count}h", pcm_data[: count * 2])
            sum_sq = sum(s * s for s in samples)
            rms = math.sqrt(sum_sq / count) / 32768.0
        else:
            if not pcm_data:
                return False
            sum_sq = sum(s * s for s in pcm_data)
            rms = math.sqrt(sum_sq / len(pcm_data))

        return rms >= self.energy_threshold

    def update_and_check_pause(self, pcm_chunk: bytes | List[float], chunk_duration_ms: float) -> bool:
        """
        Updates internal silence tracker. Returns True if a micro-pause
        (silence duration >= min_silence_ms) is detected.
        """
        if self.is_speech_frame(pcm_chunk):
            self.silence_frames_count = 0
            return False
        else:
            self.silence_frames_count += chunk_duration_ms
            return self.silence_frames_count >= self.min_silence_ms

    def reset(self):
        self.silence_frames_count = 0
