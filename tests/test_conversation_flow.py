"""
Phase 2 test suite: verifies human-in-the-loop conversation flow.
"""
from datetime import datetime, timedelta
from unittest.mock import patch
from langchain_core.messages import HumanMessage
from src.booking_agent.schemas import BookingRequest
from src.booking_agent.workflow import get_test_agent


def _mock_llm_chain(*args, **kwargs):
    input_data = {}
    for a in args:
        if isinstance(a, dict):
            input_data = a
            break
    req = input_data.get("user_request", "")
    req_lower = req.lower()

    user_name = None
    if "alex" in req_lower:
        user_name = "Alex"
    elif "sam" in req_lower:
        user_name = "Sam"

    duration = None
    if "2 hours" in req_lower or "make it 2" in req_lower:
        duration = 2.0
    elif "1 hour" in req_lower or "2pm" in req_lower or "3pm" in req_lower:
        duration = 1.0

    capacity = 2
    if "4 people" in req_lower or "for 4" in req_lower:
        capacity = 4
    elif "for 2" in req_lower or "2 people" in req_lower:
        capacity = 2

    start_date = None
    if "tomorrow" in req_lower:
        start_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    start_time = None
    if "2pm" in req_lower:
        start_time = "02:00:00 PM"
    elif "3pm" in req_lower:
        start_time = "03:00:00 PM"

    return BookingRequest(
        start_date=start_date,
        start_time=start_time,
        duration_hours=duration,
        capacity=capacity,
        user_name=user_name,
        clarification_needed=False,
    )


def _send(agent, cfg, text):
    return agent.invoke(
        {"messages": [HumanMessage(content=text)]},
        config=cfg,
    )


def test_search_presents_but_does_not_book():
    agent = get_test_agent()
    cfg = {"configurable": {"thread_id": "flow-1"}}

    with patch("langchain_core.runnables.base.RunnableSequence.invoke", side_effect=_mock_llm_chain):
        result = _send(agent, cfg, "I need a room tomorrow at 2pm for 4 people")

    assert result["phase"] == "presenting"
    assert len(result["candidate_rooms"]) > 0
    assert result["ui_payload"]["type"] == "room_options"
    assert result.get("pending_booking") is None


def test_full_four_turn_flow():
    agent = get_test_agent()
    cfg = {"configurable": {"thread_id": "flow-2"}}

    with patch("langchain_core.runnables.base.RunnableSequence.invoke", side_effect=_mock_llm_chain):
        # Turn 1: search
        r1 = _send(agent, cfg, "room tomorrow 2pm for 2")
        assert r1["phase"] == "presenting"

        # Turn 2: select room by name
        first_room = r1["candidate_rooms"][0]
        r2 = _send(agent, cfg, first_room["name"])
        assert r2["phase"] in ("collecting", "confirming")
        assert r2["pending_booking"]["room_id"] == first_room["id"]

        # Turn 3: provide name if asked
        if r2["phase"] == "collecting":
            r3 = _send(agent, cfg, "Alex")
            assert r3["phase"] == "confirming"
        else:
            r3 = r2

        # Turn 4: confirm
        r4 = _send(agent, cfg, "yes")
        assert r4["phase"] == "booked"
        assert r4["ui_payload"]["type"] == "booking_receipt"
        assert "booking_id" in r4["ui_payload"]["booking"]


def test_rejection_does_not_book():
    agent = get_test_agent()
    cfg = {"configurable": {"thread_id": "flow-3"}}

    with patch("langchain_core.runnables.base.RunnableSequence.invoke", side_effect=_mock_llm_chain):
        r1 = _send(agent, cfg, "room tomorrow 2pm")
        first_room = r1["candidate_rooms"][0]
        r2 = _send(agent, cfg, first_room["name"])
        if r2["phase"] == "collecting":
            r3 = _send(agent, cfg, "Alex")
        else:
            r3 = r2
        assert r3["phase"] == "confirming"

        # Say NO
        r4 = _send(agent, cfg, "no, actually forget it")
        assert r4["phase"] != "booked"
        assert not (r4.get("ui_payload") or {}).get("booking")


def test_context_preserved_across_turns():
    """State must persist and merge across turns."""
    agent = get_test_agent()
    cfg = {"configurable": {"thread_id": "flow-4"}}

    with patch("langchain_core.runnables.base.RunnableSequence.invoke", side_effect=_mock_llm_chain):
        _send(agent, cfg, "my name is Alex, I need a room tomorrow 3pm")
        r2 = _send(agent, cfg, "1 hour please")
        r3 = _send(agent, cfg, "actually make it 2 hours")

    # 'Alex' should still be in state
    assert r3["parsed_request"].get("user_name") == "Alex"
    # Duration updated, not clobbered
    assert r3["parsed_request"].get("duration_hours") in (1, 2)


if __name__ == "__main__":
    test_search_presents_but_does_not_book()
    print("[OK] test_search_presents_but_does_not_book passed")
    test_full_four_turn_flow()
    print("[OK] test_full_four_turn_flow passed")
    test_rejection_does_not_book()
    print("[OK] test_rejection_does_not_book passed")
    test_context_preserved_across_turns()
    print("[OK] test_context_preserved_across_turns passed")
    print("\nALL 4 CONVERSATION FLOW TESTS PASSED!")
