import asyncio
import logging
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from .config import CleanupConfig
from .gemini_client import GeminiAsiaMumbaiClient
from .prompts import (
    WISPR_FLOW_FINAL_RECONCILIATION_INSTRUCTION,
    WISPR_FLOW_SENTENCE_INSTRUCTION,
)
from .segmenter import SentenceSegmenter


logger = logging.getLogger(__name__)


class WisprFlowCleanupEngine:
    """
    Concurrent Sentence-Level Dictation Cleanup Engine (Wispr Flow architecture).
    Fires Gemini 2.5 Flash (Asia Mumbai) concurrently in background tasks alongside
    the ongoing local ASR stream, minimizing perceived polish latency.
    """

    def __init__(
        self,
        config: Optional[CleanupConfig] = None,
        on_raw_chunk: Optional[Callable[[str], None]] = None,
        on_sentence_started: Optional[Callable[[Dict[str, Any]], None]] = None,
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
        self.on_sentence_started = on_sentence_started
        self.on_sentence_polished = on_sentence_polished

        self.raw_history: List[str] = []
        self._sentence_results: Dict[int, str] = {}
        self._sentence_outputs: Dict[int, str] = {}
        self._background_tasks: List[asyncio.Task] = []
        self._sentence_counter = 0
        self.session_id = uuid.uuid4().hex[:6]

    def reset(self):
        """
        Resets all sentence buffers, counters, and history for a fresh dictation session.
        """
        self.raw_history.clear()
        self._sentence_results.clear()
        self._sentence_outputs.clear()
        self._background_tasks.clear()
        self._sentence_counter = 0
        self.session_id = uuid.uuid4().hex[:6]
        self.segmenter = SentenceSegmenter(
            min_words=self.config.min_sentence_words,
            max_words=self.config.max_sentence_words,
            silence_pause_sec=self.config.silence_pause_sec,
        )

    @property
    def polished_sentences(self) -> List[str]:
        """
        Returns all completed polished sentences strictly ordered by their index.
        """
        return [
            self._sentence_results[idx]
            for idx in sorted(self._sentence_results.keys())
        ]

    def _dispatch_sentence(self, raw_sentence: str):
        """
        Assigns unique sequential ID, notifies start of cleaning, and fires background LLM worker.
        """
        self._sentence_counter += 1
        idx = self._sentence_counter
        sentence_id = f"s_{self.session_id}_{idx}"

        if self.on_sentence_started:
            self.on_sentence_started({
                "sentence_id": sentence_id,
                "sentence_index": idx,
                "raw_sentence": raw_sentence,
            })

        task = asyncio.create_task(
            self._polish_sentence_worker(idx, sentence_id, raw_sentence)
        )
        self._background_tasks.append(task)

    async def feed_stream(self, raw_chunk: str, is_pause: bool = False):
        """
        Ingests newly transcribed raw tokens from ASR.
        If a sentence boundary (full stop or pause) is detected,
        dispatches a concurrent background task to Gemini Flash.
        ASR continues running without waiting.
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
            self._dispatch_sentence(raw_sentence)

    async def feed_typed_text(self, text: str):
        """
        Ingests user-typed text. Flushes any pending mic tail held by the segmenter first,
        then segments typed text into sentences and dispatches them through the same counter,
        cleaning and polished flow.
        """
        text = text.strip()
        if not text:
            return

        # Flush any unfinished mic words held by segmenter
        mic_tail = self.segmenter.flush_tail()
        if mic_tail:
            self._dispatch_sentence(mic_tail)

        # Segment typed text into sentences and flush all
        sentences = self.segmenter.feed(text, is_pause=True)
        rem = self.segmenter.flush_tail()
        if rem:
            sentences.append(rem)

        for sent in sentences:
            self.raw_history.append(sent)
            self._dispatch_sentence(sent)

    @staticmethod
    def _validate_cleaned_output(
        raw_sentence: str,
        generated_text: str,
    ) -> tuple[str, bool, str]:
        text = (generated_text or "").strip()
        clean_prefix = "Clean sentence:"
        if text.casefold().startswith(clean_prefix.casefold()):
            text = text[len(clean_prefix):].strip()

        if not text:
            return raw_sentence, False, "empty"

        lowered = text.casefold()
        if "<speech_to_clean>" in lowered or "<reference_context>" in lowered:
            return raw_sentence, False, "prompt_tag"

        if any(
            lowered.startswith(prefix.casefold())
            for prefix in ("Raw Sentence:", "Clean sentence:", "Context:")
        ):
            return raw_sentence, False, "prompt_prefix"

        if len(text.split()) > 1.5 * len(raw_sentence.split()) + 3:
            return raw_sentence, False, "excessive_length"

        return text, True, ""

    async def _polish_sentence_worker(self, index: int, sentence_id: str, raw_sentence: str):
        """
        Background worker that sends the sentence to Gemini Asia Mumbai and updates state.
        """
        speech_text = re.sub(
            r"</?speech_to_clean\s*>",
            "",
            raw_sentence,
            flags=re.IGNORECASE,
        )
        user_prompt = f"<speech_to_clean>{speech_text}</speech_to_clean>"

        cleaned_text, latency_ms, tps = await self.client.generate_async(
            system_instruction=WISPR_FLOW_SENTENCE_INSTRUCTION,
            user_prompt=user_prompt,
        )

        output_text, accepted, rejection_reason = self._validate_cleaned_output(
            raw_sentence,
            cleaned_text,
        )
        if accepted:
            self._sentence_results[index] = output_text
        else:
            logger.warning(
                "Rejected Gemini cleanup output sentence_id=%s reason=%s",
                sentence_id,
                rejection_reason,
            )
        self._sentence_outputs[index] = output_text

        event = {
            "sentence_id": sentence_id,
            "sentence_index": index,
            "raw_sentence": raw_sentence,
            "polished_sentence": output_text,
            "latency_ms": round(latency_ms, 1),
            "tps": round(tps, 1),
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
            self._dispatch_sentence(tail)

        # Wait for all background LLM tasks fired alongside ASR to finish.
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        full_raw = " ".join(self.raw_history).strip()
        sentence_outputs = [
            self._sentence_outputs[idx] for idx in sorted(self._sentence_outputs)
        ]
        full_polished = " ".join(sentence_outputs).strip()

        # Optional final reconciliation
        if run_final_pass and full_polished:
            final_text, _, _ = await self.client.generate_async(
                system_instruction=WISPR_FLOW_FINAL_RECONCILIATION_INSTRUCTION,
                user_prompt=f"Text to finalize:\n\"{full_polished}\"",
            )
            if final_text:
                full_polished = final_text

        return {
            "raw_text": full_raw,
            "polished_text": full_polished,
            "sentences_count": len(sentence_outputs),
            "sentences": sentence_outputs,
        }

    def get_live_state(self) -> Dict[str, Any]:
        """
        Returns snapshot of live dictation state for UI rendering.
        """
        return {
            "raw_full": " ".join(self.raw_history).strip(),
            "polished_full": " ".join(
                self._sentence_outputs[idx] for idx in sorted(self._sentence_outputs)
            ).strip(),
            "in_flight_tail": self.segmenter.get_current_tail(),
            "completed_sentences": [
                self._sentence_outputs[idx] for idx in sorted(self._sentence_outputs)
            ],
        }
