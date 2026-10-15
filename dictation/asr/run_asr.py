import os
import json
import subprocess
import sys
from pathlib import Path

from .client import DEFAULT_MODEL

HANDY_EXE = Path(os.environ.get("LOCALAPPDATA", "")) / "Handy" / "handy.exe"
<<<<<<< HEAD
DEFAULT_MODEL = os.environ.get(
    "DICTATION_ASR_MODEL",
    "handy-computer/parakeet-unified-en-0.6b-gguf/parakeet-unified-en-0.6b-Q8_0.gguf",
)

def transcribe(wav_path: str, model_id: str = DEFAULT_MODEL) -> dict:
    """
    Transcribes a 16 kHz mono 16-bit WAV file using the Parakeet Unified EN engine.
=======

def transcribe(wav_path: str, model_id: str = DEFAULT_MODEL) -> dict:
    """
    Transcribes a 16 kHz mono 16-bit WAV file using the configured Handy model.
>>>>>>> 2dc7fb33e284c705fab3378cfe353f1ab4ccac70
    """
    wav_file = Path(wav_path).resolve()
    if not wav_file.exists():
        raise FileNotFoundError(f"Audio file not found: {wav_file}")
    if not HANDY_EXE.exists():
        raise FileNotFoundError(f"Engine executable not found at: {HANDY_EXE}")

    cmd = [
        str(HANDY_EXE),
        "--transcribe-file", str(wav_file),
        "--model", model_id,
        "--json"
    ]

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8"
    )

    stdout = (result.stdout or "").strip()
    if result.returncode != 0:
        raise RuntimeError(f"Transcription failed (code {result.returncode}): {result.stderr}")

    try:
        data = json.loads(stdout)
        return data
    except json.JSONDecodeError:
        return {"text": stdout, "raw": stdout}

if __name__ == "__main__":
    target_wav = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parents[2] / "hi3.wav")
    print(f"Transcribing: {target_wav}")
    res = transcribe(target_wav)
    print(f"Text: {res.get('text')}")
    print(f"Inference latency: {res.get('best_ms')}ms (RTF: {res.get('rtf'):.2f}x)")
    print(f"Backend: {res.get('bound_backend')}")
