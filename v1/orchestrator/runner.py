from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional
import time

from ..decider.interface import Decider, DecisionResult
from ..cleanup.gemini_cleanup import GeminiCleanup
from ..agent.system2 import System2Agent, AgentResult


@dataclass
class OrchestratorResult:
    branch: str  # "dictation" or "command"
    output_text: str
    raw_text: str
    actions_enabled: bool
    cleanup_enabled: bool
    tools_enabled: bool
    decision: Optional[DecisionResult] = None
    cleaned_text: Optional[str] = None
    cleanup_changed: bool = False
    cleanup_discarded: bool = False
    asr_latency_ms: float = 0.0
    decider_latency_ms: float = 0.0
    cleanup_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    decider_auth_ms: float = 0.0
    decider_network_ms: float = 0.0
    cleanup_auth_ms: float = 0.0
    cleanup_network_ms: float = 0.0
    command_placeholder: Optional[str] = None
    agent_result: Optional[AgentResult] = None
    agent_latency_ms: float = 0.0
    customer: str = ""
    cleanup_future: Optional[Any] = None

    def wait_for_cleanup(self, timeout: Optional[float] = 10.0) -> float:
        """
        Waits for background cleanup if still running (outside measured path)
        and returns the recorded cleanup_latency_ms.
        """
        if self.cleanup_future:
            try:
                self.cleanup_future.result(timeout=timeout)
            except Exception:
                pass
        return self.cleanup_latency_ms


