"""Validate that your courier output conforms to the required formats.

Checks FORMAT ONLY. It does not evaluate whether your decisions are correct
and contains no expected answers.

    # check an event log your simulator produced
    python3 validate_format.py --event-log my_shift.jsonl

    # check decision responses your endpoint returns
    python3 validate_format.py --responses my_responses.json

    # probe a live endpoint with a well-formed order and check the response shape
    python3 validate_format.py --endpoint http://localhost:8000/decide

Stdlib only. Exits non-zero if the format is invalid.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

LATENCY_BUDGET_MS = 50
MAX_REASON_WORDS = 40

VEHICLES = {"moto", "car", "bike"}
DECISIONS = {"ACCEPT", "SKIP"}
TIERS = {"tier1", "tier2"}
CONSTRAINTS = {"flagged_zone_night", "mandatory_break", "heat_rule",
               "shift_end_infeasible", "vehicle_capacity", "reservation_wage", None}

REQUIRED_BY_EVENT = {
    "shift_start":     ["event", "sim_time", "seed", "shift_hours", "vehicle",
                        "start_location_zone", "shift_end_time"],
    "order_offered":   ["event", "order_id", "sim_time", "zone_pickup", "zone_dropoff",
                        "distance_pickup_km", "distance_delivery_km", "base_pay_mxn",
                        "surge_multiplier", "vehicle"],
    "decision":        ["event", "order_id", "sim_time", "decision", "reason", "latency_ms"],
    "position_update": ["event", "sim_time", "zone", "status"],
    "earnings_update": ["event", "sim_time", "earnings_mxn", "orders_completed"],
    "shock":           ["event", "sim_time", "shock_type"],
    "strategy_update": ["event", "sim_time", "reservation_wage_mxn_hr"],
    "shift_end":       ["event", "sim_time"],
}

# A well-formed request used only to check response SHAPE. It is not a test
# case and has no expected answer.
PROBE = {
    "order_id": "FORMAT-PROBE-001",
    "platform": "rappi",
    "sim_time": "2026-03-21T18:42:00",
    "zone_pickup": 7,
    "zone_dropoff": 11,
    "distance_pickup_km": 1.4,
    "distance_delivery_km": 6.5,
    "base_pay_mxn": 58.0,
    "est_tip_mxn": 12.0,
    "surge_multiplier": 1.3,
    "restaurant_prep_min": 9,
    "weight_kg": 2.1,
    "volume_liters": 6.0,
    "vehicle": "moto",
}


def check_response(r: dict, label: str, measured_ms: float | None = None) -> list[str]:
    errs: list[str] = []
    for key in ("order_id", "decision", "reason", "latency_ms"):
        if key not in r:
            errs.append(f"{label}: missing required key {key!r}")

    if r.get("decision") not in DECISIONS:
        errs.append(f"{label}.decision must be ACCEPT or SKIP, got {r.get('decision')!r}")

    reason = str(r.get("reason", ""))
    if not reason.strip():
        errs.append(f"{label}.reason is empty")
    elif len(reason.split()) > MAX_REASON_WORDS:
        errs.append(f"{label}.reason is {len(reason.split())} words, "
                    f"maximum is {MAX_REASON_WORDS}")

    if "binding_constraint" in r and r["binding_constraint"] not in CONSTRAINTS:
        errs.append(f"{label}.binding_constraint must be one of "
                    f"{sorted(c for c in CONSTRAINTS if c)} or null, "
                    f"got {r['binding_constraint']!r}")

    if "tier" in r and r["tier"] not in TIERS:
        errs.append(f"{label}.tier must be tier1 or tier2, got {r['tier']!r}")

    lat = r.get("latency_ms", measured_ms)
    if lat is not None and not isinstance(lat, (int, float)):
        errs.append(f"{label}.latency_ms must be a number, got {lat!r}")
    elif isinstance(lat, (int, float)) and lat > LATENCY_BUDGET_MS:
        errs.append(f"{label}: latency {lat:.0f}ms exceeds the "
                    f"{LATENCY_BUDGET_MS}ms fast-path budget")
    return errs


def check_event_log(path: str) -> tuple[list[str], dict[str, int]]:
    errs: list[str] = []
    counts: dict[str, int] = {}
    for lineno, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError as e:
            errs.append(f"line {lineno}: not valid JSON ({e.msg}) - "
                        f"the event log must be JSON Lines, one object per line")
            continue
        name = ev.get("event")
        if name is None:
            errs.append(f"line {lineno}: missing 'event' key")
            continue
        counts[name] = counts.get(name, 0) + 1
        required = REQUIRED_BY_EVENT.get(name)
        if required is None:
            errs.append(f"line {lineno}: unknown event type {name!r}")
            continue
        for key in required:
            if key not in ev:
                errs.append(f"line {lineno} ({name}): missing required key {key!r}")
        if name in ("shift_start", "order_offered") and ev.get("vehicle") not in VEHICLES:
            errs.append(f"line {lineno} ({name}): vehicle must be one of "
                        f"{sorted(VEHICLES)}, got {ev.get('vehicle')!r}")
        if name == "decision":
            errs += check_response(ev, f"line {lineno} (decision)")

    if counts and "shift_start" not in counts:
        errs.append("event log has no shift_start event")
    if counts and "order_offered" not in counts:
        errs.append("event log has no order_offered events")
    return errs, counts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event-log")
    ap.add_argument("--responses")
    ap.add_argument("--endpoint")
    args = ap.parse_args()

    if not any([args.event_log, args.responses, args.endpoint]):
        ap.error("give at least one of --event-log, --responses, --endpoint")

    errs: list[str] = []

    print()
    print("=" * 70)
    print("  COURIER - FORMAT CHECK")
    print("=" * 70)

    if args.event_log:
        e, counts = check_event_log(args.event_log)
        errs += e
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none"
        print(f"  event log: {args.event_log}")
        print(f"  events: {summary}")

    if args.responses:
        raw = json.loads(Path(args.responses).read_text())
        items = raw if isinstance(raw, list) else list(raw.values())
        print(f"  responses: {len(items)} from {args.responses}")
        for i, r in enumerate(items):
            errs += check_response(r, f"responses[{i}]")

    if args.endpoint:
        print(f"  endpoint: {args.endpoint}")
        try:
            req = urllib.request.Request(
                args.endpoint, data=json.dumps(PROBE).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode())
            measured = (time.perf_counter() - t0) * 1000
            print(f"  round trip: {measured:.0f}ms")
            errs += check_response(body, "endpoint response", measured)
        except (urllib.error.URLError, TimeoutError) as e:
            errs.append(f"endpoint: could not reach {args.endpoint} ({e})")
        except json.JSONDecodeError:
            errs.append("endpoint: response body is not valid JSON")

    print("-" * 70)
    if errs:
        for e in errs:
            print(f"  FAIL  {e}")
        print("-" * 70)
        print(f"  {len(errs)} format error(s)")
    else:
        print("  PASS  output conforms to the required formats")

    print("""
  This checks FORMAT ONLY. It does not tell you whether your decisions are
  correct, and it does not measure earnings against a baseline.
""")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
