# Courier — Evaluation Protocol

What judges will run against your system, and the shape of the inputs. No expected answers are given here: you are told **what is tested**, not what the right answer is for a given payload.

---

## 1. Shift configuration

Your system must run a full shift from a configuration of this shape, supplied at run time:

```json
{
  "seed": 1234,
  "shift_hours": 8.0,
  "vehicle": "moto",
  "start_location_zone": 7
}
```

A seed must produce a **byte-identical order stream** every time. This is required for fair comparison and for reproducible demos.

Judges will run a mix of published and unpublished configurations that vary seed, shift length, vehicle, start zone and disruption timing. Build for the general case rather than any fixed list.

Use disjoint seed sets for tuning and reporting. Your reported numbers must come from seeds you did not tune on.

Your simulator must handle all three vehicle types — `moto`, `car`, `bike` — with distinct speed profiles and distinct weight and volume limits.

---

## 2. Order pings

Judges POST orders matching `order_offered` in `event_log_schema.json` to your decision endpoint, and read the response defined in `decision_response_schema.json`.

Some requests carry `courier_state_overrides` to establish a specific courier state before the ping — accumulated riding time, elapsed shift hours, an in-flight order, a shift end time. Your system must apply these rather than ignoring them.

**Latency budget: 50 ms** for the fast path.

---

## 3. Decision categories

Judges probe these categories. Each is a situation where a pay-only rule is insufficient. You are told the categories, not the payloads, thresholds or expected answers.

| Category | What is under test |
|---|---|
| **Dropoff location value** | Decisions that must account for where the courier ends up next, not just current-order pay. |
| **Threshold consistency** | Clear, reproducible handling near acceptance boundaries and tie cases. |
| **Safety-over-pay invariance** | Safety refusals must remain refusals even when pay conditions improve. |
| **Stacking and route feasibility** | Decisions with in-flight work must account for the combined route and timing. |
| **End-of-shift feasibility** | Acceptance policy near shift end must preserve on-time completion. |
| **Vehicle capacity compliance** | Weight and volume constraints must match the assigned vehicle profile. |
| **Continuous-riding safeguards** | Mandatory break and heat constraints must affect acceptance behavior when active. |

For each probe, judges record the decision **and** the `reason` string. A correct decision with a reason that names the wrong constraint — or a generic one — does not earn the Judgment credit.

---

## 4. Safety constraints

These must be enforced **in code**, not as instructions in a model prompt. Judges will ask you to open the file where each limit is defined.

1. No dropoff in flagged zones after 22:00
2. Mandatory 20-minute break after 4 continuous hours
3. Heat rule: continuous riding capped at 90 minutes during 12:00–16:00
4. Refuse orders that cannot be completed before shift end
5. Weight and volume limits per vehicle type

Each constraint is probed under boundary and stress conditions, including cases where pay signals conflict with safety policy.

A constraint that exists in code but is never demonstrated triggering during your demo scores low. Rehearse at least two as live demo moments.

---

## 5. Mid-shift disruption

At least one shock during the demo is required by the brief. Judges may inject shocks live, using the `shock` event format in `event_log_schema.json`: `surge`, `closure`, `rain`, `delay`.

Your system must react without stalling the decision loop.

---

## 6. Replay determinism

Judges may ask you to record a complete shift to an event log, replay that log against your running system, and diff the decisions.

**Requirement:** identical fast-path accept/skip decisions on identical input. Strategy-layer parameters may vary slightly from model non-determinism, provided no fast-path decision changes as a result.

A mismatch indicates hidden mutable state, a wall-clock dependency, or a race between layers. You will be asked to identify which.

---

## 7. Model failure

Judges may disable your model connection mid-shift — typically by invalidating the API credential in the process environment — then restore it.

**Requirement:** the fast path continues deciding autonomously on the last known strategy, still within the latency budget. The system **signals** that it is degraded, through its response, logs or a status endpoint. No order is held or queued waiting for the model. The strategy layer recovers when connectivity returns.

A silent fallback is partial credit. A crash, a stall, or queued decisions is a hard failure on Feasibility.

Rehearse this with the network off.

---

## 8. Results reporting

Fill in `results_table_template.csv` and put it on one slide.

- At least 10 held-out shifts
- Compare against named baselines, not against nothing
- **Tuning seeds and reporting seeds must be disjoint, and you must say which is which**
- Safety violations must be zero

If your reported numbers come from the seeds you tuned on, **Results caps at 3** regardless of the margin.
