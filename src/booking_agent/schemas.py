# src/booking_agent/schemas.py
"""Pydantic models and state schema for the booking agent."""
from typing import Annotated, List, Dict, Optional, Literal
from typing_extensions import TypedDict
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


## Agent State — persisted server-side by SqliteSaver
class AgentState(TypedDict, total=False):
    """
    Full agent state. total=False allows nodes to return partial dicts.
    `messages` uses add_messages reducer — each turn APPENDS, never overwrites.
    """
    messages: Annotated[List[BaseMessage], add_messages]
    phase: Literal["idle", "searching", "presenting", "collecting", "confirming", "booked", "cancelled", "error"]
    intent: Optional[str]

    # Request Processing
    user_input: str
    parsed_request: Optional[Dict]
    clarification_needed: bool
    clarification_question: Optional[str]
    user_name_for_booking: Optional[str]

    # Room Selection
    candidate_rooms: Optional[List[Dict]]
    matching_rooms: Optional[List[Dict]]
    available_rooms: Optional[List[Dict]]
    alternative_rooms: Optional[List[Dict]]
    selected_room: Optional[Dict]
    pending_booking: Optional[Dict]
    missing_fields: Optional[List[str]]
    user_confirmed: Optional[bool]
    _tools_approved: Optional[bool]
    ui_payload: Optional[Dict]

    # Booking Result
    booking_result: Optional[bool]
    error_message: Optional[str]
    error: Optional[str]

class BookingRequest(BaseModel):
    start_date: Optional[str] = Field(
        None,
        description="The starting date for the booking in the format YYYY-MM-DD (e.g., 2025-05-12)" \
        "This can be a specific date or derived from relative terms like 'tomorrow'." \
        "This date must be in future."
    )
    start_time: Optional[str] = Field(
        None,
        description="The starting time for the booking in the format HH:MM:SS AM/PM (e.g., 02:45:30 PM). " \
        "This can be a specific time or calculated from relative terms like 'after 1 hour'."\
        "The time must be in future." \
    )
    duration_hours: Optional[float] = Field(
        None,
        description="The duration of the booking in hours (e.g., 0.5 for 30 minutes, 1 for one hour)." \
        " Accepts fractional values for partial hours."
    )
    capacity: Optional[int] = Field(
        None,
        description="The number of people the room should accommodate (e.g., 5 for a room that fits 5 people)."\
        " This must be greater than 0. set it null if not applicable."
    )
    equipments: Optional[List[str]] = Field(
        default_factory=list,  # Default to an empty list if no value is provided
        description="A list of equipment required for the booking (e.g., ['projector', 'whiteboard'])."\
        "If user don't have specific equipments, write 'nothing'."
    )
    user_name: Optional[str] = Field(
        None,
        description="The name of the person making the booking to personalize the booking process."
    )
    clarification_needed: bool = Field(
        False,
        description="Indicates whether additional clarification is required to process the booking request"\
         " (e.g., True if the input is ambiguous or incomplete)."
    )
    clarification_question: Optional[str] = Field(
        None,
        description="A question to ask the user for clarification if required fields are nulls or ambiguous"\
             " (e.g., 'Could you specify the start time?')."
    )
