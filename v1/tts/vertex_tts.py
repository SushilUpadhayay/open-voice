from pathlib import Path
from typing import Optional, Tuple
import base64
import time
import requests
from google.oauth2 import service_account
from google.auth.transport.requests import Request


class VertexTTS:
    """
    Google Cloud Text-to-Speech client for synthesizing spoken replies.
    Supports primary 'ne-NP' and graceful fallback to 'hi-IN' (hi-IN-Neural2-A).
    """

    def __init__(
        self,
        key_file: Path | str,
        primary_lang: str = "ne-NP",
        fallback_lang: str = "hi-IN",
        fallback_voice: str = "hi-IN-Neural2-A",
        timeout_seconds: int = 15,
    ):
        self.key_file = Path(key_file).resolve()
        if not self.key_file.exists():
            raise FileNotFoundError(f"Service account key not found: {self.key_file}")

        self.primary_lang = primary_lang
        self.fallback_lang = fallback_lang
        self.fallback_voice = fallback_voice
        self.timeout_seconds = timeout_seconds

        self.credentials = service_account.Credentials.from_service_account_file(
            str(self.key_file),
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        self.endpoint_url = "https://texttospeech.googleapis.com/v1/text:synthesize"
        self.session = requests.Session()

    def _get_auth_header(self) -> dict:
        if not self.credentials.valid:
            self.credentials.refresh(Request())
        return {
            "Authorization": f"Bearer {self.credentials.token}",
            "Content-Type": "application/json",
        }

    def synthesize(self, text: str) -> Tuple[bytes, float]:
        """
        Synthesizes Nepali text to MP3 audio bytes.
        Returns:
            Tuple of (audio_bytes, latency_ms)
        """
        clean_text = text.strip()
        if not clean_text:
            return b"", 0.0

        headers = self._get_auth_header()
        start_time = time.perf_counter()

        # Primary attempt (Nepali)
        payload = {
            "input": {"text": clean_text},
            "voice": {"languageCode": self.primary_lang},
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.0},
        }

        try:
            resp = self.session.post(
                self.endpoint_url,
                headers=headers,
                json=payload,
                timeout=self.timeout_seconds,
            )
            if resp.status_code == 200:
                audio_bytes = base64.b64decode(resp.json()["audioContent"])
                latency_ms = (time.perf_counter() - start_time) * 1000.0
                return audio_bytes, round(latency_ms, 2)
        except Exception:
            pass

        # Fallback attempt (Hindi voice capable of reading Devanagari)
        fallback_payload = {
            "input": {"text": clean_text},
            "voice": {
                "languageCode": self.fallback_lang,
                "name": self.fallback_voice,
            },
            "audioConfig": {"audioEncoding": "MP3", "speakingRate": 1.0},
        }

        resp = self.session.post(
            self.endpoint_url,
            headers=headers,
            json=fallback_payload,
            timeout=self.timeout_seconds,
        )
        latency_ms = (time.perf_counter() - start_time) * 1000.0

        if resp.status_code != 200:
            raise RuntimeError(
                f"TTS synthesis failed with status {resp.status_code}: {resp.text}"
            )

        audio_bytes = base64.b64decode(resp.json()["audioContent"])
        return audio_bytes, round(latency_ms, 2)
