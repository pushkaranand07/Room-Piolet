"""
Manual smoke test: 4-turn booking flow against live Flask server.
Run with: python tests/smoke_test.py
Server must already be running on localhost:5001.
"""
import requests
import json
import sys

BASE = "http://localhost:5001/api/booking"
s = requests.Session()


def post(msg):
    r = s.post(BASE, json={"user_input": msg})
    if not r.ok:
        print(f"  HTTP {r.status_code}: {r.text}")
        sys.exit(1)
    d = r.json()
    print(f"  phase={d.get('phase')}")
    for m in d.get("messages", []):
        label = m["type"].upper()
        content = m["content"][:200].replace("\n", " | ").encode("ascii", "replace").decode("ascii")
        print(f"  [{label}]: {content}")
    ui = d.get("ui") or {}
    if ui:
        print(f"  ui.type={ui.get('type')}")
    print()
    return d


def run_smoke_test():
    print("=" * 60)
    print("SMOKE TEST: 4-turn booking flow")
    print("=" * 60)

    # Turn 1: search (already done — this is a fresh session so we redo it)
    print("--- Turn 1: Search ---")
    r1 = post("I need a room tomorrow at 2pm for 2 hours")
    assert r1.get("phase") == "presenting", f"Expected 'presenting', got {r1.get('phase')}"
    assert len(r1.get("ui", {}).get("rooms", [])) > 0, "No rooms returned"
    first_room = r1["ui"]["rooms"][0]["name"]
    print(f"  [picked room: {first_room}]")

    # Turn 2: select
    print(f"--- Turn 2: Select '{first_room}' ---")
    r2 = post(first_room)
    assert r2.get("phase") in ("collecting", "confirming"), f"Unexpected phase: {r2.get('phase')}"

    # Turn 3: provide name (only if collecting)
    if r2.get("phase") == "collecting":
        print("--- Turn 3: Provide name 'Alex' ---")
        r3 = post("Alex")
        assert r3.get("phase") == "confirming", f"Expected 'confirming', got {r3.get('phase')}"
    else:
        r3 = r2
        print("--- Turn 3: (skipped — name already known) ---")

    # Turn 4: confirm
    print("--- Turn 4: Confirm 'yes' ---")
    r4 = post("yes")
    assert r4.get("phase") == "booked", f"Expected 'booked', got {r4.get('phase')}"
    assert (r4.get("ui") or {}).get("type") == "booking_receipt", "No booking receipt"
    booking_id = r4["ui"]["booking"].get("booking_id", "???")

    print("=" * 60)
    print(f"[SMOKE TEST PASSED] booking_id: {booking_id}")
    print("=" * 60)


if __name__ == "__main__":
    run_smoke_test()
