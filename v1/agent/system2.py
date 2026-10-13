from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import time
import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from .tools import VERTEX_TOOL_DECLARATIONS, execute_dummy_tool


@dataclass
class AgentResult:
    reply: str
    outcome: str  # "tool_call", "missing_detail", "no_matching_tool", "tools_disabled"
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[Dict[str, Any]] = None
    tools_enabled: bool = True
    latency_ms: float = 0.0
    tool_call_latency_ms: float = 0.0
    raw_response: Optional[str] = None

    @property
    def action_taken(self) -> bool:
        return self.outcome == "tool_call"

    @property
    def clarification_asked(self) -> bool:
        return self.outcome == "missing_detail"

    @property
    def refusal(self) -> bool:
        return self.outcome == "no_matching_tool"


SYSTEM_PROMPT_TEMPLATE = """You are System 2, a fast and helpful Nepali voice command agent.

Current Reference Context:
- Date: {current_date} (YYYY-MM-DD)
- Day of Week: {current_weekday}
- Timezone: Asia/Kathmandu (UTC+5:45)

Rules for interpretation:
1. Dates and times MUST be resolved relative to the reference date provided above:
   - "आज" = {current_date}
   - "भोलि" = {tomorrow_date}
   - "पर्सि" = {day_after_tomorrow_date}
   - Time format must be 24-hour HH:MM (e.g., "बिहान १० बजे" -> 10:00, "दिउँसो २ बजे" -> 14:00, "साँझ ५ बजे" -> 17:00, "साँझ ६ बजे" -> 18:00).
   - If the user corrects themselves (e.g. "भोलि होइन पर्सि", "बिहान होइन दिउँसो", "छ बजे अँ पाँच बजे"), strictly honor the corrected information.

2. Available tools:
   - send_email: requires "to", "subject", "body".
   - create_calendar_event: requires "title", "date", "start_time". "attendees" is optional; NEVER ask for attendees if they are not mentioned. If no specific meeting topic is given other than "बैठक" or "छलफल", use "बैठक" as the title.
   - set_reminder: requires "text", "date", "time". If no specific task is given other than "सम्झाऊ", use "सम्झाउने" or the general topic as text.

3. Missing details rule:
   - If an essential argument is missing (e.g., no recipient for email, no email message/subject, no time or date for an event/reminder), DO NOT call any tool and DO NOT fabricate or guess information.
   - Ask exactly ONE short, natural question in Nepali to clarify the missing detail.

4. No matching tool rule:
   - If the user asks for an action that does not match any of the available tools (e.g., "चिया बनाइदेऊ", "गीत बजाऊ", "ढोका बन्द गर"), DO NOT invent a tool and DO NOT call any function.
   - Reply politely in Nepali stating that you cannot perform this task (e.g., "म यो काम गर्न सक्दिनँ।").

5. Language:
   - All questions, replies, and confirmations to the user must be in concise, natural Nepali.
{tools_mode_instruction}"""


