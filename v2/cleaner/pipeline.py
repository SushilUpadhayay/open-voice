from typing import Tuple
from .gemini import GeminiFlashClient
from .prompts import IN_FLIGHT_SYSTEM_INSTRUCTION, FINAL_PASS_SYSTEM_INSTRUCTION
from ..engine.heuristics import HeuristicCleaner


class PolishPipeline:
    """
    Coordinates the two-stage polishing process:
    1. In-flight fragment cleanup (with heuristic bypass and anti-completion prompt).
    2. Final reconciliation pass (terminal punctuation and capitalization).
    """

    def __init__(
        self,
        gemini_client: GeminiFlashClient,
        heuristic_cleaner: HeuristicCleaner | None = None,
        enable_heuristics: bool = True,
    ):
        self.gemini = gemini_client
        self.heuristics = heuristic_cleaner or HeuristicCleaner()
        self.enable_heuristics = enable_heuristics

    def clean_in_flight(self, context: str, fragment: str) -> Tuple[str, float, bool]:
        """
        Cleans an in-flight fragment.
        Returns:
            (cleaned_fragment: str, latency_ms: float, was_bypassed: bool)
        """
        fragment = fragment.strip()
        if not fragment:
            return "", 0.0, True

        # Step 1: 0ms heuristic check
        if self.enable_heuristics:
            needs_llm, quick_cleaned = self.heuristics.analyze(fragment)
            if not needs_llm:
                # Bypass LLM: fragment is already clean!
                return fragment, 0.0, True

        # Step 2: Format in-flight prompt with context carry-forward
        user_prompt = f"Context so far: \"{context}\"\nNew fragment to clean: \"{fragment}\""
        cleaned_text, latency_ms = self.gemini.generate(
            system_instruction=IN_FLIGHT_SYSTEM_INSTRUCTION,
            user_prompt=user_prompt,
        )

        # Fallback safety: do not return empty if model was silent
        if not cleaned_text:
            cleaned_text = fragment

        return cleaned_text, latency_ms, False

    def finalize_stream(self, full_text: str) -> Tuple[str, float]:
        """
        Runs the final reconciliation pass once speech has finished.
        """
        full_text = full_text.strip()
        if not full_text:
            return "", 0.0

        user_prompt = f"Finalize and reconcile this transcribed text:\n\"{full_text}\""
        reconciled, latency_ms = self.gemini.generate(
            system_instruction=FINAL_PASS_SYSTEM_INSTRUCTION,
            user_prompt=user_prompt,
        )

        return reconciled if reconciled else full_text, latency_ms
