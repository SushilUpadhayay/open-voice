import asyncio
import time
from typing import Any, Callable, Dict, List, Optional

from .config import CleanupConfig
from .gemini_client import GeminiAsiaMumbaiClient
from .prompts import (
    WISPR_FLOW_FINAL_RECONCILIATION_INSTRUCTION,
    WISPR_FLOW_SENTENCE_INSTRUCTION,
)
from .segmenter import SentenceSegmenter


class WisprFlowCleanupEngine:
    """
    Concurrent Sentence-Level Dictation Cleanup Engine (Wispr Flow architecture).
    Fires Gemini 2.5 Flash (Asia Mumbai) concurrently in background tasks alongside
    the ongoing Nemotron ASR stream, minimizing perceived polish latency.
    """

    def __init__(
        self,
        config: Optional[CleanupConfig] = None,
        on_raw_chunk: Optional[Callable[[str], None]] = None,
        on_sentence_polished: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        self.config = config or CleanupConfig()
        self.client = GeminiAsiaMumbaiClient(self.config)
        self.segmenter = SentenceSegmenter(
            min_words=self.config.min_sentence_words,
            max_words=self.config.max_sentence_words,
            silence_pause_sec=self.config.silence_pause_sec,
        )

        # Callbacks for live UI visualization
        self.on_raw_chunk = on_raw_chunk
        self.on_sentence_polished = on_sentence_polished

        # State buffers
        self.raw_history: List[str] = []
        self._sentence_results: Dict[int, str] = {}
        self._background_tasks: List[asyncio.Task] = []
        self._sentence_counter = 0

    @property
    def polished_sentences(self) -> List[str]:
        """
        Returns all completed polished sentences strictly ordered by their index.
        """
        return [
            self._sentence_results[idx]
            for idx in sorted(self._sentence_results.keys())
        ]

    def _get_recent_context(self) -> str:
        """
        Retrieves the last N polished sentences to provide grammatical continuity.
        """
        sentences = self.polished_sentences
        if not sentences:
            return ""
        recent = sentences[-self.config.context_sentence_window:]
        return " ".join(recent).strip()

    async def feed_stream(self, raw_chunk: str, is_pause: bool = False):
        """
        Ingests newly transcribed raw tokens from Nemotron.
        If a sentence boundary (full stop or pause) is detected,
        dispatches a concurrent background task to Gemini Flash.
        Nemotron continues running without waiting.
        """
        if not raw_chunk and not is_pause:
            return

        if raw_chunk:
            self.raw_history.append(raw_chunk)
            if self.on_raw_chunk:
                self.on_raw_chunk(raw_chunk)

        # Segment into completed sentences
        new_sentences = self.segmenter.feed(raw_chunk, is_pause=is_pause)

        for raw_sentence in new_sentences:
            self._sentence_counter += 1
            idx = self._sentence_counter
            context = self._get_recent_context()

            # Fire Gemini Flash alongside ongoing ASR in a non-blocking background task
            task = asyncio.create_task(
                self._polish_sentence_worker(idx, raw_sentence, context)
            )
            self._background_tasks.append(task)

    async def _polish_sentence_worker(self, index: int, raw_sentence: str, context: str):
        """
        Background worker that sends the sentence to Gemini Asia Mumbai and updates state.
        """
        user_prompt = f"Context: \"{context}\"\nRaw Sentence: \"{raw_sentence}\""

        cleaned_text, latency_ms = await self.client.generate_async(
            system_instruction=WISPR_FLOW_SENTENCE_INSTRUCTION,
            user_prompt=user_prompt,
        )

        # Safety fallback
        if not cleaned_text or cleaned_text.isspace():
            cleaned_text = raw_sentence

        self._sentence_results[index] = cleaned_text

        event = {
            "sentence_index": index,
            "raw_sentence": raw_sentence,
            "polished_sentence": cleaned_text,
            "latency_ms": round(latency_ms, 1),
            "timestamp": round(time.time(), 3),
        }

        if self.on_sentence_polished:
            self.on_sentence_polished(event)

    async def finish_and_finalize(self, run_final_pass: bool = False) -> Dict[str, Any]:
        """
        Flushes any uncommitted trailing words, awaits all in-flight background tasks,
        and returns the complete reconciled transcript in exact chronological order.
        """
        tail = self.segmenter.flush_tail()
        if tail:
            self._sentence_counter += 1
            idx = self._sentence_counter
            context = self._get_recent_context()
            task = asyncio.create_task(
                self._polish_sentence_worker(idx, tail, context)
            )
            self._background_tasks.append(task)

        # Wait for all background LLM tasks fired alongside Nemotron to finish
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        full_raw = " ".join(self.raw_history).strip()
        full_polished = " ".join(self.polished_sentences).strip()

        # Optional final reconciliation
        if run_final_pass and full_polished:
            final_text, _ = await self.client.generate_async(
                system_instruction=WISPR_FLOW_FINAL_RECONCILIATION_INSTRUCTION,
                user_prompt=f"Text to finalize:\n\"{full_polished}\"",
            )
            if final_text:
                full_polished = final_text

        return {
            "raw_text": full_raw,
            "polished_text": full_polished,
            "sentences_count": len(self.polished_sentences),
            "sentences": self.polished_sentences,
        }

    def get_live_state(self) -> Dict[str, Any]:
        """
        Returns snapshot of live dictation state for UI rendering.
        """
        return {
            "raw_full": " ".join(self.raw_history).strip(),
            "polished_full": " ".join(self.polished_sentences).strip(),
            "in_flight_tail": self.segmenter.get_current_tail(),
            "completed_sentences": list(self.polished_sentences),
        }
