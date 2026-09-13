# HackMTY 2026 — Data Formats and Judging Rules

**For participating teams, both tracks.**

This pack specifies the **formats** your project must produce and consume, and the rules judges score against. It is a specification, not a dataset.

## You build your own data

Neither track ships a ready-made environment, and that is deliberate — constructing it is part of the work.

- **Forensic Auditor:** you build the synthetic company. Write a generator, or adapt a dataset supplied with the problem statement.
- **Courier:** you build the shift simulator and its order stream. Same options.

What you get here is the schema your data must conform to, so that a judge can read it and so that your output is comparable with every other team's.

Budget the time. For both tracks this is a substantial fraction of the build, and it comes before any agent work.

---

## The four criteria

Both tracks are scored on the same four, equally weighted, **1–5 each, 20 total**.

| | Forensic Auditor | Courier |
|---|---|---|
| **Results** | On a fresh estate it has never seen, how much fraud does it catch while letting honest payments through? | On a fresh shift it has never seen, how much does it earn compared with a simple baseline? |
| **Judgment** | Does it refuse to accuse without evidence, and can it defend each call? | Does it make safe, sensible calls under surge and traffic, and explain them? |
| **Feasibility** | Would a real audit team trust and operate this? Cost, determinism, auditability. | Could this help a real courier in the few seconds they actually have? |
| **Clarity** | Is the money trail legible to a non-technical judge? | Is the decision trail followable? |

A 3 means "did the thing, no more." A 5 requires specific evidence, not a strong impression.

Results is one quarter of your score. The other three are where most teams leave points on the table.

---

## Rules that apply to both tracks

**Report on data you did not tune on.** Hold out seeds you never touch during development, and name both sets in your pitch.

> *Courier:* numbers from the seeds you tuned on cap **Results at 3**, regardless of the margin.
> *Forensic:* ground truth leaking into the agent's reasoning caps **Results at 2**, regardless of the numbers.

**Constraints live in code, not in prompts.** Both tracks require this explicitly. A judge will ask you to open the file where the constant is defined.

**Determinism.** The same seed produces the same output. Judges may run it twice.

**Every decision must be explainable from a log.** Judges ask "why did you skip that order" or "why didn't you flag vendor X" and expect an answer in under ten seconds, read from a record. Re-running your system to find out is the wrong answer even when the answer is right.

**Replay without a network.** Both tracks must be able to reproduce a completed run with connectivity disabled. This is also your insurance if the venue network fails during the demo.

**Have your cost numbers ready.** Model call count, MXN cost, wall-clock time. "We don't know" scores low on Feasibility.

---

## What is in here

```
student-materials/
├── courier/
│   ├── event_log_schema.json          simulator event format, all event types
│   ├── decision_response_schema.json  decision endpoint request/response contract
│   ├── evaluation_protocol.md         what judges will run
│   ├── event_log_example.jsonl        field shape only
│   ├── validate_format.py             format conformance check
│   └── results_table_template.csv
└── forensic-auditor/
    ├── estate_schema.sql              data estate tables and CFDI 4.0 field names
    ├── submission_schema.json         findings, declined leads, run metadata
    ├── ground_truth_schema.json       answer-key format for your own harness
    ├── case_file_structure.md         required sections of the case file
    ├── submission_example.json        field shape only
    ├── validate_format.py             format conformance check
    └── results_table_template.csv
```

Each track folder has its own README. **Read that next.**

```bash
cd courier          && python3 validate_format.py --event-log event_log_example.jsonl
cd forensic-auditor && python3 validate_format.py --submission submission_example.json
```

Both validators are stdlib-only Python 3 — no install step — and exit non-zero on a format error, so you can wire them into your build.

**They check format only.** Neither one tells you whether your results are correct. Measuring that is your job, against held-out data you generate.

## About the examples

Files named `*_example.*` show **field shape only**. Their values are placeholders and their text content is deliberately skeletal. They exist so you can test your serializer against the validator. They are not worked solutions and are not usable as data.

Do not infer distributions, thresholds, or strategy from placeholder values in examples. The judging data and control probes are different.

---

## Before you demo

- [ ] Both format checks exit 0
- [ ] Your results table is filled in from held-out data, with tuning and reporting sets named on the slide
- [ ] You can show a constraint firing, or a lead declined, live and from a log
- [ ] You have three numbers ready: model calls, MXN cost, wall-clock seconds
- [ ] Replay works with the network off — rehearse it
- [ ] You can name what you cut and why
