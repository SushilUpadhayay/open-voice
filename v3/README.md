# Open Voice v3 — Real-Time Streaming Dictation & Wispr Flow Polish

A next-generation streaming dictation platform combining local **Nemotron 3.5 Vulkan GPU ASR** with **Wispr Flow-style sentence-level cleanup** powered by **Gemini 2.5 Flash in Asia Mumbai (`asia-south1`)**.

---

## Architecture Overview

```text
[Microphone (Web Audio API)]
          │ (16kHz PCM chunks via WebSocket)
          ▼
    [v3/backend/ws_handler]
          │
          ├─► [v3/backend/vad] (Micro-pause & speech activity detection)
          ▼
   [v3/asr (Nemotron 3.5)] ──(Vulkan0 GPU)──► [Live In-Flight Raw Stream (UI)]
          │ (Raw text tokens)
          ▼
 [v3/cleanup (Wispr Flow Engine)]
          │ (Sentence boundary detected on full stop or 350ms pause)
          ▼
 [Concurrent Background Task] (Non-blocking asyncio.create_task)
          │
          ▼
 [Gemini 2.5 Flash (Asia Mumbai Vertex AI)]
   • Strips filler words ("um", "uh", "you know", "like")
   • Resolves self-corrections / backtracking ("at 2, no wait 3 PM" → "at 3 PM")
   • Formats numbers & currencies ("twenty five dollars" → "$25")
   • Adds terminal punctuation & capitalization
          │
          ▼
 [Polished Document Output (UI)]
```

---

## Directory Structure

```text
v3/
├── asr/                       # Standalone Nemotron 3.5 ASR & VAD pipeline
│   ├── client.py              # Python client (file & in-memory PCM decoding)
│   ├── run_asr.py             # CLI test runner
│   ├── Cargo.toml             # Rust dependencies (transcribe-cpp, vad-rs, cpal)
│   ├── resources/             # Silero VAD ONNX models
│   └── src/                   # Rust engine supervisor, catalog, audio toolkit
├── cleanup/                   # Wispr Flow-style sentence-level cleanup engine
│   ├── config.py              # Vertex AI Asia Mumbai config & thresholds
│   ├── gemini_client.py       # Async Gemini 2.5 Flash client (asia-south1)
│   ├── prompts.py             # Wispr Flow cleanup instructions
│   ├── segmenter.py           # Sentence boundary detector (punctuation + VAD pauses)
│   ├── engine.py              # Concurrent orchestrator (fires LLM alongside Nemotron)
│   └── test_cleanup.py        # End-to-end simulation test
├── backend/                   # Runtime server
│   ├── app.py                 # FastAPI application (REST APIs + Static mount)
│   ├── ws_handler.py          # WebSocket handler (/ws/dictate)
│   └── vad.py                 # 16kHz Energy VAD for pause detection
└── frontend/                  # Web interface
    ├── index.html             # Glassmorphism dual-buffer streaming UI
    └── static/
        ├── app.js             # Web Audio API 16kHz streamer & visualizer
        └── style.css          # Dark-mode glass styling & animations
```

---

## Running the v3 Service

Launch the server using `.venv` and Uvicorn:

```bash
.venv\Scripts\python.exe -m uvicorn v3.backend.app:app --port 8002 --reload
```

Then open your browser at **`http://127.0.0.1:8002/`**.
