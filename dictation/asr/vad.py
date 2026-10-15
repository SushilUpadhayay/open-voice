import math
import struct


class EnergyVAD:
    """
    Low-latency energy-based Voice Activity Detector for 16kHz 16-bit mono PCM.
    Calculates RMS energy, tracks background noise floor, and identifies speech vs silence pauses.
    """

    def __init__(
        self,
        energy_threshold: float = 350.0,
        min_silence_ms: float = 350.0,
        min_speech_ms: float = 120.0,
        session_pause_ms: float = 3000.0,
    ):
        self.energy_threshold = energy_threshold
        self.min_silence_ms = min_silence_ms
        self.min_speech_ms = min_speech_ms
        self.session_pause_ms = session_pause_ms

        self.consecutive_speech_ms: float = 0.0
        self.consecutive_silence_ms: float = 0.0
        self.is_speech_active: bool = False
        self.noise_floor: float = 200.0
        self.has_spoken: bool = False
        self._session_pause_triggered: bool = False

    def calculate_rms(self, pcm_bytes: bytes) -> float:
        if len(pcm_bytes) < 2:
            return 0.0

        count = len(pcm_bytes) // 2
        shorts = struct.unpack(f"<{count}h", pcm_bytes[: count * 2])
        sum_squares = sum(s * s for s in shorts)
        return math.sqrt(sum_squares / count) if count > 0 else 0.0

    def is_speech_frame(self, pcm_bytes: bytes) -> bool:
        rms = self.calculate_rms(pcm_bytes)
        if rms < self.energy_threshold:
            self.noise_floor = 0.95 * self.noise_floor + 0.05 * rms
        return rms > max(self.energy_threshold, self.noise_floor * 1.6)

    def update_and_check_pause(self, pcm_bytes: bytes, chunk_duration_ms: float) -> bool:
        """
        Updates VAD state with the audio frame.
        Returns:
            True if a silence pause (>= min_silence_ms) is detected following active speech.
        """
        is_speech = self.is_speech_frame(pcm_bytes)

        if is_speech:
            self.consecutive_speech_ms += chunk_duration_ms
            self.consecutive_silence_ms = 0.0
            if self.consecutive_speech_ms >= self.min_speech_ms:
                self.is_speech_active = True
                self.has_spoken = True
                self._session_pause_triggered = False
            return False
        else:
            self.consecutive_silence_ms += chunk_duration_ms
            self.consecutive_speech_ms = 0.0

            if self.is_speech_active and self.consecutive_silence_ms >= self.min_silence_ms:
                self.is_speech_active = False
                return True

            return False

    def is_session_pause(self) -> bool:
        """
        Returns True once when consecutive silence reaches session_pause_ms (3.0s)
        after active speech has occurred.
        """
        if self.has_spoken and not self._session_pause_triggered:
            if self.consecutive_silence_ms >= self.session_pause_ms:
                self._session_pause_triggered = True
                return True
        return False

    def reset(self):
        self.consecutive_speech_ms = 0.0
        self.consecutive_silence_ms = 0.0
        self.is_speech_active = False
        self.has_spoken = False
        self._session_pause_triggered = False
