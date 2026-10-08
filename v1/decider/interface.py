from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class DecisionResult:
    option: str  # e.g., "dictation", "command", "unclear"
    confidence: float  # 0.0 to 1.0
    option_probabilities: Dict[str, float] = field(default_factory=dict)
    latency_ms: float = 0.0
    auth_ms: float = 0.0
    network_ms: float = 0.0
    raw_response: Optional[str] = None

class Decider(ABC):
    """Abstract base class for all decider implementations."""

    @abstractmethod
    def decide(
        self,
        text: str,
        options: Optional[List[str]] = None,
        reverse_order: bool = False,
    ) -> DecisionResult:
        """
        Classifies input text according to options.

        Args:
            text: Raw input speech text in Devanagari.
            options: List of choices (default: ["dictation", "command", "unclear"]).
            reverse_order: Whether to present options in reversed order for order testing.

        Returns:
            DecisionResult containing the chosen option, confidence, and timings.
        """
        pass
