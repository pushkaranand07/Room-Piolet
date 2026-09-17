import pytest
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from src.booking_agent.workflow import get_test_agent
from src.booking_agent.tools import (
    search_rooms_tool, book_room_tool, cancel_booking_tool,
    list_user_bookings_tool, get_booking_tool,
)


def _send(agent, cfg, text):
    return agent.invoke(
        {"messages": [HumanMessage(content=text)]},
        config=cfg,
    )


# ---------- Unit tests: tools work standalone ----------

def test_search_tool_returns_rooms():
    result = search_rooms_tool.invoke({
        "start_date": "2026-10-01",
        "start_time": "14:00",
        "duration_hours": 1,
        "capacity": 2,
    })
    assert "rooms" in result
    assert isinstance(result["rooms"], list)


def test_book_then_cancel_roundtrip():
    # Search first to get a valid room
    search = search_rooms_tool.invoke({
        "start_date": "2026-10-01",
        "start_time": "15:00",
        "duration_hours": 1,
        "capacity": 1,
    })
    if not search["rooms"]:
        pytest.skip("No rooms available for test date")

    room = search["rooms"][0]
    booking = book_room_tool.invoke({
        "room_id": str(room["id"]),
        "start_date": "2026-10-01",
        "start_time": "15:00",
        "duration_hours": 1,
        "user_name": "TestUser",
    })
    assert "booking_id" in booking

    # Cancel it
    cancelled = cancel_booking_tool.invoke({"booking_id": booking["booking_id"]})
    assert cancelled.get("cancelled") is True


def test_list_user_bookings():
    result = list_user_bookings_tool.invoke({"user_name": "TestUser"})
    assert "bookings" in result


# ---------- Integration: LLM autonomously calls tools ----------

def test_llm_searches_when_user_asks_for_room():
    agent = get_test_agent()
    cfg = {"configurable": {"thread_id": "tool-1"}}
    result = _send(agent, cfg, "find me a room tomorrow at 2pm for 4 people")

    # The LLM should have called search_rooms at some point or routed to search_and_present
    called_tools = [
        tc["name"]
        for msg in result["messages"]
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None)
        for tc in msg.tool_calls
    ]
    assert "search_rooms" in called_tools or result.get("candidate_rooms")


def test_llm_does_not_book_without_confirmation():
    """Critical safety test: LLM must not call book_room speculatively."""
    agent = get_test_agent()
    cfg = {"configurable": {"thread_id": "tool-2"}}

    result = _send(agent, cfg, "book me a room tomorrow at 3pm")

    called_tools = [
        tc["name"]
        for msg in result["messages"]
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None)
        for tc in msg.tool_calls
    ]
    assert "book_room" not in called_tools, \
        "LLM called book_room without user confirmation!"


def test_cancel_flow():
    agent = get_test_agent()
    cfg = {"configurable": {"thread_id": "tool-3"}}

    # First, book something
    r1 = _send(agent, cfg, "room tomorrow 2pm for 2, name is Alex")
    if r1.get("phase") == "presenting" and r1.get("candidate_rooms"):
        first = r1["candidate_rooms"][0]
        r2 = _send(agent, cfg, first["name"])
        if r2.get("phase") == "collecting":
            _send(agent, cfg, "Alex")
        _send(agent, cfg, "yes")

    # Now try to cancel
    r = _send(agent, cfg, "cancel my booking")
    # LLM should either ask for ID, list, or call cancel directly
    assert r["phase"] in ("cancelled", "idle", "error", "confirming")


def test_unknown_intent_falls_back_to_llm():
    agent = get_test_agent()
    cfg = {"configurable": {"thread_id": "tool-4"}}
    result = _send(agent, cfg, "who are you and what can you do?")
    assert result["messages"][-1].content  # LLM answered something
    assert result["phase"] in ("idle", "booked")
