import asyncio
import json
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect

from ..asr import ASRStreamSession, HandyASRClient
from ..cleanup import WisprFlowCleanupEngine, CleanupConfig


class DictationWebSocketHandler:
    """
    Integration layer connecting client WebSocket transport to:
    - dictation/asr: streaming ASR session (all ASR & VAD running logic)
    - dictation/cleanup: WisprFlowCleanupEngine (all cleanup & LLM polish running logic)
    """

    def __init__(
        self,
        asr_client: Optional[HandyASRClient] = None,
        cleanup_config: Optional[CleanupConfig] = None,
        silence_pause_ms: float = 350.0,
        session_pause_ms: float = 3000.0,
    ):
        self.asr_client = asr_client or HandyASRClient()
        self.cleanup_config = cleanup_config or CleanupConfig()
        self.silence_pause_ms = silence_pause_ms
        self.session_pause_ms = session_pause_ms

    async def handle_connection(self, websocket: WebSocket):
        await websocket.accept()

        # 1. Initialize ASR running session (owns audio buffer and VAD)
        asr_session = ASRStreamSession(
            asr_client=self.asr_client,
            silence_pause_ms=self.silence_pause_ms,
            session_pause_ms=self.session_pause_ms,
        )

        # 2. Initialize Cleanup running engine (owns Wispr Flow segmentation and Gemini polish)
        async def on_sentence_started_event(event):
            try:
                await websocket.send_json({
                    "type": "sentence_cleaning",
                    "sentence_id": event["sentence_id"],
                    "sentence_index": event["sentence_index"],
                    "raw_sentence": event["raw_sentence"],
                })
            except Exception:
                pass

        async def on_sentence_polished_event(event):
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

        async def finalize_session(reason: str = "manual"):
            # Flush any remaining uncommitted audio in ASR module
            final_asr = await asr_session.flush()
            if final_asr:
                await websocket.send_json({
                    "type": "raw_tail",
                    "tail": final_asr.text,
                    "asr_latency_ms": final_asr.latency_ms,
                    "rtf": final_asr.rtf,
                    "tps": final_asr.tps,
                })
                await cleaner.feed_stream(final_asr.text, is_pause=True)

            # Finalize cleanup module and wait for all background LLM tasks
            final_doc = await cleaner.finish_and_finalize(run_final_pass=False)

            # Yield briefly to ensure any queued on_sentence_polished tasks are flushed
            await asyncio.sleep(0.05)

            await websocket.send_json({
                "type": "finalized",
                "raw_text": final_doc["raw_text"],
                "polished_text": final_doc["polished_text"],
                "sentences_count": final_doc["sentences_count"],
                "session_ended": True,
                "reason": reason,
            })
            asr_session.reset()

        try:
            while True:
                message = await websocket.receive()

                # Case A: Audio bytes streamed from browser mic
                if "bytes" in message and message["bytes"]:
                    raw_bytes = message["bytes"]

                    # ASR module handles buffer accumulation, VAD, and transcription trigger
                    asr_chunk = await asr_session.feed_audio(raw_bytes)

                    if asr_chunk:
                        # Forward instant verbatim preview to frontend
                        await websocket.send_json({
                            "type": "raw_tail",
                            "tail": asr_chunk.text,
                            "asr_latency_ms": asr_chunk.latency_ms,
                            "rtf": asr_chunk.rtf,
                            "tps": asr_chunk.tps,
                        })

                        # Feed into Cleanup module (dispatches concurrent Wispr Flow polish)
                        await cleaner.feed_stream(asr_chunk.text, is_pause=asr_chunk.is_pause)

                    # Auto-stop dictation session after the configured silence pause.
                    if asr_session.should_end_session():
                        await finalize_session(reason="pause_timeout")

                # Case B: Control signals (stop, reset, text_input)
                elif "text" in message and message["text"]:
                    data = json.loads(message["text"])
                    msg_type = data.get("type")

                    if msg_type == "stop":
                        await finalize_session(reason="manual")

                    elif msg_type == "reset":
                        asr_session.reset()
                        cleaner.reset()

                    elif msg_type == "text_input":
                        await cleaner.feed_typed_text(data.get("text", ""))

        except WebSocketDisconnect:
            pass
        except Exception as e:
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass
