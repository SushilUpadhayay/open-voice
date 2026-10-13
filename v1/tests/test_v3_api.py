from pathlib import Path
import json
import time
import requests

BASE_URL = "http://127.0.0.1:8000"
TESTS_DIR = Path(__file__).resolve().parent
AUDIO_FILE = TESTS_DIR / "audio" / "namaste.wav"


def test_api():
    print(f"Testing V3 API on {BASE_URL}...")

    # 1. Test GET /
    r_index = requests.get(f"{BASE_URL}/")
    assert r_index.status_code == 200, f"GET / failed: {r_index.status_code}"
    assert "Open Voice Layer" in r_index.text, "Index HTML missing title"
    print("[PASS] GET / served index.html successfully.")

    # 2. Test POST /api/process (Text Command with Tools)
    payload = {
        "text": "भोलि बिहान दश बजे बैठक राख।",
        "actions": True,
        "cleanup": True,
        "tools": True,
    }
    r_proc = requests.post(
        f"{BASE_URL}/api/process",
        headers={"Content-Type": "application/json"},
        json=payload,
    )
    assert r_proc.status_code == 200, f"POST /api/process text failed: {r_proc.text}"
    data = r_proc.json()
    assert data["branch"] == "command", f"Expected command branch, got {data['branch']}"
    assert data["card"]["type"] in ["calendar", "tools_disabled", "question"], f"Unexpected card: {data['card']}"
    assert "timings" in data, "Missing timings in response"
    print(f"[PASS] POST /api/process (text): Branch={data['branch']}, Total={data['timings']['total_ms']}ms, Card={data['card']['type']}")

    # 3. Test POST /api/process (Audio Dictation)
    if AUDIO_FILE.exists():
        with open(AUDIO_FILE, "rb") as f:
            files = {"audio": ("namaste.wav", f, "audio/wav")}
            data_form = {
                "actions": "false",
                "cleanup": "true",
                "tools": "false",
            }
            r_audio = requests.post(f"{BASE_URL}/api/process", files=files, data=data_form)
            assert r_audio.status_code == 200, f"POST /api/process audio failed: {r_audio.text}"
            audio_res = r_audio.json()
            assert audio_res["branch"] == "dictation", f"Expected dictation branch, got {audio_res['branch']}"
            print(f"[PASS] POST /api/process (audio): Raw='{audio_res['raw_text']}', Clean='{audio_res['cleaned_text']}', ASR={audio_res['timings']['asr_ms']}ms")

    # 4. Test POST /api/tts
    r_tts = requests.post(f"{BASE_URL}/api/tts", json={"text": "नमस्ते"})
    assert r_tts.status_code == 200, f"POST /api/tts failed: {r_tts.text}"
    assert len(r_tts.content) > 1000, "TTS audio content empty"
    print(f"[PASS] POST /api/tts synthesized speech successfully ({len(r_tts.content)} bytes).")

    # 5. Test GET /api/tools/log
    r_log = requests.get(f"{BASE_URL}/api/tools/log")
    assert r_log.status_code == 200, f"GET /api/tools/log failed: {r_log.text}"
    logs = r_log.json().get("logs", [])
    print(f"[PASS] GET /api/tools/log returned {len(logs)} log entries.")

    print("\nALL V3 API ENDPOINTS VALIDATED SUCCESSFULLY!")


if __name__ == "__main__":
    test_api()
