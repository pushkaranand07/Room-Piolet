# src/booking_agent/nodes.py

"""Phase 2 Human-in-the-Loop booking agent nodes."""
import os
import random
from datetime import datetime
from langchain.output_parsers import PydanticOutputParser
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage

from src.helper import initialize_llm, apply_request_prompt, get_missing_fields, load_clarification_msgs
from src.config import logger, TEMPERATURE
from src.booking_agent.schemas import AgentState, BookingRequest


def parse_request(state: AgentState, llm=None) -> dict:
    """
    Extract structured fields from the conversation.
    IMPORTANT: only overwrite fields the user just provided.
    Do NOT clear pending_booking / selected_room mid-flow.
    """
    logger.info(" ------------------ NODE: PARSE REQUEST ------------------ ")

    if llm is None:
        llm = initialize_llm(name="groq", temp=TEMPERATURE)

    current_date = datetime.now().strftime('%Y-%m-%d')
    current_time = datetime.now().strftime('%I:%M:%S %p')

    parser = PydanticOutputParser(pydantic_object=BookingRequest)
    prompt_template = apply_request_prompt(parser)

    # Extract latest user message
    messages = state.get("messages", [])
    latest_user_input = state.get("user_input", "")
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", None) == "human":
            latest_user_input = msg.content
            break

    # Build full request context from conversation history
    conversation_context = "\n".join(
        f"{'USER' if isinstance(msg, HumanMessage) or getattr(msg, 'type', None) == 'human' else 'AGENT'}: {msg.content}"
        for msg in messages
    )
    logger.info("\n>>>>> CONVERSATION CONTEXT: %s", conversation_context)

    merged = dict(state.get("parsed_request") or {})

    try:
        chain = prompt_template | llm | parser
        parsed_data = chain.invoke({
            "user_request": conversation_context,
            "current_date": current_date,
            "current_time": current_time,
        })
        parsed_dict = parsed_data.model_dump()
        logger.info("\n >>>>>>> PARSED REQUEST: %s", parsed_dict)
        for k, v in parsed_dict.items():
            if v not in (None, "", []):
                merged[k] = v

        return {
            "user_input": latest_user_input,
            "parsed_request": merged,
            "clarification_needed": parsed_data.clarification_needed,
            "clarification_question": parsed_data.clarification_question,
            "user_name_for_booking": merged.get("user_name"),
            "error_message": None,
        }
    except Exception as e:
        logger.exception("Request parsing failed: %s", str(e))
        return {
            "user_input": latest_user_input,
            "parsed_request": merged,
            "error_message": f"Failed to parse request: {str(e)}",
        }


def classify_intent(state: AgentState) -> dict:
    """
    Phase-aware intent classifier.
    Extends Phase 2 with cancel, list, reschedule, and 'unknown'.
    """
    phase = state.get("phase", "idle")
    messages = state.get("messages", [])
    last_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", None) == "human":
            last_msg = (msg.content or "").lower().strip()
            break

    logger.info(">>> CLASSIFY INTENT | phase=%s | last_msg=%r", phase, last_msg)

    # Check if last AI message was asking for confirmation
    prev_ai_msg = ""
    for msg in reversed(messages[:-1] if len(messages) > 1 else []):
        if isinstance(msg, AIMessage) or getattr(msg, "type", None) == "ai":
            prev_ai_msg = (msg.content or "").lower()
            break

    # --- Phase-driven (highest priority) ---
    if phase == "presenting":
        # Check for cancel/restart signals first
        if any(w in last_msg for w in ["never mind", "forget it", "cancel"]):
            return {"intent": "search"}
        return {"intent": "select_room"}

    if phase == "collecting":
        return {"intent": "provide_details"}

    CONFIRM_SET = {"yes", "yeah", "yep", "confirm", "sure", "ok"}
    REJECT_SET = {"no", "nope", "don't", "stop", "abort", "forget it"}
    msg_tokens = set(last_msg.split())

    if phase == "confirming":
        if (msg_tokens & CONFIRM_SET) or any(w in last_msg for w in ["book it", "go ahead", "please do"]):
            return {"intent": "confirm", "user_confirmed": True}
        if (msg_tokens & REJECT_SET) or any(w in last_msg for w in ["cancel", "forget it"]):
            return {"intent": "reject", "user_confirmed": False}
        return {"intent": "clarify_confirmation"}

    # --- Confirmation when AI previously asked to confirm (e.g. cancellation) ---
    if (msg_tokens & CONFIRM_SET) or any(w in last_msg for w in ["go ahead", "please do"]):
        if any(w in prev_ai_msg for w in ["cancel", "would you like me to", "shall i", "(yes / no)", "proceed"]):
            return {"intent": "cancel_booking", "user_confirmed": True}
        return {"intent": "unknown", "user_confirmed": True}

    # --- Keyword-driven (idle or booked phase) ---

    # Cancel signals
    if any(w in last_msg for w in ["cancel", "delete booking"]):
        confirmed = "bk-" in last_msg or any(w in last_msg for w in ["yes", "confirm", "please"])
        return {"intent": "cancel_booking", "user_confirmed": confirmed}

    # List signals
    if any(w in last_msg for w in ["my bookings", "show my", "list my",
                                    "what did i book", "my reservations"]):
        return {"intent": "list_bookings"}

    # Reschedule signals
    if any(w in last_msg for w in ["move my", "reschedule", "change my booking",
                                    "shift my"]):
        return {"intent": "reschedule"}

    # Smalltalk signals
    if any(w in last_msg for w in ["hello", "hi ", "hey", "thanks",
                                    "thank you", "how are you"]):
        return {"intent": "smalltalk"}

    # Search signals (explicit)
    if any(w in last_msg for w in ["book", "reserve", "need a room", "room",
                                    "find me", "looking for", "available"]) or (
        state.get("parsed_request", {}).get("start_date") and phase == "idle"
    ):
        return {"intent": "search"}

    # Fallback: let the LLM reason about it
    return {"intent": "unknown"}