class System2Agent:
    """
    System 2 Agent using Gemini with Vertex AI function calling.
    Handles single-turn and tool execution multi-turn responses.
    """

    def __init__(
        self,
        project_id: str,
        region: str,
        key_file: str | Path,
        model_name: str = "gemini-2.5-flash",
        log_path: Optional[Path] = None,
        timeout_seconds: int = 30,
    ):
        self.project_id = project_id
        self.region = region
        self.model_name = model_name
        self.log_path = log_path
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

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        headers = self._get_auth_header()
        for attempt in range(5):
            try:
                response = self.session.post(
                    self.endpoint_url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 429 and attempt < 4:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                break
            except (requests.exceptions.RequestException, TimeoutError):
                if attempt == 4:
                    raise
                time.sleep(1.0 * (attempt + 1))

        if response.status_code != 200:
            raise RuntimeError(
                f"Vertex AI Agent call failed with status {response.status_code}: {response.text}"
            )
        return response.json()

    def process(
        self,
        text: str,
        tools_enabled: bool = True,
        reference_datetime: Optional[datetime] = None,
    ) -> AgentResult:
        start_time = time.perf_counter()
        ref_dt = reference_datetime or datetime.now()
        cur_date_str = ref_dt.strftime("%Y-%m-%d")
        cur_weekday = ref_dt.strftime("%A")
        tomorrow_str = (ref_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        day_after_str = (ref_dt + timedelta(days=2)).strftime("%Y-%m-%d")

        if tools_enabled:
            tools_mode_instruction = (
                "6. Tools are ENABLED. When all required parameters are provided, execute the matching tool."
            )
        else:
            tools_mode_instruction = (
                "6. Tools are DISABLED. Do NOT call any function or tool. "
                "Write a short, natural Nepali sentence explaining what action you would have performed."
            )

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            current_date=cur_date_str,
            current_weekday=cur_weekday,
            tomorrow_date=tomorrow_str,
            day_after_tomorrow_date=day_after_str,
            tools_mode_instruction=tools_mode_instruction,
        )

        payload: Dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {
                "temperature": 0.0,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        if tools_enabled:
            payload["tools"] = [{"functionDeclarations": VERTEX_TOOL_DECLARATIONS}]

        data = self._post(payload)
        candidates = data.get("candidates", [])
        if not candidates:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return AgentResult(
                reply="कुनै प्रतिक्रिया प्राप्त हुन सकेन।",
                tools_enabled=tools_enabled,
                latency_ms=round(latency_ms, 2),
            )

        first_part = candidates[0].get("content", {}).get("parts", [{}])[0]

        # Case 1: Model chose a tool call
        if "functionCall" in first_part and tools_enabled:
            fn_call = first_part["functionCall"]
            fn_name = fn_call.get("name", "")
            fn_args = fn_call.get("args", {})

            # Execute dummy tool
            t_tool_0 = time.perf_counter()
            tool_result = execute_dummy_tool(fn_name, fn_args, log_path=self.log_path)
            tool_call_latency_ms = (time.perf_counter() - t_tool_0) * 1000.0

            # Send functionResponse back to Gemini to get a natural Nepali reply
            followup_contents = [
                {"role": "user", "parts": [{"text": text}]},
                {"role": "model", "parts": [first_part]},
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": fn_name,
                                "response": {"content": tool_result},
                            }
                        }
                    ],
                },
            ]
            followup_payload = dict(payload)
            followup_payload["contents"] = followup_contents
            followup_data = self._post(followup_payload)

            reply_text = (
                followup_data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )
            if not reply_text:
                reply_text = f"{fn_name} कार्य सम्पन्न भयो।"

            latency_ms = (time.perf_counter() - start_time) * 1000.0
            return AgentResult(
                reply=reply_text,
                outcome="tool_call",
                tool_name=fn_name,
                tool_args=fn_args,
                tool_result=tool_result,
                tools_enabled=True,
                latency_ms=round(latency_ms, 2),
                tool_call_latency_ms=round(tool_call_latency_ms, 2),
                raw_response=json.dumps(fn_call, ensure_ascii=False),
            )

        # Case 2: Direct text response (tools disabled, clarification needed, or refusal)
        reply_text = first_part.get("text", "").strip()
        if not tools_enabled:
            outcome = "tools_disabled"
        else:
            is_refusal = (
                "सक्दिन" in reply_text
                or "गर्न मिल्दैन" in reply_text
                or "उपलब्ध छैन" in reply_text
                or "सहायता गर्न सक्दिन" in reply_text
            )
            if is_refusal:
                outcome = "no_matching_tool"
            else:
                outcome = "missing_detail"

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        return AgentResult(
            reply=reply_text,
            outcome=outcome,
            tool_name=None,
            tool_args=None,
            tool_result=None,
            tools_enabled=tools_enabled,
            latency_ms=round(latency_ms, 2),
            raw_response=reply_text,
        )
