"""
tests/fake_llm.py
-----------------
Deterministic fake LLM for unit tests. Never hits a real API.

Usage in tests:
    os.environ["LLM_PROVIDER"] = "fake"
    from src.helper import initialize_llm
    llm = initialize_llm(with_tools=True)

Or directly:
    from tests.fake_llm import FakeLLM, make_search_script, make_book_script

Scripting tool calls:
    llm = FakeLLM(with_tools=True)
    llm.script_response(
        matcher="find me a room",   # str (substring) or callable
        response={
            "content": "",
            "tool_calls": [{"name": "search_rooms", "args": {...}, "id": "call_1"}],
        }
    )
"""
from typing import Any, List, Optional, Iterator
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration


class FakeLLM(BaseChatModel):
    """
    Minimal ChatModel that returns pre-scripted responses.
    Fully compatible with LangChain's tool-binding interface.
    """
    with_tools: bool = False
    _scripts: List[Any] = []
    _call_count: int = 0

    model_config = {"arbitrary_types_allowed": True}

    def __init__(self, **data):
        super().__init__(**data)
        # Instance-level scripts list so tests don't share state
        object.__setattr__(self, "_scripts", [])
        object.__setattr__(self, "_call_count", 0)

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        """LangChain calls this when the agent binds tools. Return self."""
        object.__setattr__(self, "with_tools", True)
        return self

    def script_response(self, matcher, response):
        """
        Register a scripted response.

        Args:
            matcher: str (substring match on last message) | callable(BaseMessage) -> bool
            response: AIMessage | dict {"content": str, "tool_calls": [...]} | str
        """
        self._scripts.append((matcher, response))
        return self  # Allow chaining

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager=None,
        **kwargs,
    ) -> ChatResult:
        object.__setattr__(self, "_call_count", self._call_count + 1)
        last = messages[-1] if messages else None

        for matcher, response in self._scripts:
            matched = False
            if callable(matcher):
                matched = matcher(last)
            elif isinstance(matcher, str) and last is not None:
                matched = matcher.lower() in (getattr(last, "content", "") or "").lower()

            if matched:
                ai_msg = self._to_ai_message(response, messages)
                return ChatResult(generations=[ChatGeneration(message=ai_msg)])

        # 1. Post-tool execution: ToolMessage just ran, LLM should answer nicely
        if isinstance(last, ToolMessage) or getattr(last, "type", None) == "tool":
            tool_name = getattr(last, "name", "")
            if tool_name == "book_room":
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Booking confirmed! Your room has been booked successfully."))])
            elif tool_name == "cancel_booking":
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Your booking has been cancelled."))])
            elif tool_name == "search_rooms":
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Here are the available rooms I found."))])
            elif tool_name == "list_user_bookings":
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Here are your bookings."))])
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Action completed successfully."))])

        full_text = " ".join([str(getattr(m, "content", "")) for m in messages]).lower()

        # 2. Safety gate / confirmation: if user confirmed a pending booking, emit book_room tool call
        if self.with_tools and "user confirmed: true" in full_text and "room_id" in full_text:
            import re
            room_id_match = re.search(r"['\"]room_id['\"]\s*:\s*['\"]?([^'\",\s}]+)", full_text)
            room_id = room_id_match.group(1) if room_id_match else "1"
            start_date_match = re.search(r"['\"]start_date['\"]\s*:\s*['\"]([^'\"]+)", full_text)
            start_date = start_date_match.group(1) if start_date_match else "2026-10-01"
            start_time_match = re.search(r"['\"]start_time['\"]\s*:\s*['\"]([^'\"]+)", full_text)
            start_time = start_time_match.group(1) if start_time_match else "14:00"
            user_name_match = re.search(r"['\"]user_name['\"]\s*:\s*['\"]([^'\"]+)", full_text)
            user_name = user_name_match.group(1) if user_name_match else "Alex"

            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content="",
                tool_calls=[{
                    "name": "book_room",
                    "args": {
                        "room_id": str(room_id),
                        "start_date": start_date,
                        "start_time": start_time,
                        "duration_hours": 1.0,
                        "user_name": user_name,
                    },
                    "id": f"fake_call_{self._call_count}",
                    "type": "tool_call",
                }]
            ))])

        # 3. Handle structured parsing for BookingRequest (parse_request node)
        if "bookingrequest" in full_text or "parsing_schema" in full_text or "properties" in full_text:
            import json
            from datetime import datetime, timedelta

            user_portion = full_text
            if "current user request:" in full_text:
                user_portion = full_text.split("current user request:")[-1]
            elif "user:" in full_text:
                user_portion = full_text.split("user:")[-1]

            start_date = None
            if "tomorrow" in user_portion:
                start_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            elif "today" in user_portion:
                start_date = datetime.now().strftime("%Y-%m-%d")

            start_time = None
            if "2pm" in user_portion or "14:00" in user_portion:
                start_time = "02:00:00 PM"
            elif "3pm" in user_portion or "15:00" in user_portion:
                start_time = "03:00:00 PM"
            elif "10am" in user_portion or "10:00" in user_portion:
                start_time = "10:00:00 AM"

            duration = None
            if "2 hour" in user_portion or "for 2" in user_portion or "make it 2" in user_portion:
                duration = 2.0
            elif "1 hour" in user_portion or "for 1" in user_portion or "1 hr" in user_portion or "2pm" in user_portion or "3pm" in user_portion:
                duration = 1.0

            capacity = None
            if "4 people" in user_portion or "for 4" in user_portion:
                capacity = 4
            elif "2 people" in user_portion or "for 2" in user_portion:
                capacity = 2

            user_name = None
            if "alex" in user_portion:
                user_name = "Alex"
            elif "sam" in user_portion:
                user_name = "Sam"

            booking_dict = {
                "start_date": start_date,
                "start_time": start_time,
                "duration_hours": duration,
                "capacity": capacity,
                "equipments": [],
                "user_name": user_name,
                "clarification_needed": bool(not start_date and not start_time),
            }
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=json.dumps(booking_dict)))])

        # 4. Default fallback responses based on intent
        if "who are you" in full_text:
            content = "I am an AI booking assistant. I can help you search for rooms, make bookings, and view your schedule."
        elif "cancel" in full_text:
            if self.with_tools:
                return ChatResult(generations=[ChatGeneration(message=AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "cancel_booking",
                        "args": {"booking_id": "BK-123"},
                        "id": f"fake_call_{self._call_count}",
                        "type": "tool_call",
                    }]
                ))])
            content = "I can help cancel your booking. Please provide your booking ID."
        else:
            content = "I hear you. Could you clarify what you need?"

        return ChatResult(generations=[
            ChatGeneration(message=AIMessage(content=content))
        ])

    def _to_ai_message(self, response, messages) -> AIMessage:
        """Coerce response into an AIMessage."""
        if callable(response):
            return response(messages)
        if isinstance(response, AIMessage):
            return response
        if isinstance(response, dict):
            tool_calls = response.get("tool_calls", [])
            # Normalise tool call format for LangChain
            normalised = []
            for tc in tool_calls:
                normalised.append({
                    "name": tc["name"],
                    "args": tc.get("args", {}),
                    "id": tc.get("id", f"fake_call_{self._call_count}"),
                    "type": "tool_call",
                })
            return AIMessage(
                content=response.get("content", ""),
                tool_calls=normalised,
            )
        return AIMessage(content=str(response))

    # Required by BaseChatModel abstract interface
    def _stream(self, messages, stop=None, run_manager=None, **kwargs) -> Iterator:
        result = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        yield result.generations[0]


