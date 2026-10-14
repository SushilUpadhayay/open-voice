import re
from typing import Set, Tuple

COMMON_FILLERS: Set[str] = {
    # English fillers
    "um", "uh", "er", "ah", "hmm", "like", "you know", "basically", "actually",
    # Nepali & Hindi fillers and hesitation markers
    "उम्", "अँ", "ए", "हजुर हजुर", "त्यो के भन्छन्", "चाहिँ", "कि क्या हो",
    "मतलब", "यार", "भाई",
}

STUTTER_PATTERN = re.compile(r"\b(\w+)\s+\1\b", flags=re.IGNORECASE | re.UNICODE)


class HeuristicCleaner:
    """
    0ms deterministic rule-based cleaner and filter.
    Determines if a text fragment contains fillers or stutters that need LLM cleanup,
    or can bypass the LLM and pass directly with 0ms latency.
    """

    def __init__(self, additional_fillers: Set[str] | None = None):
        self.fillers = COMMON_FILLERS.copy()
        if additional_fillers:
            self.fillers.update(additional_fillers)

    def analyze(self, text: str) -> Tuple[bool, str]:
        """
        Analyzes the text fragment.
        Returns:
            (needs_llm: bool, quick_cleaned_text: str)
        """
        if not text or not text.strip():
            return False, ""

        cleaned = text.strip()
        has_anomaly = False

        # 1. Check for immediate stutters (e.g. "म म" -> "म", "the the" -> "the")
        if STUTTER_PATTERN.search(cleaned):
            has_anomaly = True
            cleaned = STUTTER_PATTERN.sub(r"\1", cleaned)

        # 2. Check for filler words
        words = cleaned.split()
        filtered_words = []
        for w in words:
            clean_word = w.strip(".,!?\"'").lower()
            if clean_word in self.fillers:
                has_anomaly = True
            else:
                filtered_words.append(w)

        quick_text = " ".join(filtered_words)

        # If any filler or stutter was detected, flag for LLM or use quick-clean
        return has_anomaly, quick_text

    def fast_strip_fillers(self, text: str) -> str:
        """Instant stripping of fillers from the tentative in-flight tail for display."""
        _, quick = self.analyze(text)
        return quick
