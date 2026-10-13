from typing import List, Optional, Tuple


class WindowManager:
    """
    Manages the sliding window of incoming transcribed words.
    Enforces adaptive chunking:
    - Triggers LLM when word threshold (e.g. 5 words) is reached.
    - Triggers LLM on natural micro-pauses (speech breathing silence).
    - Maintains previous context so subsequent chunks do not lose grammar/casing.
    """

    def __init__(self, word_threshold: int = 5, max_context_words: int = 15):
        self.word_threshold = word_threshold
        self.max_context_words = max_context_words

        self.pending_words: List[str] = []
        self.committed_words: List[str] = []
        self.previous_context_words: List[str] = []

    def feed_text(self, text: str) -> List[str]:
        """
        Feeds newly recognized words into the in-flight buffer.
        """
        if not text:
            return self.pending_words

        new_tokens = [w for w in text.strip().split() if w]
        self.pending_words.extend(new_tokens)
        return self.pending_words

    def get_in_flight_tail(self) -> str:
        """Returns the current raw uncommitted words."""
        return " ".join(self.pending_words)

    def should_trigger(self, pause_detected: bool = False) -> bool:
        """
        Checks if the buffer is ready to be dispatched for cleanup:
        - Word threshold reached (>= word_threshold words), OR
        - Speech micro-pause detected AND at least 2 words present.
        """
        count = len(self.pending_words)
        if count >= self.word_threshold:
            return True
        if pause_detected and count >= 2:
            return True
        return False

    def pop_chunk_for_cleaning(self) -> Tuple[str, str]:
        """
        Extracts the pending words as a chunk to be cleaned,
        along with the recent context history.
        Returns:
            (previous_context: str, current_fragment: str)
        """
        fragment = " ".join(self.pending_words)
        self.pending_words = []

        context_str = " ".join(self.previous_context_words[-self.max_context_words:])
        return context_str, fragment

    def commit_polished_chunk(self, polished_text: str):
        """
        Commits a polished chunk into history and updates context.
        """
        cleaned = polished_text.strip()
        if not cleaned:
            return

        tokens = cleaned.split()
        self.committed_words.extend(tokens)
        self.previous_context_words.extend(tokens)

    def get_full_committed_text(self) -> str:
        """Returns all finalized & polished text so far."""
        return " ".join(self.committed_words)

    def reset(self):
        self.pending_words.clear()
        self.committed_words.clear()
        self.previous_context_words.clear()
