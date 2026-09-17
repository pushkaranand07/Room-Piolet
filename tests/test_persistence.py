"""
Phase 1 acceptance test: verify multi-turn state survives past the
old 4KB cookie limit by using LangGraph's MemorySaver (same reducer
logic as SqliteSaver, no disk I/O needed for tests).
"""
import unittest
from unittest.mock import patch
from langchain_core.messages import HumanMessage
from src.booking_agent.schemas import BookingRequest
from src.booking_agent.workflow import get_test_agent


def test_20_turns_persist_in_memory():
    """State accumulates across 20 turns — proves add_messages reducer works."""
    agent = get_test_agent()
    config = {"configurable": {"thread_id": "persist-test-1"}}

    mock_parsed = BookingRequest(
        clarification_needed=True,
        clarification_question="Could you clarify your booking details?",
    )

    with patch("langchain_core.runnables.base.RunnableSequence.invoke", return_value=mock_parsed):
        for i in range(20):
            agent.invoke(
                {"messages": [HumanMessage(content=f"Turn {i}")]},
                config=config,
            )

    state = agent.get_state(config)
    msgs = state.values["messages"]
    user_msgs = [m for m in msgs if m.type == "human"]
    assert len(user_msgs) == 20, f"Expected 20 human messages, got {len(user_msgs)}"
    assert user_msgs[0].content == "Turn 0"
    assert user_msgs[-1].content == "Turn 19"
    print(f"[OK] 20 turns persisted. First={user_msgs[0].content}, Last={user_msgs[-1].content}")


def test_threads_are_isolated():
    """Two thread_ids must have independent state — critical for multi-user."""
    agent = get_test_agent()

    cfg_a = {"configurable": {"thread_id": "user-a"}}
    cfg_b = {"configurable": {"thread_id": "user-b"}}

    mock_parsed_alice = BookingRequest(
        user_name="Alice",
        clarification_needed=True,
        clarification_question="Hi Alice, how can I help you?",
    )
    mock_parsed_bob = BookingRequest(
        user_name="Bob",
        clarification_needed=True,
        clarification_question="Hi Bob, how can I help you?",
    )

    def mock_invoke(input_data, *args, **kwargs):
        req = input_data.get("user_request", "") if isinstance(input_data, dict) else str(input_data)
        if "Bob" in req:
            return mock_parsed_bob
        return mock_parsed_alice

    with patch("langchain_core.runnables.base.RunnableSequence.invoke", side_effect=mock_invoke):
        agent.invoke({"messages": [HumanMessage(content="I am Alice")]}, config=cfg_a)
        agent.invoke({"messages": [HumanMessage(content="I am Bob")]}, config=cfg_b)
        agent.invoke({"messages": [HumanMessage(content="Still Alice")]}, config=cfg_a)

    state_a = agent.get_state(cfg_a)
    state_b = agent.get_state(cfg_b)

    user_a = [m for m in state_a.values["messages"] if m.type == "human"]
    user_b = [m for m in state_b.values["messages"] if m.type == "human"]

    assert len(user_a) == 2, f"Thread A: expected 2, got {len(user_a)}"
    assert len(user_b) == 1, f"Thread B: expected 1, got {len(user_b)}"
    assert user_a[0].content == "I am Alice"
    assert user_b[0].content == "I am Bob"
    print("[OK] Thread isolation verified")


def test_persists_across_restart():
    """The REAL test: state survives process death using SqliteSaver."""
    import os
    import sqlite3
    from src.booking_agent.workflow import create_workflow
    from langgraph.checkpoint.sqlite import SqliteSaver

    db_file = "data/test_persist.sqlite"
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except OSError:
            pass

    cfg = {"configurable": {"thread_id": "restart-test"}}

    mock_parsed = BookingRequest(
        clarification_needed=True,
        clarification_question="Clarify details",
    )

    with patch("langchain_core.runnables.base.RunnableSequence.invoke", return_value=mock_parsed):
        # Simulate process 1
        conn1 = sqlite3.connect(db_file, check_same_thread=False)
        agent1 = create_workflow().compile(checkpointer=SqliteSaver(conn1))
        agent1.invoke({"messages": [HumanMessage(content="Turn A")]}, config=cfg)
        agent1.invoke({"messages": [HumanMessage(content="Turn B")]}, config=cfg)
        conn1.close()

        # Simulate process 2 (fresh connection to same sqlite db)
        conn2 = sqlite3.connect(db_file, check_same_thread=False)
        agent2 = create_workflow().compile(checkpointer=SqliteSaver(conn2))
        state = agent2.get_state(cfg)
        conn2.close()

    user_msgs = [m for m in state.values["messages"] if m.type == "human"]
    assert len(user_msgs) == 2, f"State lost across restart! Got {len(user_msgs)}"
    assert user_msgs[0].content == "Turn A"
    assert user_msgs[1].content == "Turn B"
    if os.path.exists(db_file):
        try:
            os.remove(db_file)
        except OSError:
            pass
    print("[OK] State survives process restart via SqliteSaver")


class TestPersistence(unittest.TestCase):
    def test_20_turns(self):
        test_20_turns_persist_in_memory()

    def test_isolation(self):
        test_threads_are_isolated()

    def test_restart(self):
        test_persists_across_restart()


if __name__ == "__main__":
    unittest.main()