def search_and_present(state: AgentState) -> dict:
    """
    Runs the search, stores candidates, and ENDS the turn by asking the user
    to pick one. Does NOT book. Sets phase='presenting'.
    """
    logger.info(" ------------------ NODE: SEARCH AND PRESENT ------------------ ")
    parsed = dict(state.get("parsed_request") or {})
    if not parsed.get("duration_hours"):
        parsed["duration_hours"] = 1.0

    # Validate we have enough to search
    required_for_search = ["start_date", "start_time"]
    missing = [f for f in required_for_search if not parsed.get(f)]
    if missing:
        return {
            "phase": "idle",
            "intent": "search",
            "missing_fields": missing,
            "messages": [AIMessage(content=(
                f"I need a bit more info to search: "
                f"{', '.join(missing)}. Could you provide those?"
            ))],
        }

    from src.mock_apis.room_services import find_matching_rooms
    rooms = find_matching_rooms(
        start_date=parsed["start_date"],
        start_time=parsed["start_time"],
        duration_hours=float(parsed["duration_hours"]),
        capacity=parsed.get("capacity") or 1,
        equipments=parsed.get("equipments", []),
    )

    if not rooms:
        return {
            "phase": "idle",
            "candidate_rooms": [],
            "messages": [AIMessage(content=(
                "I couldn't find any rooms matching that request. "
                "Want to adjust the time, capacity, or equipment?"
            ))],
        }

    top = rooms[:3]
    room_lines = "\n".join(
        f"{i+1}. **{r['name']}** — seats {r['capacity']}, "
        f"equipped with {', '.join(r['equipments']) if r.get('equipments') else 'basic setup'}"
        for i, r in enumerate(top)
    )

    return {
        "phase": "presenting",
        "candidate_rooms": top,
        "ui_payload": {
            "type": "room_options",
            "rooms": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "capacity": r["capacity"],
                    "equipments": r.get("equipments", []),
                }
                for r in top
            ],
        },
        "messages": [AIMessage(content=(
            f"I found {len(rooms)} matching room(s):\n\n{room_lines}\n\n"
            f"Which one would you like? Just say the number or the name."
        ))],
    }


