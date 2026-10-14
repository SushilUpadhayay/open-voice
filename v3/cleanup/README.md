# Dictation Cleanup Module (Wispr Flow Architecture)

This module implements a streaming, sentence-level dictation cleanup system powered by **Gemini 2.5 Flash in Asia Mumbai (`asia-south1`)**.

## Wispr Flow Principles Implemented

1. **Filler Word Removal:** Strips verbal tics ("um", "uh", "you know", "like", "basically", "er", "उम्", "अँ", "हजुर", "मतलब").
2. **Backtracking & Self-Corrections:** Automatically detects mid-sentence corrections and keeps only the intended words (e.g. *"at two, no wait three PM"* → *"at 3 PM."*).
3. **Number & Symbol Normalization:** Spoken numbers, percentages, and currencies are formatted cleanly (e.g. *"twenty five dollars"* → *"$25"*, *"ten percent"* → *"10%"*).
4. **Sentence-Level Boundary Detection:** Segments raw streams when terminal punctuation (`.`, `?`, `!`, `।`) or acoustic pauses (silence ≥ 350ms) are detected.
5. **Parallel LLM Execution:** Dispatches background cleanup tasks immediately upon sentence completion, running alongside Nemotron ASR so perceived latency is near zero.
6. **Dual Buffer Model:** Keeps both raw Nemotron verbatim text and polished text, supporting instant live preview with an "Undo" safety net.

## Architecture

```text
[Nemotron ASR Stream] ──(raw tokens)──► [SentenceSegmenter]
                                               │
                                               ├─ (terminal punctuation / pause)
                                               ▼
                                      [Concurrent Dispatch]
                                     (asyncio.create_task)
                                               │
                     ┌─────────────────────────┴────────────────────────┐
                     ▼                                                  ▼
          [Gemini 2.5 Flash (Mumbai)]                        [Nemotron ASR Stream]
              (asia-south1 Vertex)                         (Continues transcribing
             Wispr Flow Prompting                           next sentence in parallel)
                     │
                     ▼
          [Polished Sentence Buffer]
```

## Running the Test

```bash
.venv\Scripts\python.exe d:\open-voice\v3\cleanup\test_cleanup.py
```
