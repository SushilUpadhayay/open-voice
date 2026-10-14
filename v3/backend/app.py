import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, File, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..asr.client import NemotronASRClient
from ..cleanup.config import CleanupConfig
from ..cleanup.engine import WisprFlowCleanupEngine
from .ws_handler import DictationWebSocketHandler

BACKEND_DIR = Path(__file__).resolve().parent
V3_DIR = BACKEND_DIR.parent
FRONTEND_DIR = V3_DIR / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"

# Initialize ASR & Cleanup
asr_client = NemotronASRClient()
cleanup_config = CleanupConfig()
ws_handler = DictationWebSocketHandler(
    asr_client=asr_client,
    cleanup_config=cleanup_config,
    silence_pause_ms=350.0,
)

app = FastAPI(
    title="Open Voice v3 — Streaming Dictation & Wispr Flow Polish",
    description="Nemotron 3.5 Vulkan ASR + Gemini 2.5 Flash Asia Mumbai Cleanup",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def get_index():
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Open Voice v3 Streaming Dictation API is running."}


@app.get("/api/test-audio")
async def get_test_audio():
    wav_path = V3_DIR.parent / "hi3.wav"
    if wav_path.exists():
        return FileResponse(wav_path, media_type="audio/wav")
    return JSONResponse({"error": "hi3.wav not found"}, status_code=404)


@app.get("/api/status")
async def get_status():
    """
    Returns engine, GPU, and Vertex AI connectivity status.
    """
    key_file = Path(cleanup_config.key_file)
    return {
        "status": "online",
        "version": "v3.0.0",
        "asr": {
            "model": "nvidia/nemotron-3.5-asr-streaming-0.6b-Q8_0",
            "available": asr_client.is_available(),
            "backend": "Vulkan0 (NVIDIA GPU)",
            "handy_exe": str(asr_client.handy_exe),
        },
        "cleaner": {
            "provider": "Google Cloud Vertex AI",
            "region": cleanup_config.region,
            "region_name": "Asia Mumbai (asia-south1)",
            "model": cleanup_config.model_name,
            "key_file_exists": key_file.exists(),
        },
    }


class SimulationRequest(BaseModel):
    chunks: List[str]
    pause_after_indices: List[int] = []


@app.post("/api/simulate")
async def simulate_cleanup(req: SimulationRequest):
    """
    Simulates streaming dictation step-by-step with sentence-level Wispr Flow polish.
    """
    engine = WisprFlowCleanupEngine(config=cleanup_config)

    events = []
    def on_sentence(evt):
        events.append(evt)

    engine.on_sentence_polished = on_sentence

    for idx, chunk in enumerate(req.chunks):
        is_pause = idx in req.pause_after_indices
        await engine.feed_stream(chunk, is_pause=is_pause)

    result = await engine.finish_and_finalize(run_final_pass=False)

    return {
        "raw_text": result["raw_text"],
        "polished_text": result["polished_text"],
        "sentence_events": events,
        "sentences_count": result["sentences_count"],
    }


@app.post("/api/transcribe-file")
async def transcribe_uploaded_file(file: UploadFile = File(...)):
    """
    Transcribes an uploaded WAV file using Nemotron 3.5 and applies Wispr Flow cleanup.
    """
    content = await file.read()
    raw_text, asr_lat, rtf = asr_client.transcribe_pcm_bytes(content)

    cleaner = WisprFlowCleanupEngine(config=cleanup_config)
    await cleaner.feed_stream(raw_text, is_pause=True)
    res = await cleaner.finish_and_finalize(run_final_pass=False)

    return {
        "filename": file.filename,
        "asr_latency_ms": asr_lat,
        "rtf": rtf,
        "raw_text": raw_text,
        "polished_text": res["polished_text"],
        "sentences": res["sentences"],
    }


@app.websocket("/ws/dictate")
async def websocket_dictation_endpoint(websocket: WebSocket):
    """
    Full-duplex WebSocket endpoint streaming audio in and dual-buffer transcripts out.
    """
    await ws_handler.handle_connection(websocket)
