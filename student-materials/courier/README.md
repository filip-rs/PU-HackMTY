# Courier — Data Formats and Judging Rules

This folder specifies the **formats** your project must produce and consume, and the protocol judges will run. It contains no dataset.

**You build your own simulator and order stream.** Write a generator, or adapt a dataset supplied with the problem statement. The formats below are the contract; the data is yours.

## Files

| File | What it specifies |
|---|---|
| `event_log_schema.json` | The simulator event format — every event type, its required fields, and illustrative examples |
| `decision_response_schema.json` | The request and response contract for your decision endpoint, plus `explain_decision` |
| `evaluation_protocol.md` | What judges will run: shift configurations, probe categories, safety constraints, replay and failure checks |
| `event_log_example.jsonl` | Field shape only — one of each event type, with placeholder values |
| `validate_format.py` | Checks your output conforms. Format only; no test cases, no expected answers. |
| `results_table_template.csv` | The Results table shape |

## Using the validator

```bash
# an event log your simulator produced
python3 validate_format.py --event-log my_shift.jsonl

# decision responses your endpoint returned
python3 validate_format.py --responses my_responses.json

# probe a running endpoint and check the response shape
python3 validate_format.py --endpoint http://localhost:8000/decide
```

Exits non-zero on a format error. Wire it into your build.

It checks format only. It does not tell you whether your decisions are correct and does not measure earnings.

## Read `evaluation_protocol.md` next

It lists representative evaluation conditions, the decision categories judges probe, the five safety constraints, and the replay/model-failure checks — without giving exact hidden test payloads or expected answers.

## Rules that decide your score

**Decisions must be deterministic per seed.** A seed must produce a byte-identical order stream every time, and identical fast-path decisions on identical input. Judges may record a shift, replay it, and diff the decisions.

**The fast path has a 50 ms budget.** A courier has roughly 5 seconds to decide in the real app. Any code path that calls a model inside the decision window fails Feasibility.

**Safety constraints must be enforced in code.** Not as instructions in a model prompt. Judges will ask you to open the file where each limit is defined. A constraint that exists but is never demonstrated triggering scores low — rehearse at least two as live demo moments.

**Every decision carries a reason under 40 words** that names the constraint that actually bound. Set `binding_constraint` so a safety refusal is machine-distinguishable from pay criteria. A correct decision with a generic or wrong reason does not earn the Judgment credit.

**Report on seeds you did not tune on.** Name both sets in the pitch. If your numbers come from the seeds you tuned on, **Results caps at 3** regardless of the margin.

**Compare against named baselines.** A single number with nothing beside it is not a result.

**Handle model failure.** When the model is unreachable the fast path keeps deciding on the last known strategy, within budget, and signals that it is degraded. A silent fallback is partial credit; a stall or crash is a hard failure.

**Three vehicle types.** `moto`, `car` and `bike`, with distinct speed profiles and distinct weight and volume limits.

## Questions judges ask

- "What happens if I change this input?"
- "Why should I trust this number?"
- "What does it do when it's wrong?"
- "Could a real courier use this tomorrow?"
- "What did you cut, and why?"
- "Why did you skip that order?"
- "What would it do if a surge hit right now?"
- "What if this order's restaurant is running 15 minutes late?"

Answering from a decision log in under ten seconds is itself scored. Re-deriving the answer live is the wrong answer even when it turns out to be right.
