from dataclasses import dataclass, field
from pathlib import Path
import os

@dataclass
class CleanupConfig:
    """
    Configuration for Wispr Flow-style sentence-level dictation cleanup.
    """
    # Vertex AI configuration (Google Cloud Asia Mumbai)
    project_id: str = "tpu-project-235909"
    region: str = "asia-south1"  # Asia Mumbai
    key_file: str = str(Path(__file__).parents[2] / "vertex-key.json")
    model_name: str = "gemini-2.5-flash"
    api_key: str = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY", ""))

    # Sentence boundary & segmentation parameters
    silence_pause_sec: float = 0.35       # 350ms pause triggers sentence boundary
    min_sentence_words: int = 3           # Minimum words before committing a sentence on pause
    max_sentence_words: int = 15          # Max words before forcing segmentation if no punctuation/pause
    context_sentence_window: int = 2      # Number of previous polished sentences to feed as context

    # Generation parameters
    temperature: float = 0.0
    max_output_tokens: int = 1024
    thinking_budget: int = 0              # 0 disables reasoning tokens for sub-second cleanup
    timeout_seconds: int = 15

