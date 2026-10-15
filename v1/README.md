# V1: The Branch (English Dictation Integration)

V1 Iteration 1 updates the Customer A dictation path to use local Nemotron 3.5 ASR and the English Wispr Flow-style cleanup used by `dictation/`. The existing command-routing and assistant paths are separate follow-up work.

## Project Layout

```text
V1/
  config/
    customer_a.yaml      actions: false, cleanup: true (dictation-only)
    customer_b.yaml      actions: true, cleanup: true  (full assistant)
    settings.yaml        Vertex AI credentials, Nemotron model/audio settings
  asr/
    client.py            Adapter to local Nemotron ASR (WAV or in-memory PCM)
  decider/
    interface.py         Decider abstract base class & DecisionResult dataclass
    gemini_decider.py    Gemini Flash-Lite decider on Vertex AI with token logprobs
  cleanup/
    gemini_cleanup.py    Adapter to English dictation cleanup in dictation/
  orchestrator/
    runner.py            Parallel execution, config resolution, and branching logic
  tests/
    sentences.csv        Existing labeled routing test sentences
    test_runner.py       Benchmark suite runner (accuracy, timings, order sensitivity)
    audio/
      namaste.wav        Legacy non-English sample; Iteration 1 smoke test uses root hi3.wav
  results/               Benchmark reports (JSON and Markdown)
  main.py                CLI entry point
```

## Setup

Activate the virtual environment with the required dependencies:

```bash
source .myvenv/Scripts/activate  # or .myvenv\Scripts\activate on Windows
pip install pyyaml requests google-auth
```

Ensure `vertex-key.json` exists at the project root with Vertex AI permissions on project `tpu-project-235909`. Install the Handy desktop app and download the Nemotron 3.5 model in Handy's model settings before transcribing audio.

## Usage

### 1. Single Input Evaluation

**Customer A dictation-only path (English text):**
```bash
python v1/main.py --input "hello um so basically let us meet at two no wait three pm" --config customer_a
```

**Customer A dictation-only path (English audio):**
```bash
python v1/main.py --input hi3.wav --config customer_a
```

### Iteration 1 dictation smoke tests

Use Customer A (`actions: false`) to verify that English text is cleaned without invoking the Decider or System 2 Agent:

```powershell
python v1\main.py --input "hello um so basically let us meet at two no wait three pm" --config customer_a
python v1\main.py --input hi3.wav --config customer_a
```

Audio is transcribed locally using Nemotron 3.5 through Handy; cleanup uses Gemini 2.5 Flash in Vertex AI.

### 2. Running the 30-Sentence Benchmark

Runs all 30 sentences from `tests/sentences.csv`, checks accuracy per category, collects step timings, and tests option-order stability:

```bash
python V1/main.py --test --config customer_b
```

Benchmark results and markdown summaries will be written directly into `V1/results/`.
