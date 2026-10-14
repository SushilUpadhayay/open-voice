import re
import time
from typing import List, Optional, Tuple

TERMINAL_PUNCTUATION = re.compile(r'([.?!।]+(?:\s+|$))')


class SentenceSegmenter:
    """
    Sentence-level boundary detector for streaming ASR text.
    Segments text when:
    1. A full stop or terminal punctuation ('.', '?', '!', '।') is detected.
    2. An acoustic pause / silence is reported (e.g., VAD silence >= 350ms) with enough words.
    3. The in-flight buffer exceeds a maximum word threshold.
    """

    def __init__(
        self,
        min_words: int = 3,
        max_words: int = 15,
        silence_pause_sec: float = 0.35,
    ):
        self.min_words = min_words
        self.max_words = max_words
        self.silence_pause_sec = silence_pause_sec

        self._in_flight_words: List[str] = []
        self._last_word_time = time.perf_counter()

    def feed(self, text_chunk: str, is_pause: bool = False) -> List[str]:
        """
        Feeds new words/tokens from streaming ASR.
        Returns a list of completed sentences ready for LLM cleanup.
        Leaves any incomplete tail in the internal buffer.
        """
        now = time.perf_counter()
        completed_sentences: List[str] = []

        raw_words = text_chunk.strip().split()
        if raw_words:
            self._in_flight_words.extend(raw_words)
            self._last_word_time = now

        full_in_flight = " ".join(self._in_flight_words).strip()
        if not full_in_flight:
            return completed_sentences

        # Criteria 1: Check for explicit terminal punctuation inside in-flight buffer
        if TERMINAL_PUNCTUATION.search(full_in_flight):
            parts = TERMINAL_PUNCTUATION.split(full_in_flight)
            # Reconstruct sentences with their punctuation
            reconstructed = []
            i = 0
            while i < len(parts):
                segment = parts[i].strip()
                if not segment:
                    i += 1
                    continue
                if i + 1 < len(parts) and TERMINAL_PUNCTUATION.match(parts[i + 1]):
                    reconstructed.append(f"{segment}{parts[i + 1].strip()}")
                    i += 2
                else:
                    reconstructed.append(segment)
                    i += 1

            if len(reconstructed) > 1:
                # All but the last segment are definitely completed sentences
                for sent in reconstructed[:-1]:
                    if sent.strip():
                        completed_sentences.append(sent.strip())
                # Last segment remains in buffer
                self._in_flight_words = reconstructed[-1].split()
                return completed_sentences
            elif len(reconstructed) == 1 and TERMINAL_PUNCTUATION.search(reconstructed[0]):
                completed_sentences.append(reconstructed[0].strip())
                self._in_flight_words = []
                return completed_sentences

        # Criteria 2: Acoustic pause or silence detected with sufficient word length
        word_count = len(self._in_flight_words)
        elapsed_silence = now - self._last_word_time

        if (is_pause or elapsed_silence >= self.silence_pause_sec) and word_count >= self.min_words:
            sentence = " ".join(self._in_flight_words).strip()
            completed_sentences.append(sentence)
            self._in_flight_words = []
            return completed_sentences

        # Criteria 3: Safety valve — buffer exceeds max length without natural pause
        if word_count >= self.max_words:
            sentence = " ".join(self._in_flight_words).strip()
            completed_sentences.append(sentence)
            self._in_flight_words = []
            return completed_sentences

        return completed_sentences

    def flush_tail(self) -> Optional[str]:
        """
        Flushes any remaining incomplete sentence in the buffer (used at end of speech).
        """
        if self._in_flight_words:
            sentence = " ".join(self._in_flight_words).strip()
            self._in_flight_words = []
            return sentence
        return None

    def get_current_tail(self) -> str:
        """
        Returns the uncommitted live tail currently accumulating.
        """
        return " ".join(self._in_flight_words).strip()
