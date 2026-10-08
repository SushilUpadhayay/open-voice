from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, Optional
import time

from ..decider.interface import Decider, DecisionResult
from ..cleanup.gemini_cleanup import GeminiCleanup


@dataclass
class OrchestratorResult:
    branch: str  # "dictation" or "command"
    output_text: str
    raw_text: str
    customer: str
    actions_enabled: bool
    cleanup_enabled: bool
    decision: Optional[DecisionResult] = None
    cleaned_text: Optional[str] = None
    cleanup_changed: bool = False
    asr_latency_ms: float = 0.0
    decider_latency_ms: float = 0.0
    cleanup_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    decider_auth_ms: float = 0.0
    decider_network_ms: float = 0.0
    cleanup_auth_ms: float = 0.0
    cleanup_network_ms: float = 0.0
    command_placeholder: Optional[str] = None


class Orchestrator:
    """
    Coordinates ASR, Decider, and Cleanup according to customer config.
    Runs decider and cleanup concurrently when actions are enabled.
    """

    def __init__(
        self,
        decider: Decider,
        cleanup: GeminiCleanup,
        settings: Dict[str, Any],
    ):
        self.decider = decider
        self.cleanup = cleanup
        self.settings = settings
        self.threshold = float(
            settings.get("vertex", {}).get("confidence_threshold", 0.75)
        )

    def process(
        self,
        raw_text: str,
        customer_config: Dict[str, Any],
        reverse_order: bool = False,
        asr_latency_ms: float = 0.0,
    ) -> OrchestratorResult:
        start_time = time.perf_counter()
        customer_name = customer_config.get("name", "unknown")
        actions_enabled = bool(customer_config.get("actions", False))
        cleanup_enabled = bool(customer_config.get("cleanup", True))

        decider_res: Optional[DecisionResult] = None
        cleaned_text: Optional[str] = None
        cleanup_changed: bool = False
        decider_ms = 0.0
        cleanup_ms = 0.0
        cleanup_auth_ms = 0.0
        cleanup_network_ms = 0.0

        if not actions_enabled:
            # Actions OFF: skip decider, treat everything as dictation
            if cleanup_enabled:
                cleaned_text, cleanup_ms, cleanup_changed, cleanup_auth_ms, cleanup_network_ms = self.cleanup.clean(raw_text)
                final_text = cleaned_text
            else:
                final_text = raw_text

            total_ms = (time.perf_counter() - start_time) * 1000.0
            return OrchestratorResult(
                branch="dictation",
                output_text=final_text.replace("。", "।"),
                raw_text=raw_text,
                customer=customer_name,
                actions_enabled=actions_enabled,
                cleanup_enabled=cleanup_enabled,
                decision=None,
                cleaned_text=cleaned_text,
                cleanup_changed=cleanup_changed,
                asr_latency_ms=asr_latency_ms,
                decider_latency_ms=0.0,
                cleanup_latency_ms=cleanup_ms,
                cleanup_auth_ms=cleanup_auth_ms,
                cleanup_network_ms=cleanup_network_ms,
                total_latency_ms=round(total_ms, 2),
            )

        # Actions ON: Run decider and cleanup in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_decider = executor.submit(
                self.decider.decide, raw_text, None, reverse_order
            )
            future_cleanup = (
                executor.submit(self.cleanup.clean, raw_text)
                if cleanup_enabled
                else None
            )

            decider_res = future_decider.result()
            decider_ms = decider_res.latency_ms

            if future_cleanup:
                cleaned_text, cleanup_ms, cleanup_changed, cleanup_auth_ms, cleanup_network_ms = future_cleanup.result()
            else:
                cleaned_text = raw_text
                cleanup_ms = 0.0
                cleanup_changed = False

        # Branching rules
        is_confident_command = (
            decider_res.option == "command"
            and decider_res.confidence >= self.threshold
        )

        if is_confident_command:
            branch = "command"
            command_msg = f'would call System 2 with raw text: "{raw_text.replace("。", "।")}"'
            final_text = command_msg
        else:
            branch = "dictation"
            final_text = cleaned_text if cleanup_enabled else raw_text
            command_msg = None

        total_ms = (time.perf_counter() - start_time) * 1000.0
        return OrchestratorResult(
            branch=branch,
            output_text=final_text.replace("。", "।"),
            raw_text=raw_text,
            customer=customer_name,
            actions_enabled=actions_enabled,
            cleanup_enabled=cleanup_enabled,
            decision=decider_res,
            cleaned_text=cleaned_text,
            cleanup_changed=cleanup_changed,
            asr_latency_ms=asr_latency_ms,
            decider_latency_ms=decider_ms,
            decider_auth_ms=decider_res.auth_ms if decider_res else 0.0,
            decider_network_ms=decider_res.network_ms if decider_res else 0.0,
            cleanup_latency_ms=cleanup_ms,
            cleanup_auth_ms=cleanup_auth_ms,
            cleanup_network_ms=cleanup_network_ms,
            total_latency_ms=round(total_ms, 2),
            command_placeholder=command_msg,
        )