def select_room(state: AgentState) -> dict:
    """
    User picked a room. Parse which one, then move to detail collection.
    """
    logger.info(" ------------------ NODE: SELECT ROOM ------------------ ")
    candidates = state.get("candidate_rooms", [])
    if not candidates:
        return {
            "phase": "idle",
            "messages": [AIMessage(content=(
                "I don't have any room options on the table. "
                "What kind of room are you looking for?"
            ))],
        }

    messages = state.get("messages", [])
    last_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", None) == "human":
            last_msg = (msg.content or "").lower().strip()
            break

    # Try to match by number ("1", "2", "first", "second", "third") or name ("tech hub")
    chosen = None
    ordinals = {"first": 1, "second": 2, "third": 3, "1st": 1, "2nd": 2, "3rd": 3}
    for word, idx in ordinals.items():
        if word in last_msg and idx <= len(candidates):
            chosen = candidates[idx - 1]
            break

    if not chosen:
        for i, room in enumerate(candidates):
            name = room["name"].lower()
            if str(i + 1) in last_msg or name in last_msg:
                chosen = room
                break

    # Fuzzy fallback: check any room name token appears
    if not chosen:
        for room in candidates:
            for token in room["name"].lower().split():
                if len(token) > 3 and token in last_msg:
                    chosen = room
                    break
            if chosen:
                break

    if not chosen:
        return {
            "messages": [AIMessage(content=(
                "Sorry, I didn't catch which room. "
                "You can say the number (1, 2, 3) or the room name."
            ))],
        }

    # Build pending booking draft
    parsed = state.get("parsed_request", {}) or {}
    user_name = state.get("user_name_for_booking") or parsed.get("user_name")

    pending = {
        "room_id": chosen["id"],
        "room_name": chosen["name"],
        "start_date": parsed.get("start_date"),
        "start_time": parsed.get("start_time"),
        "duration_hours": float(parsed.get("duration_hours") or 1.0),
        "user_name": user_name,
        "equipments": parsed.get("equipments", []),
        "purpose": parsed.get("purpose", ""),
    }

    # What's still missing?
    missing = [f for f in ["user_name"] if not pending.get(f)]

    if missing:
        return {
            "phase": "collecting",
            "selected_room": chosen,
            "pending_booking": pending,
            "missing_fields": missing,
            "messages": [AIMessage(content=(
                f"Great — **{chosen['name']}** it is.\n\n"
                f"Before I book it, could you tell me your name?"
            ))],
        }

    # All details known — jump straight to confirmation
    return _build_confirmation_response(pending, selected_room=chosen)


def collect_details(state: AgentState) -> dict:
    """
    User just provided missing info (usually their name).
    Merge into pending_booking and move to confirmation.
    """
    logger.info(" ------------------ NODE: COLLECT DETAILS ------------------ ")
    pending = dict(state.get("pending_booking") or {})
    messages = state.get("messages", [])
    last_msg = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", None) == "human":
            last_msg = (msg.content or "").strip()
            break

    # The last human message IS the value we needed
    missing_fields = state.get("missing_fields") or []
    if "user_name" in missing_fields and last_msg:
        clean_name = last_msg
        for prefix in ["my name is", "i am", "name is", "call me"]:
            if clean_name.lower().startswith(prefix):
                clean_name = clean_name[len(prefix):].strip()
        pending["user_name"] = clean_name[:80]

    # Also update parsed_request with user_name so it persists
    parsed = dict(state.get("parsed_request") or {})
    if pending.get("user_name"):
        parsed["user_name"] = pending["user_name"]

    # Recompute missing
    still_missing = [f for f in ["user_name"] if not pending.get(f)]

    if still_missing:
        return {
            "phase": "collecting",
            "pending_booking": pending,
            "missing_fields": still_missing,
            "parsed_request": parsed,
            "messages": [AIMessage(content=(
                f"I still need: {', '.join(still_missing)}."
            ))],
        }

    return _build_confirmation_response(pending, selected_room=state.get("selected_room"), parsed_request=parsed)


def _build_confirmation_response(pending: dict, selected_room: dict = None, parsed_request: dict = None) -> dict:
    """Helper: produce the confirmation prompt + phase='confirming'."""
    res = {
        "phase": "confirming",
        "pending_booking": pending,
        "missing_fields": [],
        "messages": [AIMessage(content=(
            f"Please confirm this booking:\n\n"
            f"• **Room**: {pending['room_name']}\n"
            f"• **Date**: {pending['start_date']}\n"
            f"• **Time**: {pending['start_time']} ({pending['duration_hours']}h)\n"
            f"• **Name**: {pending['user_name']}\n\n"
            f"Shall I book it? (yes / no)"
        ))],
        "ui_payload": {
            "type": "confirmation",
            "booking": pending,
        },
    }
    if selected_room:
        res["selected_room"] = selected_room
    if parsed_request:
        res["parsed_request"] = parsed_request
    return res


