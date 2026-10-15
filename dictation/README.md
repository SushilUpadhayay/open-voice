# Open Voice Dictation — Real-Time Streaming Dictation & Wispr Flow Polish

A next-generation streaming dictation platform combining local **Parakeet Unified EN 0.6B Vulkan GPU ASR** with **Wispr Flow-style sentence-level cleanup** powered by **Gemini 2.5 Flash in Asia Mumbai (`asia-south1`)**.

---

## Architecture Overview

```text
[Microphone (Web Audio API)]
          │ (16kHz PCM chunks via WebSocket)
          ▼
    [dictation/backend/ws_handler]
          │
          ├─► [dictation/backend/vad] (Micro-pause & speech activity detection)
          ▼
   [dictation/asr (Parakeet Unified EN)] ──(Vulkan0 GPU)──► [Live In-Flight Raw Stream (UI)]
          │ (Raw text tokens)
          ▼
 [dictation/cleanup (Wispr Flow Engine)]
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
dictation/
├── asr/                       # Local Handy Parakeet ASR & VAD pipeline
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
│   ├── engine.py              # Concurrent orchestrator (fires LLM alongside ASR)
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

## Running the Dictation Service

The default English Parakeet model must be downloaded in Handy before use. The API status endpoint reports whether both Handy and the selected model are available.

Launch the server using `uv` or `.venv`:

```bash
uv run uvicorn dictation.backend.app:app --port 8002 --reload
```

or with Python directly:

```bash
.venv\Scripts\python.exe -m uvicorn dictation.backend.app:app --port 8002 --reload
```

Then open your browser at **`http://127.0.0.1:8002/`**.
