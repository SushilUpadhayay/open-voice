from pathlib import Path
from typing import Dict, Tuple
import time
import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account


CLEANUP_SYSTEM_INSTRUCTION = """You are a text cleanup assistant for Nepali transcribed speech.
Your goal is to turn raw speech transcript into clean, readable Nepali text:
1. Remove filler words, hesitation markers, and false starts (e.g., 'ए...', 'उम्', 'अँ', 'हजुर हजुर', 'त्यो के भन्छन्', 'चाहिँ', 'कि क्या हो').
2. Clean up speech repetitions (e.g., 'त्यो काम त्यो काम' -> 'त्यो काम').
3. Resolve self-corrections (e.g., 'भोलि होइन पर्सि' -> 'पर्सि', 'छ बजे सम्झाऊ अँ पाँच बजे' -> 'पाँच बजे सम्झाऊ').
4. Add or fix appropriate Nepali punctuation (पूर्णविराम '।', अल्पविराम ',').
5. If the input text is already clean and natural, return it EXACTLY unchanged.
6. Do NOT add commentary, explanations, or quotes. Output ONLY the cleaned Nepali text."""


class GeminiCleanup:
    """
    Cleans raw Nepali speech transcript using Gemini on Vertex AI.
    Removes fillers, false starts, and resolves self-corrections.
    """

    def __init__(
        self,
        project_id: str,
        region: str,
        key_file: str | Path,
        model_name: str = "gemini-2.5-flash",
        timeout_seconds: int = 20,
    ):
        self.project_id = project_id
        self.region = region
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

        key_path = Path(key_file).resolve()
        if not key_path.exists():
            raise FileNotFoundError(f"Service account key file not found: {key_path}")

        self.credentials = service_account.Credentials.from_service_account_file(
            str(key_path),
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        self.session = requests.Session()
        self.endpoint_url = (
            f"https://{self.region}-aiplatform.googleapis.com/v1/projects/"
            f"{self.project_id}/locations/{self.region}/publishers/google/models/"
            f"{self.model_name}:generateContent"
        )

    def _get_auth_header(self) -> Dict[str, str]:
        if not self.credentials.valid or self.credentials.expired:
            self.credentials.refresh(Request())
        return {
            "Authorization": f"Bearer {self.credentials.token}",
            "Content-Type": "application/json",
        }

    def clean(self, raw_text: str) -> Tuple[str, float, bool, float, float]:
        """
        Cleans the input Nepali text.

        Returns:
            Tuple of (cleaned_text, latency_ms, changed_flag, auth_ms, network_ms)
        """
        if not raw_text.strip():
            return "", 0.0, False, 0.0, 0.0

        auth_start = time.perf_counter()
        headers = self._get_auth_header()
        auth_ms = (time.perf_counter() - auth_start) * 1000.0

        payload = {
            "systemInstruction": {
                "parts": [{"text": CLEANUP_SYSTEM_INSTRUCTION}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"Raw text: {raw_text}\nClean text:"}],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 200,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

        start_time = time.perf_counter()
        response = None
        network_ms = 0.0
        for attempt in range(2):
            try:
                net_start = time.perf_counter()
                response = self.session.post(
                    self.endpoint_url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                network_ms = (time.perf_counter() - net_start) * 1000.0
                break
            except (requests.exceptions.RequestException, TimeoutError):
                if attempt == 1:
                    raise
                time.sleep(1.0)

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        if response.status_code != 200:
            raise RuntimeError(
                f"Vertex AI cleanup call failed with status {response.status_code}: {response.text}"
            )

        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return raw_text.replace("。", "।"), latency_ms, False, round(auth_ms, 2), round(network_ms, 2)

        cand_text = (
            candidates[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
            .strip()
        )
        cleaned_text = cand_text if cand_text else raw_text
        # Guarantee Devanagari danda (।) instead of Japanese full stop (。)
        cleaned_text = cleaned_text.replace("。", "।")
        changed = cleaned_text.strip() != raw_text.strip()

        return cleaned_text, round(latency_ms, 2), changed, round(auth_ms, 2), round(network_ms, 2)

