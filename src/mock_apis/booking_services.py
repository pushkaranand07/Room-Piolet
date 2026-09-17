# src/mock_apis/booking_services.py
"""
Booking persistence layer.

Thread-safety guarantees
------------------------
Every read-modify-write against bookings.json is protected by _BOOKINGS_LOCK
(threading.Lock) and written via _atomic_write() which flushes to a .tmp file
then renames it — making the write atomic on both POSIX and Windows NTFS.
"""
import json
import os
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional, Union, Dict

from langchain_core.tools import tool

from src.config import BOOKINGS_FILE, DELAY, now_local


# ── 4.1: module-level lock ─────────────────────────────────────────────────
_BOOKINGS_LOCK = threading.Lock()


# ── helpers ────────────────────────────────────────────────────────────────

def _atomic_write(filepath: Path, data: dict) -> None:
    """Write *data* to *filepath* atomically via a .tmp sibling + os.replace()."""
    tmp = filepath.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, filepath)


def load_bookings(
        filepath: Path = BOOKINGS_FILE
    ) -> Dict[str, List[Dict[str, Union[str, datetime]]]]:
    """Load existing bookings from external file (read-only, no lock needed)."""
    existing_data: Dict[str, List[Dict[str, Union[str, datetime]]]] = {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            existing_data = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        existing_data = {}
    return existing_data


def save_bookings_tool(
        room_id: Union[int, str],
        booking: Dict,
        file_path: Path = BOOKINGS_FILE,
    ) -> None:
    """Append *booking* to *room_id*'s list and flush atomically."""
    room_id = str(room_id)
    # 4.1: hold the lock for the full read-modify-write cycle
    with _BOOKINGS_LOCK:
        bookings = load_bookings(filepath=file_path)
        room_bookings = bookings.get(room_id, [])
        room_bookings.append(booking)
        bookings[room_id] = room_bookings
        _atomic_write(file_path, bookings)


def check_time_conflict_tool(
        existing_bookings: List[Dict[str, Union[str, datetime]]],
        room_id: int,
        start_time: Union[str, datetime],
        end_time: Optional[Union[str, datetime]] = None,
        duration_hours: Optional[float] = None,
    ) -> bool:
    """Check if a room has a time conflict for the requested time."""
    start_time = datetime.fromisoformat(start_time)
    if isinstance(end_time, str):
        end_time = datetime.fromisoformat(end_time)
    end_time = end_time or (start_time + timedelta(hours=duration_hours))

    room_bookings = existing_bookings.get(str(room_id), [])
    if not room_bookings:
        return False
    for booking in room_bookings:
        booking_start = datetime.fromisoformat(booking['start_time'])
        booking_end = datetime.fromisoformat(booking['end_time']) + DELAY
        if start_time < booking_end and end_time > booking_start:
            return True
    return False


def get_room_reserved_time_slots(
        room_id: Union[int, str],
        existing_bookings: Dict[str, List[Dict[str, Union[str, datetime]]]]) -> List[Dict]:
    free_time_slots = []
    room_id = str(room_id)
    return free_time_slots


@tool("book_room", description="Book a room for the specified time and user.")
def book_room_tool(
        room_id: int, start_time: str,
        end_time: str, user_name: str
    ) -> Optional[Dict[str, Union[int, str]]]:
    """Book a room for the specified time and user."""
    existing_bookings = load_bookings()
    if check_time_conflict_tool(
        existing_bookings,
        room_id,
        start_time,
        end_time=end_time,
    ):
        return None
    booking = {
        "room_id": room_id,
        "start_time": start_time,
        "end_time": end_time,
        "booked_by": user_name,
    }
    save_bookings_tool(room_id, booking)
    return booking


def create_booking(
    room_id: Union[int, str],
    start_date: str,
    start_time: str,
    duration_hours: float,
    user_name: str,
    purpose: str = "",
) -> Dict:
    """Create and persist a booking, returning a confirmed receipt."""
    import uuid

    time_str = str(start_time).strip()
    start_dt = None
    if any(ampm in time_str.upper() for ampm in ["AM", "PM"]):
        for fmt in ["%Y-%m-%d %I:%M:%S %p", "%Y-%m-%d %I:%M %p", "%Y-%m-%d %I %p"]:
            try:
                start_dt = datetime.strptime(f"{start_date} {time_str}", fmt)
                break
            except ValueError:
                continue
    else:
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H"]:
            try:
                start_dt = datetime.strptime(f"{start_date} {time_str}", fmt)
                break
            except ValueError:
                continue

    if not start_dt:
        # 4.4: fall back to TZ-aware local time instead of bare datetime.now()
        start_dt = now_local().replace(tzinfo=None) + timedelta(days=1)

    start_iso = start_dt.isoformat()
    end_iso = (start_dt + timedelta(hours=float(duration_hours or 1))).isoformat()

    booking_id = f"BK-{uuid.uuid4().hex[:6].upper()}"
    booking_record = {
        "booking_id": booking_id,
        "room_id": str(room_id),
        "start_time": start_iso,
        "end_time": end_iso,
        "booked_by": user_name,
        "purpose": purpose,
        # 4.4: use TZ-aware now_local() for consistent created_at timestamps
        "created_at": now_local().replace(tzinfo=None).isoformat(),
    }

    save_bookings_tool(room_id=str(room_id), booking=booking_record)
    return booking_record


def cancel_booking(booking_id: str) -> dict:
    """Remove a booking by ID. Returns {cancelled: True, booking: ...}."""
    # 4.1: hold the lock for the full read-modify-write cycle
    with _BOOKINGS_LOCK:
        bookings = load_bookings()
        for room_id, entries in bookings.items():
            for i, entry in enumerate(entries):
                if entry.get("booking_id") == booking_id:
                    removed = entries.pop(i)
                    _atomic_write(BOOKINGS_FILE, bookings)
                    return {"cancelled": True, "booking": removed}
    return {"cancelled": False, "error": f"Booking {booking_id} not found"}


def list_bookings_for_user(user_name: str) -> list[dict]:
    """Return all bookings made by a user."""
    bookings = load_bookings()
    result = []
    for room_id, entries in bookings.items():
        for entry in entries:
            name = entry.get("booked_by") or entry.get("user_name") or ""
            if name.lower() == user_name.lower():
                result.append({**entry, "room_id": str(room_id)})
    return result


def get_booking_by_id(booking_id: str) -> Optional[dict]:
    """Return a single booking or None."""
    bookings = load_bookings()
    for room_id, entries in bookings.items():
        for entry in entries:
            if entry.get("booking_id") == booking_id:
                return {**entry, "room_id": str(room_id)}
    return None