class Orchestrator:
    """
    Coordinates ASR, Decider, and Cleanup according to config switches.
    Runs decider and cleanup concurrently when actions are enabled.
    Branches early to System 2 when decider confirms command, skipping cleanup wait.
    """

    def __init__(
        self,
        decider: Decider,
        cleanup: GeminiCleanup,
        settings: Dict[str, Any],
        agent: Optional[System2Agent] = None,
    ):
        self.decider = decider
        self.cleanup = cleanup
        self.settings = settings
        self.agent = agent
        decider_cfg = settings.get("decider", {})
        self.threshold = float(
            decider_cfg.get("confidence_threshold")
            or settings.get("vertex", {}).get("confidence_threshold", 0.75)
        )
        self._executor = ThreadPoolExecutor(max_workers=4)

    def process(
        self,
        raw_text: str,
        customer_config: Optional[Dict[str, Any]] = None,
        actions: Optional[bool] = None,
        cleanup: Optional[bool] = None,
        tools: Optional[bool] = None,
        reverse_order: bool = False,
        asr_latency_ms: float = 0.0,
        reference_datetime: Optional[datetime] = None,
    ) -> OrchestratorResult:
        start_time = time.perf_counter()

        # The orchestrator reads only the switches, never customer names
        actions_enabled = (
            actions if actions is not None
            else bool(customer_config.get("actions", False)) if customer_config
            else False
        )
        cleanup_enabled = (
            cleanup if cleanup is not None
            else bool(customer_config.get("cleanup", True)) if customer_config
            else True
        )
        tools_enabled = (
            tools if tools is not None
            else bool(customer_config.get("tools", True)) if customer_config
            else True
        )
        customer_name = customer_config.get("name", "") if customer_config else ""

        decider_res: Optional[DecisionResult] = None
        cleaned_text: Optional[str] = None
        cleanup_changed: bool = False
        decider_ms = 0.0
        cleanup_ms = 0.0
        cleanup_auth_ms = 0.0
        cleanup_network_ms = 0.0
        agent_res: Optional[AgentResult] = None
        agent_ms = 0.0
        cleanup_discarded = False

        # Partition 2: Parallel processing
        future_decider = (
            self._executor.submit(self.decider.decide, raw_text, None, reverse_order)
            if actions_enabled
            else None
        )
        cleanup_result_holder = {"ms": 0.0, "auth_ms": 0.0, "net_ms": 0.0}
        if cleanup_enabled:
            def _run_cleanup():
                t_c0 = time.perf_counter()
                c_text, c_ms, c_chg, c_auth, c_net = self.cleanup.clean(raw_text)
                cleanup_result_holder["ms"] = (time.perf_counter() - t_c0) * 1000.0
                cleanup_result_holder["auth_ms"] = c_auth
                cleanup_result_holder["net_ms"] = c_net
                return c_text, c_ms, c_chg, c_auth, c_net

            future_cleanup = self._executor.submit(_run_cleanup)
        else:
            future_cleanup = None

        # Branch as soon as decider answers
        if future_decider:
            decider_res = future_decider.result()
            decider_ms = decider_res.latency_ms
        else:
            # Actions off: decider is skipped, result is dictation
            decider_res = DecisionResult(
                option="dictation",
                confidence=1.0,
                latency_ms=0.0,
                raw_response="[Skipped: actions off]",
            )
            decider_ms = 0.0

        # Partition 3: Branching
        is_confident_command = (
            actions_enabled
            and decider_res.option == "command"
            and decider_res.confidence >= self.threshold
        )

        if is_confident_command:
            # System 2: Command assistant
            # Go straight to agent with raw text; do not wait for cleanup call
            branch = "command"
            cleanup_discarded = bool(cleanup_enabled)

            if self.agent:
                agent_res = self.agent.process(
                    text=raw_text,
                    tools_enabled=tools_enabled,
                    reference_datetime=reference_datetime,
                )
                agent_ms = agent_res.latency_ms
                final_text = agent_res.reply
                command_msg = None
            else:
                command_msg = f'would call System 2 with raw text: "{raw_text.replace("。", "।")}"'
                final_text = command_msg

        else:
            # System 1: Dictation (Single unified exit)
            branch = "dictation"
            cleanup_discarded = False

            if future_cleanup:
                # Wait for cleanup result
                cleaned_text, cleanup_ms, cleanup_changed, cleanup_auth_ms, cleanup_network_ms = future_cleanup.result()
                final_text = cleaned_text
            else:
                # Cleanup off: raw text is used
                cleaned_text = raw_text
                cleanup_ms = 0.0
                cleanup_changed = False
                final_text = raw_text

            command_msg = None

        total_ms = (time.perf_counter() - start_time) * 1000.0
        result = OrchestratorResult(
            branch=branch,
            output_text=final_text.replace("。", "।"),
            raw_text=raw_text,
            actions_enabled=actions_enabled,
            cleanup_enabled=cleanup_enabled,
            tools_enabled=tools_enabled,
            decision=decider_res,
            cleaned_text=cleaned_text,
            cleanup_changed=cleanup_changed,
            cleanup_discarded=cleanup_discarded,
            asr_latency_ms=asr_latency_ms,
            decider_latency_ms=decider_ms,
            decider_auth_ms=decider_res.auth_ms if decider_res else 0.0,
            decider_network_ms=decider_res.network_ms if decider_res else 0.0,
            cleanup_latency_ms=cleanup_ms,
            cleanup_auth_ms=cleanup_auth_ms,
            cleanup_network_ms=cleanup_network_ms,
            total_latency_ms=round(total_ms, 2),
            command_placeholder=command_msg,
            agent_result=agent_res,
            agent_latency_ms=agent_ms,
            customer=customer_name,
            cleanup_future=future_cleanup,
        )

        if future_cleanup and is_confident_command:
            def _on_cleanup_done(f):
                try:
                    result.cleanup_latency_ms = round(cleanup_result_holder.get("ms", 0.0), 2)
                    result.cleanup_auth_ms = round(cleanup_result_holder.get("auth_ms", 0.0), 2)
                    result.cleanup_network_ms = round(cleanup_result_holder.get("net_ms", 0.0), 2)
                except Exception:
                    pass
            future_cleanup.add_done_callback(_on_cleanup_done)

        return result