# ── Pre-built factory functions for common test scenarios ──────────────────

def make_search_script(
    start_date: str = "2026-10-01",
    start_time: str = "14:00",
    duration_hours: float = 1.0,
    capacity: int = 2,
) -> FakeLLM:
    """FakeLLM that always emits a search_rooms tool call."""
    llm = FakeLLM(with_tools=True)
    llm.script_response(
        matcher=lambda _m: True,  # match anything
        response={
            "content": "",
            "tool_calls": [{
                "name": "search_rooms",
                "args": {
                    "start_date": start_date,
                    "start_time": start_time,
                    "duration_hours": duration_hours,
                    "capacity": capacity,
                    "equipments": [],
                },
                "id": "fake_search_1",
            }],
        },
    )
    return llm


def make_book_script(room_id: str = "1", user_name: str = "Alex") -> FakeLLM:
    """FakeLLM that emits a book_room tool call — used to test the safety gate."""
    llm = FakeLLM(with_tools=True)
    llm.script_response(
        matcher=lambda _m: True,
        response={
            "content": "",
            "tool_calls": [{
                "name": "book_room",
                "args": {
                    "room_id": room_id,
                    "start_date": "2026-10-01",
                    "start_time": "14:00",
                    "duration_hours": 1.0,
                    "user_name": user_name,
                    "purpose": "test",
                },
                "id": "fake_book_1",
            }],
        },
    )
    return llm


def make_cancel_script(booking_id: str) -> FakeLLM:
    """FakeLLM that emits a cancel_booking tool call."""
    llm = FakeLLM(with_tools=True)
    llm.script_response(
        matcher=lambda _m: True,
        response={
            "content": "",
            "tool_calls": [{
                "name": "cancel_booking",
                "args": {"booking_id": booking_id},
                "id": "fake_cancel_1",
            }],
        },
    )
    return llm


def make_list_script(user_name: str = "Alex") -> FakeLLM:
    """FakeLLM that emits a list_user_bookings tool call."""
    llm = FakeLLM(with_tools=True)
    llm.script_response(
        matcher=lambda _m: True,
        response={
            "content": "",
            "tool_calls": [{
                "name": "list_user_bookings",
                "args": {"user_name": user_name},
                "id": "fake_list_1",
            }],
        },
    )
    return llm


def make_chat_script(message: str) -> FakeLLM:
    """FakeLLM that always returns a plain text response (no tool calls)."""
    llm = FakeLLM(with_tools=False)
    llm.script_response(matcher=lambda _m: True, response=message)
    return llm
