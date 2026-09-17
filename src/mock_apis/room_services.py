# src/mock_apis/room_services.py
import json
from pathlib import Path
from typing import List, Dict, Optional
from langchain_core.tools import tool
from src.config import ROOMS_FILE


# 4.3 — Fuzzy equipment matching helper
def _normalize(s: str) -> str:
    """Lowercase + collapse hyphens and extra spaces for fuzzy equipment comparison."""
    return s.lower().replace("-", " ").replace("_", " ").strip()


def check_room_availability_equipment(room: Dict, equipments: List[str]) -> bool:
    """
    Check if the room has all the specified equipment.
    Uses normalized substring matching so 'projector' matches 'HD Projector'
    and 'video conferencing' matches 'Video-Conferencing'.
    """
    room_equipments = [_normalize(item) for item in room["equipments"]]
    for eq in equipments:
        requested = _normalize(eq)
        if requested in ("nothing", ""):
            continue
        if not any(requested in available or available in requested for available in room_equipments):
            return False
    return True

# @tool("load_rooms", description="Load existing room options from external file. ")
def load_rooms(filepath: Path = ROOMS_FILE) -> List[Dict]:
    """
    Load existing room options from external file. 
    """
    existing_data: List[Dict] = [{}]
    try:
        with open(filepath, "r") as f:
            existing_data = json.load(f)
    except json.JSONDecodeError:
        print(f"Warning: Could not decode existing JSON in {filepath}. Starting fresh.")
        existing_data = {}
    return existing_data


# @tool("find_matching_rooms", description="Find rooms that match the required capacity and equipment.")
def find_matching_rooms_tool(existing_rooms: List[Dict], capacity: int, equipments: List[str]) -> List[Dict]:
    """
    Find rooms that match the required capacity and equipment.
    """
    matching_rooms = []
    for room in existing_rooms:
        if room['capacity'] >= capacity and check_room_availability_equipment(room, equipments):
            matching_rooms.append(room)
    return matching_rooms

@tool("find_similar_rooms", description="Find rooms with similar equipment and capacity.")
def find_similar_rooms_tool(capacity: int, equipments: list, top_n: int = 3) -> List[Dict]:
    rooms = load_rooms()
    scored_rooms = []
    for room in rooms:
        if room['capacity'] >= capacity:
            overlap = len(set(room['equipments']) & set(equipments))
            scored_rooms.append((overlap, room))
    scored_rooms.sort(reverse=True, key=lambda x: x[0])
    return [room for overlap, room in scored_rooms if overlap > 0][:top_n]

@tool("find_rooms_by_equipments", description="Find rooms that have all the specified equipment.")
def find_rooms_by_equipments_tool(equipments: List[str]) -> List[Dict]:
    """Find rooms that have all specified equipment (fuzzy normalized match)."""
    rooms = load_rooms()
    matching_rooms = []
    for room in rooms:
        if check_room_availability_equipment(room, equipments):
            matching_rooms.append(room)
    return matching_rooms

@tool("find_rooms_by_capacity", description="Find rooms that have a capacity greater than or equal to the specified value.")
def find_rooms_by_capacity_tool(capacity: int) -> List[Dict]:
    rooms = load_rooms()
    matching_rooms = []
    for room in rooms:
        if room['capacity'] >= capacity:
            matching_rooms.append(room)
    return matching_rooms


def find_matching_rooms(
    start_date: str,
    start_time: str,
    duration_hours: float,
    capacity: int = 1,
    equipments: Optional[List[str]] = None,
) -> List[Dict]:
    """
    Search and filter available matching rooms based on capacity, equipment, and time conflicts.
    """
    from src.mock_apis.booking_services import load_bookings, check_time_conflict_tool
    from datetime import datetime

    rooms = load_rooms()
    equipments = equipments or []
    matching = find_matching_rooms_tool(rooms, capacity=capacity, equipments=equipments)
    if not matching:
        return []

    # Normalize time and check conflict
    try:
        # Try standard 12-hour format first
        time_str = start_time.strip()
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
        start_iso = start_dt.isoformat()

        existing_bookings = load_bookings()
        available = []
        for r in matching:
            if not check_time_conflict_tool(
                existing_bookings=existing_bookings,
                room_id=r["id"],
                start_time=start_iso,
                duration_hours=duration_hours,
            ):
                available.append(r)
        return available
    except Exception:
        return matching

