# V1: The Branch (Nepali Voice AI Routing)

V1 proves that Nepali spoken speech transcribed into Devanagari text can be routed to the correct path (Dictation vs. Command) using a fast Gemini Flash-Lite decider operating concurrently with a Gemini cleanup pass under customer-specific configurations.

## Project Layout

```text
V1/
  config/
    customer_a.yaml      actions: false, cleanup: true (dictation-only)
    customer_b.yaml      actions: true, cleanup: true  (full assistant)
    settings.yaml        Vertex AI credentials, models, ASR endpoint, thresholds
  asr/
    client.py            Indic Conformer client (multipart wav -> raw Nepali text)
  decider/
    interface.py         Decider abstract base class & DecisionResult dataclass
    gemini_decider.py    Gemini Flash-Lite decider on Vertex AI with token logprobs
  cleanup/
    gemini_cleanup.py    Gemini cleanup call removing Nepali fillers & resolving self-corrections
  orchestrator/
    runner.py            Parallel execution, config resolution, and branching logic
  tests/
    sentences.csv        30 labeled Nepali sentences (clean dictation, messy dictation, commands, ambiguous)
    test_runner.py       Benchmark suite runner (accuracy, timings, order sensitivity)
    audio/
      namaste.wav        Recorded audio clip for smoke testing
  results/               Benchmark reports (JSON and Markdown)
  main.py                CLI entry point
```

## Setup

Activate the virtual environment with the required dependencies:

```bash
source .myvenv/Scripts/activate  # or .myvenv\Scripts\activate on Windows
pip install pyyaml requests google-auth
```

Ensure `vertex-key.json` exists at the project root with Vertex AI permissions on project `tpu-project-235909`.

## Usage

### 1. Single Input Evaluation

**With raw text (Command):**
```bash
python V1/main.py --input "रामलाई रिपोर्टको बारेमा इमेल पठाऊ।" --config customer_b
```

**With raw text under Customer A (Actions OFF -> Forced Dictation):**
```bash
python V1/main.py --input "रामलाई रिपोर्टको बारेमा इमेल पठाऊ।" --config customer_a
```

**With an audio file (Full End-to-End ASR -> Decider -> Cleanup):**
```bash
python V1/main.py --input V1/tests/audio/namaste.wav --config customer_b
```

### 2. Running the 30-Sentence Benchmark

Runs all 30 sentences from `tests/sentences.csv`, checks accuracy per category, collects step timings, and tests option-order stability:

```bash
python V1/main.py --test --config customer_b
```

Benchmark results and markdown summaries will be written directly into `V1/results/`.
