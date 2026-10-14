import asyncio
import base64
import json
import time
from typing import Optional
from fastapi import WebSocket, WebSocketDisconnect

from ..asr.client import IndicASRClient
from ..asr.vad import EnergyVAD
from ..engine.window_manager import WindowManager
from ..engine.session import StreamingSession
from ..cleaner.pipeline import PolishPipeline


class DictationWebSocketHandler:
    """
    Handles bi-directional real-time dictation over WebSocket.
    Manages audio buffer, VAD, sliding window chunking, and live Gemini polish.
    """

    def __init__(
        self,
        asr_client: IndicASRClient,
        polish_pipeline: PolishPipeline,
        word_threshold: int = 5,
        silence_pause_ms: int = 350,
    ):
        self.asr = asr_client
        self.pipeline = polish_pipeline
        self.word_threshold = word_threshold
        self.silence_pause_ms = silence_pause_ms

    async def handle_connection(self, websocket: WebSocket):
        await websocket.accept()

        session = StreamingSession()
        window = WindowManager(word_threshold=self.word_threshold)
        vad = EnergyVAD(min_silence_ms=self.silence_pause_ms)

        audio_buffer = bytearray()
        has_spoken_in_buffer = False
        last_asr_transcribe_time = time.perf_counter()

        try:
            while True:
                message = await websocket.receive()

                if "bytes" in message and message["bytes"]:
                    # Binary PCM 16kHz chunk received from client mic
                    raw_bytes = message["bytes"]
                    audio_buffer.extend(raw_bytes)
                    session.audio_chunks_received += 1

                    chunk_ms = (len(raw_bytes) / 2) / 16.0
                    is_speech = vad.is_speech_frame(raw_bytes)
                    if is_speech:
                        has_spoken_in_buffer = True

                    is_pause = vad.update_and_check_pause(raw_bytes, chunk_ms)
                    now = time.perf_counter()

                    # Trigger criteria for ASR:
                    # 1. User paused (silence >= 350ms) AND we have accumulated at least 0.8s of audio
                    # 2. Continuous speech exceeded 2.5s (to prevent latency buildup)
                    should_transcribe = False
                    if has_spoken_in_buffer:
                        if is_pause and len(audio_buffer) >= 25600:  # 0.8s * 32000 bytes/sec
                            should_transcribe = True
                        elif (now - last_asr_transcribe_time >= 2.5) and len(audio_buffer) >= 64000:  # 2.0s
                            should_transcribe = True

                    if should_transcribe:
                        last_asr_transcribe_time = now
                        wav_bytes = self.asr.pcm_to_wav_bytes(bytes(audio_buffer))
                        audio_buffer.clear()
                        has_spoken_in_buffer = False

                        raw_text, asr_latency = await asyncio.to_thread(
                            self.asr.transcribe_wav_bytes, wav_bytes
                        )

                        if raw_text:
                            session.record_raw(raw_text)
                            window.feed_text(raw_text)

                            await websocket.send_json({
                                "type": "raw_tail",
                                "tail": window.get_in_flight_tail(),
                                "asr_latency_ms": round(asr_latency, 1),
                            })

                            if window.should_trigger(pause_detected=is_pause):
                                ctx, frag = window.pop_chunk_for_cleaning()
                                cleaned, polish_lat, bypassed = await asyncio.to_thread(
                                    self.pipeline.clean_in_flight, ctx, frag
                                )
                                window.commit_polished_chunk(cleaned)
                                session.record_polish(cleaned, polish_lat, bypassed=bypassed)

                                await websocket.send_json({
                                    "type": "commit_chunk",
                                    "chunk": cleaned,
                                    "full_polished": window.get_full_committed_text(),
                                    "tail": window.get_in_flight_tail(),
                                    "latency_ms": round(polish_lat, 1),
                                    "bypassed": bypassed,
                                })

                elif "text" in message and message["text"]:
                    data = json.loads(message["text"])
                    msg_type = data.get("type", "")

                    if msg_type == "text_chunk":
                        # Text simulation mode
                        incoming_text = data.get("text", "")
                        session.record_raw(incoming_text)
                        window.feed_text(incoming_text)

                        await websocket.send_json({
                            "type": "raw_tail",
                            "tail": window.get_in_flight_tail(),
                        })

                        if window.should_trigger(pause_detected=data.get("pause", False)):
                            ctx, frag = window.pop_chunk_for_cleaning()
                            cleaned, polish_lat, bypassed = await asyncio.to_thread(
                                self.pipeline.clean_in_flight, ctx, frag
                            )
                            window.commit_polished_chunk(cleaned)
                            session.record_polish(cleaned, polish_lat, bypassed=bypassed)

                            await websocket.send_json({
                                "type": "commit_chunk",
                                "chunk": cleaned,
                                "full_polished": window.get_full_committed_text(),
                                "tail": window.get_in_flight_tail(),
                                "latency_ms": round(polish_lat, 1),
                                "bypassed": bypassed,
                            })

                    elif msg_type == "stop":
                        # User clicked stop: Transcribe any remaining audio first!
                        if len(audio_buffer) >= 9600:  # At least 300ms of audio
                            wav_bytes = self.asr.pcm_to_wav_bytes(bytes(audio_buffer))
                            audio_buffer.clear()
                            raw_text, _ = await asyncio.to_thread(
                                self.asr.transcribe_wav_bytes, wav_bytes
                            )
                            if raw_text:
                                session.record_raw(raw_text)
                                window.feed_text(raw_text)

                        # Drain remaining words from window
                        if window.pending_words:
                            ctx, frag = window.pop_chunk_for_cleaning()
                            cleaned, polish_lat, bypassed = await asyncio.to_thread(
                                self.pipeline.clean_in_flight, ctx, frag
                            )
                            window.commit_polished_chunk(cleaned)
                            session.record_polish(cleaned, polish_lat, bypassed=bypassed)

                        full_text = window.get_full_committed_text()

                        # Run final reconciliation pass
                        if full_text.strip():
                            finalized_text, final_lat = await asyncio.to_thread(
                                self.pipeline.finalize_stream, full_text
                            )
                        else:
                            finalized_text, final_lat = "", 0.0

                        await websocket.send_json({
                            "type": "finalized",
                            "full_text": finalized_text,
                            "latency_ms": round(final_lat, 1),
                            "summary": session.get_summary(),
                        })

                        # Reset buffers for next turn
                        window.reset()
                        audio_buffer.clear()
                        has_spoken_in_buffer = False
                        vad.reset()

        except WebSocketDisconnect:
            pass
