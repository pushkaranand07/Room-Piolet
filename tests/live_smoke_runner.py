"""
Runner for Phase 3 Live Smoke Tests.
"""
import requests
import json
import os
import sys

BASE_URL = "http://127.0.0.1:5001/api/booking"

def print_turn(step_title, resp):
    print(f"\n--- {step_title} ---")
    print(f"Status Code: {resp.status_code}")
    try:
        data = resp.json()
        print("JSON Response:")
        print(json.dumps(data, indent=2))
        return data
    except Exception as e:
        print(f"Failed to parse JSON: {resp.text}")
        return None

def run_scenarios_a_to_d():
    print("==================================================")
    print("SCENARIO A: Cancel Flow")
    print("==================================================")
    s_a = requests.Session()

    # Step 1: Search
    r1 = s_a.post(BASE_URL, json={"message": "find me a room tomorrow at 2pm for 2 people"})
    d1 = print_turn("Scenario A - Turn 1: Search", r1)
    rooms = (d1.get("ui") or {}).get("rooms", [])
    if not rooms:
        print("ERROR: No rooms returned in Turn 1!")
        return

    first_room_name = rooms[0]["name"]
    print(f">> Selecting room: {first_room_name}")

    # Step 2: Select room
    r2 = s_a.post(BASE_URL, json={"message": first_room_name})
    d2 = print_turn("Scenario A - Turn 2: Select room", r2)

    # Step 3: Provide name (if needed)
    if d2.get("phase") == "collecting":
        r3 = s_a.post(BASE_URL, json={"message": "Alex"})
        d3 = print_turn("Scenario A - Turn 3: Provide name", r3)
    else:
        d3 = d2

    # Step 4: Confirm booking
    r4 = s_a.post(BASE_URL, json={"message": "yes"})
    d4 = print_turn("Scenario A - Turn 4: Confirm booking", r4)
    booking_id = ((d4.get("ui") or {}).get("booking") or {}).get("booking_id")
    print(f">> Created Booking ID: {booking_id}")

    # Step 5: Cancel booking
    r5 = s_a.post(BASE_URL, json={"message": "cancel my booking"})
    d5 = print_turn("Scenario A - Turn 5: Cancel request", r5)

    # Step 6: Provide ID or confirm if asked
    last_msg = ""
    msgs = d5.get("messages", [])
    if msgs:
        last_msg = msgs[-1].get("content", "").lower()
    
    if "id" in last_msg or "which" in last_msg or "booking" in last_msg or d5.get("phase") != "cancelled":
        if booking_id:
            r6 = s_a.post(BASE_URL, json={"message": f"Please cancel {booking_id}"})
            d6 = print_turn(f"Scenario A - Turn 6: Provide booking ID {booking_id}", r6)
            # If confirmation requested:
            if "confirm" in (d6.get("messages", [])[-1].get("content", "").lower() if d6.get("messages") else ""):
                r7 = s_a.post(BASE_URL, json={"message": "yes"})
                print_turn("Scenario A - Turn 7: Confirm cancellation", r7)

    print("\n==================================================")
    print("SCENARIO B: List Flow (Same session)")
    print("==================================================")
    rb = s_a.post(BASE_URL, json={"message": "show my bookings"})
    db = print_turn("Scenario B - Turn 1: Show my bookings", rb)

    print("\n==================================================")
    print("SCENARIO C: Safety Gate (Critical)")
    print("==================================================")
    s_c = requests.Session()
    rc = s_c.post(BASE_URL, json={"message": "just book me a room tomorrow at 3pm"})
    dc = print_turn("Scenario C - Turn 1: Unconfirmed booking attempt", rc)
    assert dc.get("phase") != "booked", "FAILED: Bot booked room without user confirmation!"
    print(">> Safety Gate PASSED: phase is not 'booked' (phase=%s)" % dc.get("phase"))

    print("\n==================================================")
    print("SCENARIO D: Unknown Intent Fallback")
    print("==================================================")
    s_d = requests.Session()
    rd = s_d.post(BASE_URL, json={"message": "who are you and what can you do?"})
    dd = print_turn("Scenario D - Turn 1: Unknown intent", rd)
    print(">> Unknown Intent PASSED: response received, phase=%s" % dd.get("phase"))

if __name__ == "__main__":
    run_scenarios_a_to_d()