def execute_booking(state: AgentState) -> dict:
    """User confirmed. Actually write the booking."""
    logger.info(" ------------------ NODE: EXECUTE BOOKING ------------------ ")
    pending = state.get("pending_booking") or {}
    if not pending:
        return {
            "phase": "error",
            "error": "No pending booking to confirm",
            "messages": [AIMessage(content=(
                "Something went wrong — I don't have a booking to confirm. "
                "Let's start over: what room do you need?"
            ))],
        }

    try:
        from src.mock_apis.booking_services import create_booking
        result = create_booking(
            room_id=pending["room_id"],
            start_date=pending["start_date"],
            start_time=pending["start_time"],
            duration_hours=float(pending["duration_hours"]),
            user_name=pending["user_name"],
            purpose=pending.get("purpose", ""),
        )

        return {
            "phase": "booked",
            "pending_booking": None,
            "selected_room": None,
            "candidate_rooms": None,
            "parsed_request": None,
            "user_confirmed": True,
            "ui_payload": {
                "type": "booking_receipt",
                "booking": result,
            },
            "messages": [AIMessage(content=(
                f"[Booked] Your confirmation is **{result['booking_id']}**.\n\n"
                f"• {pending['room_name']} on {pending['start_date']} "
                f"at {pending['start_time']}\n"
                f"• Booked under {pending['user_name']}\n\n"
                f"Anything else?"
            ))],
        }
    except Exception as e:
        logger.exception("execute_booking error: %s", str(e))
        return {
            "phase": "error",
            "error": str(e),
            "messages": [AIMessage(content=(
                f"Sorry, I couldn't complete the booking: {e}.\n"
                f"Want to try again or pick a different room?"
            ))],
        }


def respond_smalltalk(state: AgentState) -> dict:
    """Non-booking chit-chat. Keeps phase intact so context isn't lost."""
    logger.info(" ------------------ NODE: RESPOND SMALLTALK ------------------ ")
    return {
        "messages": [AIMessage(content=(
            "Happy to help! Tell me what kind of room you need — "
            "date, time, how long, and any equipment — and I'll find options."
        ))],
    }


def ask_clarification(state: AgentState) -> dict:
    """Handle rejected bookings or clarification questions."""
    logger.info(" ------------------ NODE: ASK CLARIFICATION ------------------ ")
    phase = state.get("phase", "idle")
    if phase == "confirming":
        # User said "no" at confirmation — wipe all booking state AND ui_payload
        return {
            "phase": "idle",
            "pending_booking": None,
            "selected_room": None,
            "candidate_rooms": None,
            "ui_payload": None,
            "messages": [AIMessage(content=(
                "No problem, I've cancelled that booking draft. "
                "What kind of room would you like to search for instead?"
            ))],
        }

    clarification_msg = state.get("parsed_request", {}).get("clarification_question")
    missed_fields = state.get("missing_fields") or []
    if not clarification_msg:
        missed_fields = get_missing_fields(state.get("parsed_request", {}))
        if missed_fields:
            msgs = load_clarification_msgs()
            clarification_msg = random.choice(msgs[missed_fields[0]])
        else:
            clarification_msg = state.get("error_message", "Could you provide a little more information about your booking?")

    return {
        "phase": "idle",
        "clarification_question": clarification_msg,
        "ui_payload": {
            "type": "clarification",
            "missing_fields": missed_fields,
        },
        "messages": [AIMessage(content=clarification_msg)],
    }


# ---------- Phase 3: Agent Reasoning & Tool Execution Nodes ----------

AGENT_SYSTEM_PROMPT = """You are RoomPilot, a meeting room booking assistant.

You have tools available. Use them when appropriate:
- search_rooms: find available rooms matching user criteria
- book_room: book a room (ONLY after explicit user confirmation)
- cancel_booking: cancel a booking (ONLY after explicit user confirmation)
- list_user_bookings: show a user's bookings
- get_booking: look up a single booking by ID

RULES:
1. When phase is 'confirming' and user confirms (says 'yes', 'confirm', 'book it'), call book_room immediately with the pending booking details:
   room_id, start_date, start_time, duration_hours, user_name, purpose.
2. Never call book_room or cancel_booking speculatively without explicit user confirmation.
3. Before booking, make sure you have: room selection, date, time, duration, and user name.
4. When presenting search results, use a numbered list with room name, capacity, and equipment. Then ask the user to choose.
5. If the user asks to list or show their bookings, call list_user_bookings with their name.
6. If the user wants to cancel a booking, look up or ask for their booking ID, and only call cancel_booking after they confirm.
7. If the user's intent is unclear, ask a clarifying question. Do not guess.

Current conversation phase: {phase}
User confirmed: {user_confirmed}
Current pending booking: {pending_booking}
"""

_CACHED_LLM_WITH_TOOLS = None
_CACHED_PROVIDER = None

def get_tool_llm():
    global _CACHED_LLM_WITH_TOOLS, _CACHED_PROVIDER
    current_provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if _CACHED_LLM_WITH_TOOLS is None or _CACHED_PROVIDER != current_provider:
        _CACHED_LLM_WITH_TOOLS = initialize_llm(with_tools=True, temp=0.1)
        _CACHED_PROVIDER = current_provider
    return _CACHED_LLM_WITH_TOOLS


