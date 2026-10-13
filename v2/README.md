# Open Voice v2 — Real-Time Streaming Dictation & Live Polish

An independent, production-grade streaming dictation system with **adaptive sliding-window live cleanup** using **Gemini Flash**.

---

## Architecture Overview

```
[Microphone] 
     │ (16kHz PCM chunks via WebSocket)
     ▼
[IndicConformer ASR / VAD]
     │ (Instant raw tokens)
     ├─────────────────────────────────► [Live In-Flight Tail UI]
     ▼
[WindowManager (4–6 words or 300ms pause)]
     │
     ▼
[Heuristic Filter (0ms)]
     ├── Clean? ───────────────────────► [0ms Bypass directly to output]
     └── Has Fillers/Stutters?
             │
             ▼
     [Gemini 2.5 Flash In-Flight Worker]
     (Anti-completion prompt + context carry-forward)
             │
             ▼
     [Committed Polished Buffer]
             │
     [User pauses / stops]
             ▼
     [Final Pass Reconciliation]
     (Closing punctuation & capitalization)
```

---

## Directory Structure

```text
v2/
├── config/
│   ├── settings.yaml          # ASR endpoint, thresholds, Gemini config
│   └── __init__.py
├── asr/
│   ├── client.py              # IndicConformer client (WAV / in-memory buffer)
│   ├── vad.py                 # Energy-based VAD for micro-pause detection
│   └── __init__.py
├── engine/
│   ├── heuristics.py          # 0ms rule filter for speech fillers & stutters
│   ├── window_manager.py      # Sliding window buffer (word threshold & context)
│   ├── session.py             # Active session state & telemetry
│   └── __init__.py
├── cleaner/
│   ├── gemini.py              # Gemini 2.5 Flash client (Vertex AI & AI Studio)
│   ├── prompts.py             # Anti-completion in-flight & final reconciliation prompts
│   ├── pipeline.py            # Polishing pipeline coordinator
│   └── __init__.py
├── server/
│   ├── app.py                 # FastAPI application
│   ├── ws_handler.py          # Real-time WebSocket protocol (/ws/dictate)
│   └── __init__.py
└── web/
    ├── index.html             # Dual-buffer streaming web interface
    └── static/
        ├── app.js             # Web Audio API 16kHz streamer & WebSocket client
        └── style.css          # Glassmorphism dark UI with live waveforms
```

---

## Running the Service

Activate your virtual environment and launch uvicorn:

```bash
# Using Python directly:
.myvenv\Scripts\python.exe -m uvicorn v2.server.app:app --port 8001

# Or with live reload:
.myvenv\Scripts\python.exe -m uvicorn v2.server.app:app --port 8001 --reload
```

Then open your browser at **`http://127.0.0.1:8001/`**.
