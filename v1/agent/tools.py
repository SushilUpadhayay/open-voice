from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import uuid

DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent / "results" / "tool_calls.log"


def _log_tool_call(tool_name: str, args: Dict[str, Any], log_path: Optional[Path] = None) -> None:
    target_log = log_path or DEFAULT_LOG_PATH
    target_log.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": tool_name,
        "arguments": args,
    }
    with open(target_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def send_email(to: str, subject: str, body: str, log_path: Optional[Path] = None) -> Dict[str, Any]:
    args = {"to": to, "subject": subject, "body": body}
    _log_tool_call("send_email", args, log_path)
    return {
        "status": "success",
        "message_id": f"msg_{uuid.uuid4().hex[:8]}",
        "recipient": to,
        "subject": subject,
    }


def create_calendar_event(
    title: str,
    date: str,
    start_time: str,
    attendees: Optional[List[str]] = None,
    log_path: Optional[Path] = None,
) -> Dict[str, Any]:
    args = {
        "title": title,
        "date": date,
        "start_time": start_time,
        "attendees": attendees or [],
    }
    _log_tool_call("create_calendar_event", args, log_path)
    return {
        "status": "success",
        "event_id": f"evt_{uuid.uuid4().hex[:8]}",
        "title": title,
        "date": date,
        "start_time": start_time,
    }


def set_reminder(text: str, date: str, time: str, log_path: Optional[Path] = None) -> Dict[str, Any]:
    args = {"text": text, "date": date, "time": time}
    _log_tool_call("set_reminder", args, log_path)
    return {
        "status": "success",
        "reminder_id": f"rem_{uuid.uuid4().hex[:8]}",
        "text": text,
        "date": date,
        "time": time,
    }


TOOL_REGISTRY = {
    "send_email": send_email,
    "create_calendar_event": create_calendar_event,
    "set_reminder": set_reminder,
}


def execute_dummy_tool(tool_name: str, args: Dict[str, Any], log_path: Optional[Path] = None) -> Dict[str, Any]:
    if tool_name not in TOOL_REGISTRY:
        raise ValueError(f"Unknown tool '{tool_name}'. Available: {list(TOOL_REGISTRY.keys())}")
    fn = TOOL_REGISTRY[tool_name]
    return fn(**args, log_path=log_path)


VERTEX_TOOL_DECLARATIONS = [
    {
        "name": "send_email",
        "description": "Send an email to a recipient with a subject and message body.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "to": {
                    "type": "STRING",
                    "description": "Recipient name or email address.",
                },
                "subject": {
                    "type": "STRING",
                    "description": "Subject of the email.",
                },
                "body": {
                    "type": "STRING",
                    "description": "Content or message body of the email.",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "create_calendar_event",
        "description": "Schedule a meeting or calendar event with a title, date (YYYY-MM-DD), start time (HH:MM), and optional attendees.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Title or summary of the meeting or event.",
                },
                "date": {
                    "type": "STRING",
                    "description": "Date in YYYY-MM-DD format.",
                },
                "start_time": {
                    "type": "STRING",
                    "description": "Start time in HH:MM format (24-hour time or e.g. 10:00).",
                },
                "attendees": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Optional list of participants or attendee names.",
                },
            },
            "required": ["title", "date", "start_time"],
        },
    },
    {
        "name": "set_reminder",
        "description": "Set a reminder with note text, date (YYYY-MM-DD), and time (HH:MM).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "text": {
                    "type": "STRING",
                    "description": "What to be reminded about.",
                },
                "date": {
                    "type": "STRING",
                    "description": "Date in YYYY-MM-DD format.",
                },
                "time": {
                    "type": "STRING",
                    "description": "Time in HH:MM format.",
                },
            },
            "required": ["text", "date", "time"],
        },
    },
]