def agent_reasoning(state: AgentState, llm=None) -> dict:
    """
    The LLM reasons about the conversation and either:
      (a) calls a tool, or
      (b) responds directly to the user.

    If a tool is called, workflow routes to ToolNode.
    If not, workflow ends the turn.
    """
    logger.info(" ------------------ NODE: AGENT REASONING ------------------ ")
    phase = state.get("phase", "idle")
    pending = state.get("pending_booking") or {}
    user_confirmed = state.get("user_confirmed", False)

    system = SystemMessage(content=AGENT_SYSTEM_PROMPT.format(
        phase=phase,
        user_confirmed=user_confirmed,
        pending_booking=pending or "none",
    ))

    # Give the LLM the full conversation
    convo = [system] + list(state.get("messages", []))

    if llm is None:
        llm = get_tool_llm()

    response = llm.invoke(convo)

    return {
        "messages": [response],
        "phase": phase,
    }


def prepare_tool_call(state: AgentState) -> dict:
    """
    Optional hook before ToolNode executes.
    """
    return {}


def confirm_destructive_tool(state: AgentState) -> dict:
    """
    Inspects the last AIMessage's tool_calls. If any are destructive
    (book_room, cancel_booking) and user has NOT confirmed, block and ask.
    """
    logger.info(" ------------------ NODE: CONFIRM DESTRUCTIVE TOOL ------------------ ")
    messages = state.get("messages", [])
    if not messages:
        return {"_tools_approved": True}
    last = messages[-1]
    tool_calls = getattr(last, "tool_calls", None) or []
    destructive = [
        tc for tc in tool_calls
        if tc.get("name") in {"book_room", "cancel_booking"}
    ]
    if not destructive:
        return {"_tools_approved": True}

    if state.get("user_confirmed"):
        return {"_tools_approved": True}

    # Block — emit a ToolMessage saying "not confirmed" so LLM can react
    blocked_msgs = [
        ToolMessage(
            content=f"BLOCKED: {tc['name']} requires explicit user confirmation. "
                    f"Ask the user first.",
            tool_call_id=tc.get("id", "blocked"),
        )
        for tc in destructive
    ]
    prompt_msg = AIMessage(content="Please confirm first: would you like me to proceed with this action? (yes / no)")
    return {
        "_tools_approved": False,
        "messages": blocked_msgs + [prompt_msg],
        "phase": "confirming",
    }


def apply_tool_result(state: AgentState) -> dict:
    """
    Called after ToolNode runs. Inspects the ToolMessage and updates
    AgentState fields based on which tool ran.

    This is where we translate tool output into phase changes and ui_payload.
    """
    logger.info(" ------------------ NODE: APPLY TOOL RESULT ------------------ ")
    messages = state.get("messages", [])
    if not messages:
        return {}
    last = messages[-1]  # ToolMessage
    tool_name = getattr(last, "name", "") or ""
    content = getattr(last, "content", "")

    # Tool output may be dict or JSON string — normalize
    if isinstance(content, str):
        import json
        try:
            data = json.loads(content)
        except Exception:
            data = {"raw": content}
    else:
        data = content or {}

    # --- search_rooms ---
    if tool_name == "search_rooms":
        rooms = data.get("rooms", [])
        return {
            "phase": "presenting",
            "candidate_rooms": rooms,
            "ui_payload": {"type": "room_options", "rooms": rooms},
        }

    # --- book_room ---
    if tool_name == "book_room":
        if "booking_id" in data:
            booking = {
                **data,
                "room_name": (
                    (state.get("selected_room") or {}).get("name")
                    or (state.get("pending_booking") or {}).get("room_name")
                ),
            }
            return {
                "phase": "booked",
                "pending_booking": None,
                "selected_room": None,
                "candidate_rooms": None,
                "user_confirmed": True,
                "ui_payload": {"type": "booking_receipt", "booking": booking},
            }
        return {
            "phase": "error",
            "error": data.get("error", "Booking failed"),
        }

    # --- cancel_booking ---
    if tool_name == "cancel_booking":
        if data.get("cancelled"):
            return {
                "phase": "cancelled",
                "ui_payload": {"type": "cancellation_receipt", "booking": data.get("booking", {})},
            }
        return {"phase": "error", "error": data.get("error", "Cancel failed")}

    # --- list_user_bookings ---
    if tool_name == "list_user_bookings":
        return {
            "ui_payload": {"type": "booking_list", "bookings": data.get("bookings", [])},
        }

    # --- get_booking ---
    if tool_name == "get_booking":
        return {
            "ui_payload": {"type": "booking_detail", "booking": data},
        }

    # Unknown tool — no state change, let reasoning continue
    return {}