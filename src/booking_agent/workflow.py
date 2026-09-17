# src/booking_agent/workflow.py
"""Workflow using LangGraph for human-in-the-loop and autonomous tool-calling booking agent."""

import os
import sqlite3
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import AIMessage

from src.booking_agent.schemas import AgentState
from src.booking_agent.tools import ALL_TOOLS
from src.booking_agent.nodes import (
    parse_request,
    classify_intent,
    search_and_present,
    select_room,
    collect_details,
    execute_booking,
    respond_smalltalk,
    ask_clarification,
    agent_reasoning,
    confirm_destructive_tool,
    apply_tool_result,
)


def should_use_tool(state: AgentState) -> str:
    """
    Inspect the last AI message. If it has tool_calls, route to ToolNode/guardrail.
    Otherwise, the agent has answered the user — end the turn.
    """
    messages = state.get("messages", [])
    if not messages:
        return "end"
    last = messages[-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "tool"
    return "end"


def create_workflow() -> StateGraph:
    wf = StateGraph(AgentState)

    # Existing Phase 2 nodes
    wf.add_node("parse_request", parse_request)
    wf.add_node("classify_intent", classify_intent)
    wf.add_node("search_and_present", search_and_present)
    wf.add_node("select_room", select_room)
    wf.add_node("collect_details", collect_details)
    wf.add_node("respond_smalltalk", respond_smalltalk)
    wf.add_node("ask_clarification", ask_clarification)

    # Phase 3 tool nodes
    wf.add_node("agent_reasoning", agent_reasoning)
    wf.add_node("confirm_destructive", confirm_destructive_tool)
    wf.add_node("tools", ToolNode(ALL_TOOLS))
    wf.add_node("apply_tool_result", apply_tool_result)

    wf.set_entry_point("parse_request")

    # After parsing, always classify intent
    wf.add_edge("parse_request", "classify_intent")

    # Intent → branch
    wf.add_conditional_edges(
        "classify_intent",
        lambda s: s.get("intent", "search"),
        {
            "search": "search_and_present",
            "select_room": "select_room",
            "provide_details": "collect_details",
            "confirm": "agent_reasoning",
            "reject": "ask_clarification",
            "clarify_confirmation": "respond_smalltalk",
            "cancel_booking": "agent_reasoning",
            "list_bookings": "agent_reasoning",
            "reschedule": "agent_reasoning",
            "smalltalk": "respond_smalltalk",
            "unknown": "agent_reasoning",
        },
    )

    # Terminal nodes — all end the turn
    wf.add_edge("search_and_present", END)
    wf.add_edge("select_room", END)
    wf.add_edge("collect_details", END)
    wf.add_edge("respond_smalltalk", END)
    wf.add_edge("ask_clarification", END)

    # Tool calling loop with safety gate
    wf.add_conditional_edges(
        "agent_reasoning",
        should_use_tool,
        {"tool": "confirm_destructive", "end": END},
    )
    wf.add_conditional_edges(
        "confirm_destructive",
        lambda s: "execute" if s.get("_tools_approved") else "blocked",
        {"execute": "tools", "blocked": END},
    )
    wf.add_edge("tools", "apply_tool_result")
    wf.add_conditional_edges(
        "apply_tool_result",
        lambda s: "done" if s.get("phase") in {"booked", "cancelled", "error"} else "continue",
        {"done": END, "continue": "agent_reasoning"},
    )

    return wf


def get_compiled_agent(db_path: str = "data/checkpoints.sqlite"):
    """
    Compile with a PERSISTENT SQLite checkpointer.
    State survives Flask restarts, process crashes, and deployments.
    """
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    memory = SqliteSaver(conn)
    graph = create_workflow()
    return graph.compile(checkpointer=memory)


def get_test_agent():
    """In-memory checkpointer for unit tests. No disk I/O."""
    graph = create_workflow()
    return graph.compile(checkpointer=MemorySaver())