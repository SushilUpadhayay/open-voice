from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import os
import tempfile
import time

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Path setup
WEB_DIR = Path(__file__).resolve().parent
V1_DIR = WEB_DIR.parent
WORKSPACE_ROOT = V1_DIR.parent
STATIC_DIR = WEB_DIR / "static"

import sys
for p in [str(WORKSPACE_ROOT), str(V1_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from v1.config import load_settings
from v1.asr.client import IndicConformerClient
from v1.decider.gemini_decider import GeminiDecider
from v1.cleanup.gemini_cleanup import GeminiCleanup
from v1.agent.system2 import System2Agent
from v1.orchestrator.runner import Orchestrator
from v1.tts.vertex_tts import VertexTTS
from v1.web.cards import build_card_data

# Initialize components
settings = load_settings()
vertex_cfg = settings.get("vertex", {})
asr_cfg = settings.get("asr", {})

key_file = (V1_DIR / vertex_cfg.get("key_file", "../vertex-key.json")).resolve()
if not key_file.exists():
    key_file = (WORKSPACE_ROOT / "vertex-key.json").resolve()

tool_log_path = V1_DIR / "results" / "tool_calls.log"

decider = GeminiDecider(
    project_id=vertex_cfg["project_id"],
    region=vertex_cfg["region"],
    key_file=key_file,
    model_name=vertex_cfg.get("decider_model", "gemini-2.5-flash"),
)
cleanup = GeminiCleanup(
    project_id=vertex_cfg["project_id"],
    region=vertex_cfg["region"],
    key_file=key_file,
    model_name=vertex_cfg.get("cleanup_model", "gemini-2.5-flash"),
)
agent = System2Agent(
    project_id=vertex_cfg["project_id"],
    region=vertex_cfg["region"],
    key_file=key_file,
    model_name=vertex_cfg.get("agent_model", "gemini-2.5-flash"),
    log_path=tool_log_path,
)
orchestrator = Orchestrator(
    decider=decider,
    cleanup=cleanup,
    settings=settings,
    agent=agent,
)
asr_client = IndicConformerClient(
    endpoint=asr_cfg["endpoint"],
    timeout_seconds=asr_cfg.get("timeout_seconds", 30),
)
tts_client = VertexTTS(
    key_file=key_file,
    primary_lang="ne-NP",
    fallback_lang="hi-IN",
    fallback_voice="hi-IN-Neural2-A",
)

app = FastAPI(title="Open Voice V3 - Web Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProcessTextRequest(BaseModel):
    text: str
    actions: bool = True
    cleanup: bool = True
    tools: bool = True


class TTSRequest(BaseModel):
    text: str


@app.get("/")
async def get_index():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(index_file)


@app.post("/api/process")
async def process_input(
    request: Request,
    text: Optional[str] = Form(None),
    actions: bool = Form(True),
    cleanup: bool = Form(True),
    tools: bool = Form(True),
    audio: Optional[UploadFile] = File(None),
):
    """
    Unified endpoint for speech or text input.
    Accepts both multipart form (with optional audio file) and JSON body.
    """
    total_start = time.perf_counter()
    raw_text = ""
    asr_latency_ms = 0.0

    # Handle JSON body if Content-Type is application/json
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        raw_text = body.get("text", "").strip()
        actions = bool(body.get("actions", True))
        cleanup = bool(body.get("cleanup", True))
        tools = bool(body.get("tools", True))

    elif audio is not None:
        # Audio file provided
        audio_bytes = await audio.read()
        if len(audio_bytes) == 0:
            raise HTTPException(status_code=400, detail="Empty audio file provided")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = Path(tmp.name)

        try:
            raw_text, asr_latency_ms = asr_client.transcribe(tmp_path)
        finally:
            if tmp_path.exists():
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

    elif text:
        raw_text = text.strip()

    if not raw_text:
        raise HTTPException(
            status_code=400,
            detail="No input text or audio could be transcribed.",
        )

    # Execute Orchestrator
    orch_result = orchestrator.process(
        raw_text=raw_text,
        actions=actions,
        cleanup=cleanup,
        tools=tools,
        asr_latency_ms=asr_latency_ms,
        reference_datetime=datetime.now(),
    )

    total_latency_ms = (time.perf_counter() - total_start) * 1000.0

    # Build response payload
    card_data = build_card_data(orch_result)

    agent_outcome = None
    tool_name = None
    tool_args = None
    tool_call_latency_ms = 0.0
    reply_text = None

    if orch_result.agent_result:
        agent_outcome = orch_result.agent_result.outcome
        tool_name = orch_result.agent_result.tool_name
        tool_args = orch_result.agent_result.tool_args
        tool_call_latency_ms = orch_result.agent_result.tool_call_latency_ms
        reply_text = orch_result.agent_result.reply
    elif orch_result.branch == "command":
        reply_text = orch_result.output_text

    decision_info = None
    if orch_result.decision:
        decision_info = {
            "option": orch_result.decision.option,
            "confidence": round(orch_result.decision.confidence, 4),
            "skipped": orch_result.decider_latency_ms == 0.0,
        }

    response_payload = {
        "raw_text": orch_result.raw_text,
        "cleaned_text": orch_result.cleaned_text or orch_result.raw_text,
        "branch": orch_result.branch,
        "output_text": orch_result.output_text,
        "reply_text": reply_text,
        "decision": decision_info,
        "agent": {
            "outcome": agent_outcome,
            "tool_name": tool_name,
            "tool_args": tool_args,
        },
        "card": card_data,
        "switches": {
            "actions": actions,
            "cleanup": cleanup,
            "tools": tools,
        },
        "timings": {
            "asr_ms": round(asr_latency_ms, 1),
            "decider_ms": round(orch_result.decider_latency_ms, 1),
            "cleanup_ms": round(orch_result.cleanup_latency_ms, 1),
            "cleanup_discarded": orch_result.cleanup_discarded,
            "agent_ms": round(orch_result.agent_latency_ms, 1),
            "tool_call_ms": round(tool_call_latency_ms, 2),
            "pipeline_total_ms": round(orch_result.total_latency_ms, 1),
            "total_ms": round(total_latency_ms, 1),
        },
    }

    return JSONResponse(content=response_payload)


@app.post("/api/tts")
async def synthesize_speech(req: TTSRequest):
    """
    Synthesizes reply text to MP3 audio and streams it.
    """
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Empty text provided for TTS")

    try:
        audio_bytes, latency_ms = tts_client.synthesize(text)
        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "X-TTS-Latency-MS": str(latency_ms),
                "Cache-Control": "public, max-age=3600",
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS error: {str(e)}")


@app.get("/api/tools/log")
async def get_tool_log(limit: int = 5):
    """
    Returns the last 5 dummy tool calls logged in results/tool_calls.log.
    """
    if not tool_log_path.exists():
        return {"logs": []}

    try:
        with open(tool_log_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]

        recent = lines[-limit:]
        parsed_logs = []
        for line in reversed(recent):
            try:
                parsed_logs.append(json.loads(line))
            except Exception:
                parsed_logs.append({"raw": line})

        return {"logs": parsed_logs}
    except Exception as e:
        return {"logs": [], "error": str(e)}


# Mount static assets directory
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main():
    import uvicorn
    uvicorn.run("v1.web.app:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
