from pathlib import Path
from typing import Dict, List, Optional
import math
import time
import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from .interface import Decider, DecisionResult


DEFAULT_OPTIONS = ["dictation", "command", "unclear"]

FEW_SHOT_EXAMPLES = {
    "dictation": [
        "म अहिले गाडी चलाउँदै छु।",
        "परियोजनाको काम समयमै सकिनेछ।",
        "आजको मौसम धेरै चिसो छ।",
    ],
    "command": [
        "ढोका बन्द गर।",
        "यो सन्देश तुरुन्तै फरवार्ड गर।",
        "अलार्म बिहान सात बजेको लगाऊ।",
    ],
    "unclear": [
        "त्यहाँ पुगेपछि थाहा हुन्छ।",
        "सायद अर्को हप्ता।",
        "सडकको अवस्था।",
    ],
}

BASE_PROMPT_TEMPLATE = """You are a fast voice router for Nepali speech.
Decide if the given Nepali text is:
{options_desc}

Guidelines:
- "dictation": Informational statements, reports, conversation, notes, or thoughts the user wants typed out.
- "command": Imperative actions, requests, or instructions directed at an assistant (e.g., send email, schedule meeting, remind me, search).
- "unclear": Incomplete fragments, ambiguous phrases with no clear intent, or text that could equally be either.

Examples:
- "म अहिले गाडी चलाउँदै छु।" -> dictation
- "परियोजनाको काम समयमै सकिनेछ।" -> dictation
- "आजको मौसम धेरै चिसो छ।" -> dictation
- "ढोका बन्द गर।" -> command
- "यो सन्देश तुरुन्तै फरवार्ड गर।" -> command
- "अलार्म बिहान सात बजेको लगाऊ।" -> command
- "त्यहाँ पुगेपछि थाहा हुन्छ।" -> unclear
- "सायद अर्को हप्ता।" -> unclear
- "सडकको अवस्था।" -> unclear

Answer with EXACTLY ONE word from the allowed options ({options_list}). No explanation, no punctuation.

Text: "{text}"
Answer:"""


class GeminiDecider(Decider):
    """
    Decider implementation using Gemini Flash-Lite on Vertex AI.
    Uses temperature 0.0, very short output, and extracts token logprobs for confidence.
    """

    def __init__(
        self,
        project_id: str,
        region: str,
        key_file: str | Path,
        model_name: str = "gemini-2.5-flash",
        timeout_seconds: int = 30,
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

    def decide(
        self,
        text: str,
        options: Optional[List[str]] = None,
        reverse_order: bool = False,
    ) -> DecisionResult:
        opts = list(options or DEFAULT_OPTIONS)
        if reverse_order:
            opts = list(reversed(opts))

        options_desc = "\n".join([f'- "{o}"' for o in opts])
        options_list = ", ".join(opts)

        prompt = BASE_PROMPT_TEMPLATE.format(
            options_desc=options_desc,
            options_list=options_list,
            text=text,
        )

        auth_start = time.perf_counter()
        headers = self._get_auth_header()
        auth_ms = (time.perf_counter() - auth_start) * 1000.0

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 6,
                "responseLogprobs": True,
                "logprobs": 5,
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
                f"Vertex AI call failed with status {response.status_code}: {response.text}"
            )

        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return DecisionResult(
                option="unclear",
                confidence=0.0,
                latency_ms=latency_ms,
                raw_response=response.text,
            )

        cand = candidates[0]
        raw_text = (
            cand.get("content", {}).get("parts", [{}])[0].get("text", "").strip().lower()
        )

        # Match winning option
        selected_option = "unclear"
        for opt in opts:
            if opt in raw_text:
                selected_option = opt
                break

        # Extract logprobs & probabilities
        option_probs: Dict[str, float] = {}
        confidence = 0.0
        logprobs_result = cand.get("logprobsResult", {})
        top_candidates_list = logprobs_result.get("topCandidates", [])

        if top_candidates_list:
            first_token_cands = top_candidates_list[0].get("candidates", [])
            for c in first_token_cands:
                token_clean = c.get("token", "").strip().lower()
                log_prob = c.get("logProbability", -99.0)
                prob = math.exp(log_prob) if log_prob > -50 else 0.0
                for opt in opts:
                    if opt in token_clean or token_clean in opt:
                        option_probs[opt] = max(option_probs.get(opt, 0.0), prob)

            if selected_option in option_probs:
                confidence = option_probs[selected_option]
            elif first_token_cands:
                # If the chosen word matched, estimate confidence from the first candidate
                top_prob = math.exp(first_token_cands[0].get("logProbability", 0.0))
                confidence = min(1.0, max(0.0, top_prob))
            else:
                confidence = 0.5
        else:
            # Fallback when logprobs are empty
            confidence = 0.9 if selected_option != "unclear" else 0.5

        return DecisionResult(
            option=selected_option,
            confidence=round(confidence, 4),
            option_probabilities=option_probs,
            latency_ms=round(latency_ms, 2),
            auth_ms=round(auth_ms, 2),
            network_ms=round(network_ms, 2),
            raw_response=raw_text,
        )

