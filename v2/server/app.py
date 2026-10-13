from pathlib import Path
from typing import Any, Dict, List
from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import load_settings
from ..asr.client import IndicASRClient
from ..cleaner.gemini import GeminiFlashClient
from ..cleaner.pipeline import PolishPipeline
from ..server.ws_handler import DictationWebSocketHandler
from ..engine.window_manager import WindowManager
from ..engine.session import StreamingSession

SERVER_DIR = Path(__file__).resolve().parent
V2_DIR = SERVER_DIR.parent
WEB_DIR = V2_DIR / "web"
STATIC_DIR = WEB_DIR / "static"

# Load config
settings = load_settings()
server_cfg = settings.get("server", {})
gemini_cfg = settings.get("gemini", {})
asr_cfg = settings.get("asr", {})
dictation_cfg = settings.get("dictation", {})

# Resolve key_file
key_file_raw = gemini_cfg.get("key_file", "../vertex-key.json")
key_file_path = (V2_DIR / key_file_raw).resolve()
if not key_file_path.exists():
    key_file_path = (V2_DIR.parent / "vertex-key.json").resolve()

# Initialize clients
asr_client = IndicASRClient(
    endpoint=asr_cfg.get("endpoint", "http://45.115.219.97:20009/indic/transcribe/"),
    timeout_seconds=asr_cfg.get("timeout_seconds", 20),
    sample_rate=asr_cfg.get("sample_rate", 16000),
)

gemini_client = GeminiFlashClient(
    project_id=gemini_cfg.get("project_id", "tpu-project-235909"),
    region=gemini_cfg.get("region", "asia-south1"),
    key_file=key_file_path if key_file_path.exists() else None,
    api_key=gemini_cfg.get("api_key", ""),
    model_name=gemini_cfg.get("model_name", "gemini-2.5-flash"),
    timeout_seconds=gemini_cfg.get("timeout_seconds", 15),
)

pipeline = PolishPipeline(
    gemini_client=gemini_client,
    enable_heuristics=dictation_cfg.get("enable_heuristics", True),
)

ws_handler = DictationWebSocketHandler(
    asr_client=asr_client,
    polish_pipeline=pipeline,
    word_threshold=dictation_cfg.get("word_threshold", 5),
    silence_pause_ms=dictation_cfg.get("silence_pause_ms", 300),
)

app = FastAPI(title="Open Voice V2 - Real-Time Streaming Dictation")

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
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Open Voice v2 Streaming Dictation API is running."}


@app.get("/api/status")
async def get_status():
    return {
        "status": "healthy",
        "gemini_model": gemini_cfg.get("model_name", "gemini-2.5-flash"),
        "asr_endpoint": asr_cfg.get("endpoint"),
        "word_threshold": dictation_cfg.get("word_threshold", 5),
        "silence_pause_ms": dictation_cfg.get("silence_pause_ms", 300),
        "heuristics_enabled": dictation_cfg.get("enable_heuristics", True),
        "key_file_exists": key_file_path.exists(),
    }


class SimulationRequest(BaseModel):
    words: List[str]
    pause_indices: List[int] = []


@app.post("/api/simulate")
async def simulate_streaming(req: SimulationRequest):
    """
    Simulates streaming dictation step-by-step for testing the window manager
    and in-flight polish engine.
    """
    window = WindowManager(word_threshold=dictation_cfg.get("word_threshold", 5))
    session = StreamingSession()
    steps = []

    for idx, word in enumerate(req.words):
        window.feed_text(word)
        session.record_raw(word)
        is_pause = idx in req.pause_indices

        step_record = {
            "index": idx,
            "word": word,
            "in_flight_tail": window.get_in_flight_tail(),
            "triggered": False,
        }

        if window.should_trigger(pause_detected=is_pause):
            ctx, frag = window.pop_chunk_for_cleaning()
            cleaned, lat, bypassed = pipeline.clean_in_flight(ctx, frag)
            window.commit_polished_chunk(cleaned)
            session.record_polish(cleaned, lat, bypassed=bypassed)

            step_record.update({
                "triggered": True,
                "context": ctx,
                "fragment": frag,
                "polished_chunk": cleaned,
                "bypassed": bypassed,
                "latency_ms": round(lat, 1),
                "committed_so_far": window.get_full_committed_text(),
            })

        steps.append(step_record)

    # Final pass
    if window.pending_words:
        ctx, frag = window.pop_chunk_for_cleaning()
        cleaned, lat, bypassed = pipeline.clean_in_flight(ctx, frag)
        window.commit_polished_chunk(cleaned)
        session.record_polish(cleaned, lat, bypassed=bypassed)

    full_text = window.get_full_committed_text()
    finalized, final_lat = pipeline.finalize_stream(full_text)

    return {
        "steps": steps,
        "committed_text": full_text,
        "finalized_text": finalized,
        "summary": session.get_summary(),
    }


@app.websocket("/ws/dictate")
async def websocket_dictation(websocket: WebSocket):
    await ws_handler.handle_connection(websocket)
