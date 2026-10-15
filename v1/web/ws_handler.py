import asyncio
import json
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from fastapi import WebSocket, WebSocketDisconnect

from dictation.asr.stream import ASRStreamSession
from dictation.asr.client import HandyASRClient
from dictation.cleanup.config import CleanupConfig
from dictation.cleanup.engine import WisprFlowCleanupEngine
from v1.orchestrator.runner import Orchestrator, OrchestratorResult
from v1.decider.interface import DecisionResult
from v1.web.cards import build_card_data

logger = logging.getLogger(__name__)


class V1StreamingWebSocketHandler:
    """
    Real-time streaming integration handler for V1.
    Directly connects:
    - dictation/asr.stream (ASRStreamSession) for live low-latency speech recognition
    - dictation/cleanup.engine (WisprFlowCleanupEngine) for concurrent Wispr Flow sentence polish
    - V1 Decider and System 2 Agent for concurrent classification and command execution
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        asr_client: Optional[HandyASRClient] = None,
        cleanup_config: Optional[CleanupConfig] = None,
        silence_pause_ms: float = 350.0,
        session_pause_ms: float = 3000.0,
    ):
        self.orchestrator = orchestrator
        self.asr_client = asr_client or HandyASRClient()
        self.cleanup_config = cleanup_config or CleanupConfig()
        self.silence_pause_ms = silence_pause_ms
        self.session_pause_ms = session_pause_ms

    async def handle_connection(self, websocket: WebSocket):
        await websocket.accept()

        switches: Dict[str, bool] = {
            "actions": False,
            "cleanup": True,
            "tools": True,
        }

        asr_session = ASRStreamSession(
            asr_client=self.asr_client,
            silence_pause_ms=self.silence_pause_ms,
            session_pause_ms=self.session_pause_ms,
        )

        accumulated_raw_chunks: List[str] = []
        total_asr_ms: float = 0.0
        session_start_time = time.perf_counter()
        decider_result: Optional[DecisionResult] = None
        decider_task: Optional[asyncio.Task] = None

        async def on_sentence_started_event(event: Dict[str, Any]):
            try:
                await websocket.send_json({
                    "type": "sentence_cleaning",
                    "sentence_id": event["sentence_id"],
                    "sentence_index": event["sentence_index"],
                    "raw_sentence": event["raw_sentence"],
                })
            except Exception:
                pass

        async def on_sentence_polished_event(event: Dict[str, Any]):
            try:
                await websocket.send_json({
                    "type": "sentence_polished",
                    "sentence_id": event["sentence_id"],
                    "sentence_index": event["sentence_index"],
                    "raw_sentence": event["raw_sentence"],
                    "polished_sentence": event["polished_sentence"],
                    "latency_ms": event["latency_ms"],
                    "tps": event.get("tps", 0.0),
                    "timestamp": event["timestamp"],
                })
            except Exception:
                pass

        cleaner = WisprFlowCleanupEngine(
            config=self.cleanup_config,
            on_sentence_started=lambda evt: asyncio.create_task(on_sentence_started_event(evt)),
            on_sentence_polished=lambda evt: asyncio.create_task(on_sentence_polished_event(evt)),
        )
        if hasattr(self.orchestrator, "cleanup") and hasattr(self.orchestrator.cleanup, "client"):
            cleaner.client = self.orchestrator.cleanup.client

        async def _run_decider_async(text_to_decide: str):
            nonlocal decider_result
            if not switches.get("actions", False):
                return
            try:
                res = await asyncio.to_thread(self.orchestrator.decider.decide, text_to_decide)
                decider_result = res
                await websocket.send_json({
                    "type": "branch_decided",
                    "branch": res.option,
                    "confidence": round(res.confidence, 4),
                    "decider_latency_ms": round(res.latency_ms, 1),
                })
            except Exception as exc:
                logger.error("Streaming decider background run failed: %s", exc)

        async def finalize_session(reason: str = "manual"):
            nonlocal decider_task, decider_result, total_asr_ms
            # 1. Flush any uncommitted audio in ASR
            final_asr = await asr_session.flush()
            if final_asr:
                accumulated_raw_chunks.append(final_asr.text)
                total_asr_ms += final_asr.latency_ms
                await websocket.send_json({
                    "type": "raw_tail",
                    "tail": final_asr.text,
                    "asr_latency_ms": final_asr.latency_ms,
                    "rtf": final_asr.rtf,
                    "tps": final_asr.tps,
                })
                if switches.get("cleanup", True):
                    await cleaner.feed_stream(final_asr.text, is_pause=True)

            # 2. Finalize Wispr Flow cleanup engine
            final_doc = await cleaner.finish_and_finalize(run_final_pass=False)
            await asyncio.sleep(0.04)

            full_raw = final_doc.get("raw_text") or " ".join(accumulated_raw_chunks).strip()
            full_polished = final_doc.get("polished_text") or full_raw

            actions_enabled = switches.get("actions", False)
            cleanup_enabled = switches.get("cleanup", True)
            tools_enabled = switches.get("tools", True)

            decider_ms = 0.0
            agent_ms = 0.0
            agent_res = None
            reply_text = None
            cleanup_discarded = False

            if actions_enabled:
                if decider_task and not decider_task.done():
                    await decider_task
                elif decider_result is None and full_raw:
                    decider_result = await asyncio.to_thread(self.orchestrator.decider.decide, full_raw)

                if decider_result:
                    decider_ms = decider_result.latency_ms

                threshold = getattr(self.orchestrator, "threshold", 0.75)
                is_confident_command = (
                    decider_result is not None
                    and decider_result.option == "command"
                    and decider_result.confidence >= threshold
                )

                if is_confident_command:
                    branch = "command"
                    cleanup_discarded = bool(cleanup_enabled)
                    if self.orchestrator.agent:
                        agent_res = await asyncio.to_thread(
                            self.orchestrator.agent.process,
                            text=full_raw,
                            tools_enabled=tools_enabled,
                        )
                        agent_ms = agent_res.latency_ms
                        final_output = agent_res.reply
                        reply_text = agent_res.reply
                    else:
                        final_output = f'would call System 2 with raw text: "{full_raw}"'
                        reply_text = final_output
                else:
                    branch = "dictation"
                    final_output = full_polished if cleanup_enabled else full_raw
            else:
                branch = "dictation"
                final_output = full_polished if cleanup_enabled else full_raw

            total_latency_ms = (time.perf_counter() - session_start_time) * 1000.0

            orch_res = OrchestratorResult(
                branch=branch,
                output_text=final_output,
                raw_text=full_raw,
                actions_enabled=actions_enabled,
                cleanup_enabled=cleanup_enabled,
                tools_enabled=tools_enabled,
                decision=decider_result,
                cleaned_text=full_polished if cleanup_enabled else None,
                cleanup_changed=bool(full_polished.strip() != full_raw.strip()) if cleanup_enabled else False,
                cleanup_discarded=cleanup_discarded,
                asr_latency_ms=round(total_asr_ms, 1),
                decider_latency_ms=round(decider_ms, 1),
                cleanup_latency_ms=round(total_latency_ms, 1),
                total_latency_ms=round(total_latency_ms, 1),
                agent_result=agent_res,
                agent_latency_ms=round(agent_ms, 1),
            )

            card_data = build_card_data(orch_res)

            decision_info = None
            if decider_result:
                decision_info = {
                    "option": decider_result.option,
                    "confidence": round(decider_result.confidence, 4),
                    "skipped": decider_ms == 0.0,
                }

            agent_outcome = agent_res.outcome if agent_res else None
            tool_name = agent_res.tool_name if agent_res else None
            tool_args = agent_res.tool_args if agent_res else None
            tool_call_latency_ms = agent_res.tool_call_latency_ms if agent_res else 0.0

            payload = {
                "type": "finalized",
                "raw_text": full_raw,
                "cleaned_text": full_polished if cleanup_enabled else full_raw,
                "branch": branch,
                "output_text": final_output,
                "reply_text": reply_text,
                "decision": decision_info,
                "agent": {
                    "outcome": agent_outcome,
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                },
                "card": card_data,
                "switches": switches,
                "timings": {
                    "asr_ms": round(total_asr_ms, 1),
                    "decider_ms": round(decider_ms, 1),
                    "cleanup_ms": round(total_latency_ms, 1),
                    "cleanup_discarded": cleanup_discarded,
                    "agent_ms": round(agent_ms, 1),
                    "tool_call_ms": round(tool_call_latency_ms, 2),
                    "pipeline_total_ms": round(total_latency_ms, 1),
                    "total_ms": round(total_latency_ms, 1),
                },
                "session_ended": True,
                "reason": reason,
                "sentences_count": final_doc.get("sentences_count", 0),
            }
            await websocket.send_json(payload)

            # Reset session state
            asr_session.reset()
            cleaner.reset()
            accumulated_raw_chunks.clear()
            decider_task = None
            decider_result = None

        try:
            while True:
                message = await websocket.receive()
                if "bytes" in message and message["bytes"]:
                    raw_bytes = message["bytes"]
                    asr_chunk = await asr_session.feed_audio(raw_bytes)
                    if asr_chunk:
                        accumulated_raw_chunks.append(asr_chunk.text)
                        total_asr_ms += asr_chunk.latency_ms
                        await websocket.send_json({
                            "type": "raw_tail",
                            "tail": asr_chunk.text,
                            "asr_latency_ms": asr_chunk.latency_ms,
                            "rtf": asr_chunk.rtf,
                            "tps": asr_chunk.tps,
                        })
                        if switches.get("cleanup", True):
                            await cleaner.feed_stream(asr_chunk.text, is_pause=asr_chunk.is_pause)

                        if switches.get("actions", False) and decider_task is None and decider_result is None:
                            current_full = " ".join(accumulated_raw_chunks)
                            decider_task = asyncio.create_task(_run_decider_async(current_full))

                    if asr_session.should_end_session():
                        await finalize_session(reason="pause_timeout")

                elif "text" in message and message["text"]:
                    data = json.loads(message["text"])
                    msg_type = data.get("type")
                    if msg_type == "config":
                        switches.update({
                            "actions": bool(data.get("actions", switches.get("actions"))),
                            "cleanup": bool(data.get("cleanup", switches.get("cleanup"))),
                            "tools": bool(data.get("tools", switches.get("tools"))),
                        })
                        session_start_time = time.perf_counter()
                    elif msg_type == "stop":
                        await finalize_session(reason="manual")
                    elif msg_type == "reset":
                        asr_session.reset()
                        cleaner.reset()
                        accumulated_raw_chunks.clear()
                        decider_task = None
                        decider_result = None
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            try:
                await websocket.send_json({"type": "error", "message": str(exc)})
            except Exception:
                pass
