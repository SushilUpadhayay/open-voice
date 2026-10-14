import asyncio
from pathlib import Path
import time
from typing import Dict, Optional, Tuple
import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from .config import CleanupConfig


class GeminiAsiaMumbaiClient:
    """
    High-performance client for Gemini 2.5 Flash running in Vertex AI Asia Mumbai (asia-south1).
    Optimized for low-latency streaming dictation cleanup.
    """

    def __init__(self, config: Optional[CleanupConfig] = None):
        self.config = config or CleanupConfig()
        self.session = requests.Session()
        self.credentials: Optional[service_account.Credentials] = None
        self.endpoint_url: str = ""

        self._setup_connection()

    def _setup_connection(self):
        # 1. Check if direct Gemini API Key is provided
        if self.config.api_key:
            self.endpoint_url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.config.model_name}:generateContent?key={self.config.api_key}"
            )
            return

        # 2. Vertex AI with service account credentials in asia-south1 (Mumbai)
        key_path = Path(self.config.key_file).resolve()
        if key_path.exists():
            self.credentials = service_account.Credentials.from_service_account_file(
                str(key_path),
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            self.endpoint_url = (
                f"https://{self.config.region}-aiplatform.googleapis.com/v1/projects/"
                f"{self.config.project_id}/locations/{self.config.region}/publishers/google/models/"
                f"{self.config.model_name}:generateContent"
            )

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.credentials:
            if not self.credentials.valid or self.credentials.expired:
                self.credentials.refresh(Request())
            headers["Authorization"] = f"Bearer {self.credentials.token}"
        return headers

    def generate(self, system_instruction: str, user_prompt: str) -> Tuple[str, float, float]:
        """
        Synchronous call to Gemini 2.5 Flash.
        Returns:
            (generated_text: str, latency_ms: float, tps: float)
        """
        start = time.perf_counter()
        if not self.endpoint_url:
            return user_prompt, 0.0, 0.0

        gen_config = {
            "temperature": self.config.temperature,
            "maxOutputTokens": self.config.max_output_tokens,
        }
        if self.config.thinking_budget is not None:
            gen_config["thinkingConfig"] = {
                "thinkingBudget": self.config.thinking_budget
            }

        payload = {
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": gen_config,
        }

        try:
            response = self.session.post(
                self.endpoint_url,
                headers=self._get_headers(),
                json=payload,
                timeout=self.config.timeout_seconds,
            )
            latency_ms = (time.perf_counter() - start) * 1000.0

            if response.status_code != 200:
                return user_prompt, latency_ms, 0.0

            data = response.json()
            candidates = data.get("candidates", [])
            output_tokens = data.get("usageMetadata", {}).get("candidatesTokenCount", 0)
            tps = (output_tokens / (latency_ms / 1000.0)) if latency_ms > 0 else 0.0

            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "").strip(), latency_ms, round(tps, 1)

            return user_prompt, latency_ms, round(tps, 1)
        except Exception:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return user_prompt, latency_ms, 0.0

    async def generate_async(self, system_instruction: str, user_prompt: str) -> Tuple[str, float, float]:
        """
        Non-blocking async call executed concurrently in a worker thread.
        Fires alongside Nemotron ASR without blocking the event loop.
        """
        return await asyncio.to_thread(self.generate, system_instruction, user_prompt)
