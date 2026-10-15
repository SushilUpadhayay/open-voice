import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, File, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..asr.client import HandyASRClient
from ..cleanup.config import CleanupConfig
from ..cleanup.engine import WisprFlowCleanupEngine
from .ws_handler import DictationWebSocketHandler

BACKEND_DIR = Path(__file__).resolve().parent
DICTATION_DIR = BACKEND_DIR.parent
FRONTEND_DIR = DICTATION_DIR / "frontend"
STATIC_DIR = FRONTEND_DIR / "static"

# Initialize ASR & Cleanup
asr_client = HandyASRClient()
cleanup_config = CleanupConfig()
ws_handler = DictationWebSocketHandler(
    asr_client=asr_client,
    cleanup_config=cleanup_config,
    silence_pause_ms=350.0,
    session_pause_ms=3000.0,
)

app = FastAPI(
    title="Open Voice Dictation — Streaming Dictation & Wispr Flow Polish",
<<<<<<< HEAD
    description="Parakeet Unified EN Vulkan ASR + Gemini 2.5 Flash Asia Mumbai Cleanup",
=======
    description="Parakeet Unified EN 0.6B ASR + Gemini 2.5 Flash Asia Mumbai Cleanup",
>>>>>>> 2dc7fb33e284c705fab3378cfe353f1ab4ccac70
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
    return {"message": "Open Voice Dictation Streaming Dictation API is running."}


@app.get("/api/test-audio")
async def get_test_audio():
    wav_path = DICTATION_DIR.parent / "hi3.wav"
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
            "model": asr_client.model_id,
<<<<<<< HEAD
=======
            "model_name": "Parakeet Unified EN 0.6B",
>>>>>>> 2dc7fb33e284c705fab3378cfe353f1ab4ccac70
            "available": asr_client.is_available(),
            "engine_available": asr_client.handy_exe.exists(),
            "model_downloaded": asr_client.is_model_downloaded(),
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
    Transcribes an uploaded WAV file using Parakeet Unified EN and applies Wispr Flow cleanup.
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
