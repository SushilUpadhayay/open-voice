import time
import uuid
from typing import Any, Dict


class StreamingSession:
    """
    Encapsulates the state and metrics of an active dictation session.
    """

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.start_time = time.perf_counter()
        self.last_activity = self.start_time

        self.raw_text_history: list[str] = []
        self.polished_text_chunks: list[str] = []

        self.audio_chunks_received = 0
        self.gemini_calls_count = 0
        self.gemini_bypass_count = 0
        self.total_gemini_latency_ms = 0.0

    def record_raw(self, text: str):
        if text.strip():
            self.raw_text_history.append(text.strip())
            self.last_activity = time.perf_counter()

    def record_polish(self, chunk: str, latency_ms: float, bypassed: bool = False):
        if chunk.strip():
            self.polished_text_chunks.append(chunk.strip())
            self.last_activity = time.perf_counter()
            if bypassed:
                self.gemini_bypass_count += 1
            else:
                self.gemini_calls_count += 1
                self.total_gemini_latency_ms += latency_ms

    def get_summary(self) -> Dict[str, Any]:
        total_duration_sec = time.perf_counter() - self.start_time
        avg_llm_latency = (
            (self.total_gemini_latency_ms / self.gemini_calls_count)
            if self.gemini_calls_count > 0
            else 0.0
        )
        return {
            "session_id": self.session_id,
            "duration_seconds": round(total_duration_sec, 2),
            "gemini_calls": self.gemini_calls_count,
            "heuristics_bypasses": self.gemini_bypass_count,
            "avg_gemini_latency_ms": round(avg_llm_latency, 1),
            "final_raw": " ".join(self.raw_text_history),
            "final_polished": " ".join(self.polished_text_chunks),
        }
