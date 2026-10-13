import json
from pathlib import Path
import time
from typing import Dict, Optional, Tuple
import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account


class GeminiFlashClient:
    """
    High-performance client for Gemini 2.5 Flash.
    Supports:
    1. Vertex AI via Service Account key (`vertex-key.json`)
    2. Google AI Studio via API Key
    Configured with temperature=0.0 and low token limit for sub-300ms latency.
    """

    def __init__(
        self,
        project_id: str = "",
        region: str = "asia-south1",
        key_file: str | Path | None = None,
        api_key: str = "",
        model_name: str = "gemini-2.5-flash",
        timeout_seconds: int = 15,
    ):
        self.project_id = project_id
        self.region = region
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key
        self.session = requests.Session()

        self.credentials: Optional[service_account.Credentials] = None
        self.endpoint_url: str = ""

        # Setup auth
        if self.api_key:
            # Mode A: Google AI Studio
            self.endpoint_url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.model_name}:generateContent?key={self.api_key}"
            )
        elif key_file:
            # Mode B: Vertex AI
            key_path = Path(key_file).resolve()
            if key_path.exists():
                self.credentials = service_account.Credentials.from_service_account_file(
                    str(key_path),
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
                self.endpoint_url = (
                    f"https://{self.region}-aiplatform.googleapis.com/v1/projects/"
                    f"{self.project_id}/locations/{self.region}/publishers/google/models/"
                    f"{self.model_name}:generateContent"
                )

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.credentials:
            if not self.credentials.valid or self.credentials.expired:
                self.credentials.refresh(Request())
            headers["Authorization"] = f"Bearer {self.credentials.token}"
        return headers

    def generate(self, system_instruction: str, user_prompt: str) -> Tuple[str, float]:
        """
        Sends generation request to Gemini Flash.
        Returns:
            (generated_text: str, latency_ms: float)
        """
        start = time.perf_counter()
        if not self.endpoint_url:
            # Mock / fallback when no credentials are provided
            return user_prompt, 0.0

        payload = {
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 256,
            },
        }

        try:
            response = self.session.post(
                self.endpoint_url,
                headers=self._get_headers(),
                json=payload,
                timeout=self.timeout_seconds,
            )
            latency_ms = (time.perf_counter() - start) * 1000.0

            if response.status_code != 200:
                # On non-200, return original prompt without breaking pipeline
                return user_prompt, latency_ms

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return user_prompt, latency_ms

            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                return user_prompt, latency_ms

            text = parts[0].get("text", "").strip()
            return text, latency_ms
        except Exception:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return user_prompt, latency_ms
