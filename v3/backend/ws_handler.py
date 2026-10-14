import asyncio
import json
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect

from ..asr import NemotronStreamSession, NemotronASRClient
from ..cleanup import WisprFlowCleanupEngine, CleanupConfig


class DictationWebSocketHandler:
    """
    Integration layer connecting client WebSocket transport to:
    - v3/asr: NemotronStreamSession (all ASR & VAD running logic)
    - v3/cleanup: WisprFlowCleanupEngine (all cleanup & LLM polish running logic)
    """

    def __init__(
        self,
        asr_client: Optional[NemotronASRClient] = None,
        cleanup_config: Optional[CleanupConfig] = None,
        silence_pause_ms: float = 350.0,
    ):
        self.asr_client = asr_client or NemotronASRClient()
        self.cleanup_config = cleanup_config or CleanupConfig()
        self.silence_pause_ms = silence_pause_ms

    async def handle_connection(self, websocket: WebSocket):
        await websocket.accept()

        # 1. Initialize ASR running session (owns audio buffer and VAD)
        asr_session = NemotronStreamSession(
            asr_client=self.asr_client,
            silence_pause_ms=self.silence_pause_ms,
        )

        # 2. Initialize Cleanup running engine (owns Wispr Flow segmentation and Gemini polish)
        async def on_sentence_polished_event(event):
            try:
                await websocket.send_json({
                    "type": "sentence_polished",
                    "sentence_index": event["sentence_index"],
                    "raw_sentence": event["raw_sentence"],
                    "polished_sentence": event["polished_sentence"],
                    "latency_ms": event["latency_ms"],
                    "timestamp": event["timestamp"],
                })
            except Exception:
                pass

        cleaner = WisprFlowCleanupEngine(
            config=self.cleanup_config,
            on_sentence_polished=lambda evt: asyncio.create_task(on_sentence_polished_event(evt)),
        )

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
                        })

                        # Feed into Cleanup module (dispatches concurrent Wispr Flow polish)
                        await cleaner.feed_stream(asr_chunk.text, is_pause=asr_chunk.is_pause)

                # Case B: Control signals (stop, reset)
                elif "text" in message and message["text"]:
                    data = json.loads(message["text"])
                    msg_type = data.get("type")

                    if msg_type == "stop":
                        # Flush any remaining uncommitted audio in ASR module
                        final_asr = await asr_session.flush()
                        if final_asr:
                            await websocket.send_json({
                                "type": "raw_tail",
                                "tail": final_asr.text,
                                "asr_latency_ms": final_asr.latency_ms,
                                "rtf": final_asr.rtf,
                            })
                            await cleaner.feed_stream(final_asr.text, is_pause=True)

                        # Finalize cleanup module and wait for all background LLM tasks
                        final_doc = await cleaner.finish_and_finalize(run_final_pass=False)

                        await websocket.send_json({
                            "type": "finalized",
                            "raw_text": final_doc["raw_text"],
                            "polished_text": final_doc["polished_text"],
                            "sentences_count": final_doc["sentences_count"],
                        })

                    elif msg_type == "reset":
                        asr_session.reset()

        except WebSocketDisconnect:
            pass
        except Exception as e:
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass
