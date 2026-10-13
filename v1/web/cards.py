from typing import Any, Dict, Optional
from ..orchestrator.runner import OrchestratorResult


def build_card_data(result: OrchestratorResult) -> Dict[str, Any]:
    """
    Builds structured card data according to Section 7 of V3 plan.
    All UI labels and titles are in English.
    """
    if result.branch == "dictation":
        return {
            "type": "dictation",
            "title": "Dictation",
            "badge": "Dictation",
            "text": result.output_text,
            "can_copy": True,
            "raw_text": result.raw_text,
            "cleaned": bool(result.cleaned_text and result.cleanup_changed),
        }

    # Branch is "command"
    agent_res = result.agent_result

    # 1. When tools are disabled or agent is placeholder
    if not result.tools_enabled or (agent_res and agent_res.outcome == "tools_disabled"):
        return {
            "type": "tools_disabled",
            "title": "Command (Tools Disabled)",
            "badge": "Tools Disabled",
            "label": "tools off",
            "explanation": agent_res.reply if agent_res else (result.command_placeholder or result.output_text),
            "raw_text": result.raw_text,
        }

    if not agent_res:
        return {
            "type": "placeholder",
            "title": "Command",
            "badge": "Command",
            "text": result.output_text,
        }

    # 2. Tool calls
    if agent_res.outcome == "tool_call" and agent_res.tool_name:
        tool_name = agent_res.tool_name
        tool_args = agent_res.tool_args or {}

        if tool_name == "create_calendar_event":
            return {
                "type": "calendar",
                "title": "Calendar Event",
                "badge": "Calendar",
                "event_title": tool_args.get("title", "Meeting"),
                "date": tool_args.get("date", "N/A"),
                "start_time": tool_args.get("start_time", "N/A"),
                "attendees": tool_args.get("attendees", []),
                "reply": agent_res.reply,
                "status": "created (dummy)",
            }
        elif tool_name == "send_email":
            return {
                "type": "email",
                "title": "Email Message",
                "badge": "Email",
                "to": tool_args.get("to", "N/A"),
                "subject": tool_args.get("subject", "N/A"),
                "body": tool_args.get("body", ""),
                "reply": agent_res.reply,
                "status": "sent (dummy)",
            }
        elif tool_name == "set_reminder":
            return {
                "type": "reminder",
                "title": "Reminder",
                "badge": "Reminder",
                "text": tool_args.get("text", "N/A"),
                "date": tool_args.get("date", "N/A"),
                "time": tool_args.get("time", "N/A"),
                "reply": agent_res.reply,
                "status": "set (dummy)",
            }

    # 3. Clarification Question
    if agent_res.outcome == "missing_detail":
        return {
            "type": "question",
            "title": "Clarification Needed",
            "badge": "Question",
            "question": agent_res.reply,
            "raw_text": result.raw_text,
        }

    # 4. Refusal / No matching tool
    if agent_res.outcome == "no_matching_tool":
        return {
            "type": "refusal",
            "title": "Refusal / Unsupported",
            "badge": "Refusal",
            "reason": agent_res.reply,
            "raw_text": result.raw_text,
        }

    # Generic fallback
    return {
        "type": "command_reply",
        "title": "Command Reply",
        "badge": "Command",
        "text": agent_res.reply,
    }
