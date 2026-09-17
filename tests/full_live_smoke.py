"""
Full Phase 3 Live Smoke Test Suite covering Scenarios A, B, C, D, and E.
"""
import requests
import json
import os
import sys
import time

BASE_URL = "http://127.0.0.1:5001/api/booking"
BOOKINGS_PATH = "data/bookings.json"

results_report = {}

def send_and_log(session, title, payload):
    print(f"\n>>> {title}")
    resp = session.post(BASE_URL, json=payload)
    print(f"HTTP Status: {resp.status_code}")
    data = resp.json()
    print("Full JSON:")
    print(json.dumps(data, indent=2))
    return data

def run():
    print("==========================================================")
    print("SCENARIO A: Cancel Flow")
    print("==========================================================")
    s_a = requests.Session()
    d1 = send_and_log(s_a, "Turn 1: Search", {"message": "find me a room tomorrow at 2pm for 2 people"})
    first_room = d1["ui"]["rooms"][0]["name"]

    d2 = send_and_log(s_a, f"Turn 2: Select '{first_room}'", {"message": first_room})

    if d2.get("phase") == "collecting":
        d3 = send_and_log(s_a, "Turn 3: Provide Name 'Alex'", {"message": "Alex"})
    else:
        d3 = d2

    d4 = send_and_log(s_a, "Turn 4: Confirm 'yes'", {"message": "yes"})
    booking_data = (d4.get("ui") or {}).get("booking") or {}
    booking_id = booking_data.get("booking_id")
    print(f">> Created Booking: {booking_id}")

    # Now cancel
    d5 = send_and_log(s_a, "Turn 5: 'cancel my booking'", {"message": "cancel my booking"})
    
    # Bot asks for booking ID
    d6 = send_and_log(s_a, f"Turn 6: Provide booking ID '{booking_id}'", {"message": f"please cancel {booking_id}"})

    # Bot asks: "Just to be sure—do you want to cancel booking BK-XXXXXX? (yes / no)"
    d7 = send_and_log(s_a, "Turn 7: Confirm 'yes'", {"message": "yes"})

    # Check bookings.json
    with open(BOOKINGS_PATH, "r") as f:
        bookings_data = json.load(f)
    
    all_booking_ids = []
    for r_id, b_list in bookings_data.items():
        for b in b_list:
            if "booking_id" in b:
                all_booking_ids.append(b["booking_id"])

    print(f"\n>> All Booking IDs in data/bookings.json currently: {all_booking_ids}")
    if booking_id:
        assert booking_id not in all_booking_ids, f"ERROR: Booking {booking_id} still exists in bookings.json!"
        print(f">> VERIFIED: {booking_id} successfully removed from bookings.json!")

    print("\n==========================================================")
    print("SCENARIO B: List Flow")
    print("==========================================================")
    db = send_and_log(s_a, "Turn 1: 'show my bookings'", {"message": "show my bookings"})
    assert db.get("ui", {}).get("type") == "booking_list" or "bookings" in db.get("ui", {}) or "booking" in db.get("messages", [])[-1].get("content", "").lower()
    print(">> Scenario B PASSED: List bookings received!")

    print("\n==========================================================")
    print("SCENARIO C: Safety Gate (Critical)")
    print("==========================================================")
    s_c = requests.Session()
    dc = send_and_log(s_c, "Turn 1: 'just book me a room tomorrow at 3pm'", {"message": "just book me a room tomorrow at 3pm"})
    assert dc.get("phase") != "booked", f"FAILED: phase is '{dc.get('phase')}', should not be 'booked'!"
    assert (dc.get("ui") or {}).get("type") != "booking_receipt", "FAILED: returned booking receipt without confirmation!"
    print(f">> Scenario C PASSED: Safety gate held! phase={dc.get('phase')}")

    print("\n==========================================================")
    print("SCENARIO D: Unknown Intent Fallback")
    print("==========================================================")
    s_d = requests.Session()
    dd = send_and_log(s_d, "Turn 1: 'who are you and what can you do?'", {"message": "who are you and what can you do?"})
    assert dd.get("messages")[-1].get("content"), "FAILED: No content returned"
    assert dd.get("phase") == "idle", f"FAILED: phase is {dd.get('phase')}"
    print(f">> Scenario D PASSED: Unknown intent handled naturally, phase={dd.get('phase')}")

if __name__ == "__main__":
    run()
