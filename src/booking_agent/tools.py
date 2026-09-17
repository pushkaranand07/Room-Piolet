"""
Tool definitions for RoomPilot.
Each tool has a Pydantic args schema so the LLM knows exactly what to pass.
Tools are thin wrappers around src/mock_apis/* functions — they do NOT
contain business logic themselves.
"""
from typing import Optional, List
from pydantic import BaseModel, Field
from langchain_core.tools import tool

from src.mock_apis.room_services import find_matching_rooms
from src.mock_apis.booking_services import (
    create_booking as _create_booking,
    cancel_booking as _cancel_booking,
    list_bookings_for_user as _list_bookings_for_user,
    get_booking_by_id as _get_booking_by_id,
)


# ---------- Search ----------

class SearchRoomsInput(BaseModel):
    start_date: str = Field(description="ISO date YYYY-MM-DD")
    start_time: str = Field(description="Time string e.g. 14:00, 02:00:00 PM")
    duration_hours: float = Field(ge=0.5, le=8, description="Duration in hours")
    capacity: int = Field(default=1, ge=1, description="Minimum room capacity")
    equipments: List[str] = Field(
        default_factory=list,
        description="Required equipment, e.g. ['projector', 'whiteboard']",
    )


@tool("search_rooms", args_schema=SearchRoomsInput)
def search_rooms_tool(
    start_date: str,
    start_time: str,
    duration_hours: float,
    capacity: int = 1,
    equipments: Optional[List[str]] = None,
) -> dict:
    """
    Search for available meeting rooms matching criteria.
    Returns a list of matching rooms. Does NOT book anything.
    """
    rooms = find_matching_rooms(
        start_date=start_date,
        start_time=start_time,
        duration_hours=duration_hours,
        capacity=capacity,
        equipments=equipments or [],
    )
    return {
        "count": len(rooms),
        "rooms": [
            {
                "id": r["id"],
                "name": r["name"],
                "capacity": r["capacity"],
                "equipments": r.get("equipments", []),
            }
            for r in rooms[:5]
        ],
    }


# ---------- Book ----------

class BookRoomInput(BaseModel):
    room_id: str = Field(description="Room ID from search results")
    start_date: str = Field(description="ISO date YYYY-MM-DD")
    start_time: str = Field(description="Time string e.g. 14:00, 02:00:00 PM")
    duration_hours: float = Field(ge=0.5, le=8)
    user_name: str = Field(description="Name to book under")
    purpose: str = Field(default="", description="Meeting purpose (optional)")


@tool("book_room", args_schema=BookRoomInput)
def book_room_tool(
    room_id: str,
    start_date: str,
    start_time: str,
    duration_hours: float,
    user_name: str,
    purpose: str = "",
) -> dict:
    """
    Book a room. Only call this AFTER the user has explicitly confirmed
    (said 'yes', 'confirm', 'book it', etc.). Never call speculatively.
    """
    return _create_booking(
        room_id=room_id,
        start_date=start_date,
        start_time=start_time,
        duration_hours=duration_hours,
        user_name=user_name,
        purpose=purpose,
    )


# ---------- Cancel ----------

class CancelBookingInput(BaseModel):
    booking_id: str = Field(description="Booking ID to cancel, e.g. BK-3F6BBE")


@tool("cancel_booking", args_schema=CancelBookingInput)
def cancel_booking_tool(booking_id: str) -> dict:
    """
    Cancel an existing booking by ID. Only call after explicit confirmation.
    """
    return _cancel_booking(booking_id)


# ---------- List ----------

class ListUserBookingsInput(BaseModel):
    user_name: str = Field(description="User name whose bookings to list")


@tool("list_user_bookings", args_schema=ListUserBookingsInput)
def list_user_bookings_tool(user_name: str) -> dict:
    """List all active bookings for a given user."""
    bookings = _list_bookings_for_user(user_name)
    return {"count": len(bookings), "bookings": bookings}


# ---------- Lookup ----------

class GetBookingInput(BaseModel):
    booking_id: str = Field(description="Booking ID to look up")


@tool("get_booking", args_schema=GetBookingInput)
def get_booking_tool(booking_id: str) -> dict:
    """Fetch details of a single booking by ID."""
    booking = _get_booking_by_id(booking_id)
    if not booking:
        return {"error": f"No booking found with ID {booking_id}"}
    return booking


# ---------- Registry ----------

ALL_TOOLS = [
    search_rooms_tool,
    book_room_tool,
    cancel_booking_tool,
    list_user_bookings_tool,
    get_booking_tool,
]

DESTRUCTIVE_TOOLS = {"book_room", "cancel_booking"}  # require user confirmation
