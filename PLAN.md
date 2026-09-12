# PLAN.md — HackMTY 2026 · Infosys "Forensic Auditor"

## Goal
An agent that, given a company's books and only the hint that something is wrong, finds the fraud,
follows the money, proves it with record IDs and a peso amount — and refuses to accuse anyone it
can't back up. Deliverable: working code + a 3-minute live demo where judges inject a fresh scheme.

## How we win (judging criteria → what we build)

| Criterion | What scores it |
|---|---|
| Results | Recall on unseen data. Detectors (#4–#11) produce leads; the loop (#13) confirms them. Measured by `data_estate/score.py`. |
| Judgment | Zero decoy accusations. The `not_pursued` list with reasons. Evidence guard (#14). Rehearsed answers to "why did you not accuse X?" |
| Feasibility | Case file a real auditor could act on: rule cited, amount, IDs. Runs on a local model, no cloud dependency at demo time. |
| Clarity | Money trail shown on screen as the agent traces it. Rodrigo's story frames it in 30 seconds. |

## Scope — fixed
- Four scheme types: `efos_fake_supplier`, `kickback_shell`, `round_trip_sales`, `duplicate_invoice_payment`. No more.
- Five decoys (see `data_estate/README.md`). The agent must clear all five.
- Dataset schema and case-file contract are frozen. Changes go through a `needs-human` issue.

## Team & ownership

| Who | Owns | Tooling |
|---|---|---|
| Sondre | `agent/` — tools, loop, evidence guard, case file | Claude Code |
| Filip | `data_estate/` — generator, validator, scorer, batch eval | Codex |
| Hermes (cluster, unattended) | `hermes-ok` issues: detectors, housekeeping | GitHub queue, cron every 30 min |
| Whoever is free | `demo/` — story, live-trace UI, script, rehearsal | — |

Humans merge. Agents propose. See `AGENTS.md`.

## Architecture

```
data_estate/out/<seed>/        CSVs the agent sees (hidden/ never mounted)
        │
agent/data.py                  load → pandas Dataset
        │
agent/detectors.py             cheap rules → leads (EFOS match, no receipt, duplicate pay,
        │                      employee address, CLABE mismatch, round trip, fast pay, round amounts)
        │
agent/investigate.py           for each lead: hypothesis → tool calls → accuse | drop (with reason)
        │   uses agent/tools.py  (query_ledger, get_invoices, get_bank_txns, trace_flow,
        │                         check_69b, get_receipts, get_employee)
        │   LLM: Ollama on cluster (14B), cached; Gemini free tier as fallback only
        │
agent/guard.py                 every evidence ID must exist; rule must be on allow-list
        │
case_file.json                 findings[] + not_pursued[]   → data_estate/score.py
        │
demo/                          live trace UI reads the agent's step log
```

## Timeline (36 h)

| Hours | Milestone | Done when |
|---|---|---|
| 0–1 | Repo skeleton, CI, dataset frozen, issues filed, Hermes running | CI green on `main`; Hermes has opened its first PR |
| 1–4 | Loader (#2), contract test (#3), tool layer (#12) | `pytest` green; tools return real rows from company_42 |
| 4–12 | Investigation loop (#13), detectors merged as Hermes delivers | `score.py` on company_42: recall ≥ 0.75, penalty 0 |
| 12–24 | Hardening: batch eval over 10 seeds, evidence guard (#14), drop-reasons quality | mean recall ≥ 0.8, penalty 0 on every seed |
| 24–30 | Demo UI + story + script; **feature freeze at h30** | Full 3-minute run-through under a timer |
| 30–36 | Rehearse only. Teammates inject unseen seeds and ask surprise questions | Three clean rehearsals in a row |

Overnight (h12–h24): Hermes works the queue. Morning: review its PRs first thing.

## Demo (3 minutes)

1. **0:00–0:30** Story. Rodrigo, a machine-shop owner in Monterrey, deducted invoices from three
   "consultants" a contact set him up with. Each looked fine alone. Two years later SAT listed them
   under 69-B and he was on the hook — treated as a participant, not a victim. His accountant never
   connected them. (Composite case, say so.)
2. **0:30–2:30** Live. Judges pick a seed and a scheme. Agent runs; trace on screen: lead → hypothesis
   → records pulled → money followed → accusation with rule + amount, or drop with reason. Make sure
   at least one decoy is visibly dropped.
3. **2:30–3:00** Surprise question. Likely ones, rehearse them:
   - "Why didn't you accuse [decoy]?" → point at the receipt / RFC / court case in the not_pursued list.
   - "The duplicate payment — is the supplier guilty?" → No. The payment is, the vendor is honest.
   - "What if the 69-B list was out of date?" → EFOS is one signal; the no-deliverable + fast-pay
     evidence stands without it.
   - "How much did you find and how sure are you?" → amount per finding, IDs on screen.

## Risks

| Risk | Mitigation |
|---|---|
| LLM rate limits / outage on demo day | Ollama local, response cache, Gemini only as fallback. Test the fallback once. |
| Agent hallucinates evidence | Guard (#14) rejects any ID not in the dataset before it reaches the case file. |
| Accuses a decoy on stage | Batch eval must show penalty 0 across ≥10 seeds before freeze. |
| Hermes PR breaks something | CI required; humans merge; Hermes can't touch `agent/` or the frozen dataset. |
| Demo runs long | Cap the agent at N tool calls per lead; pre-warm the model; rehearse with a timer. |
| Judges inject a scheme type we don't have | Say so honestly; show it lands in `not_pursued` or `other` with what was noticed. Never fake a finding. |

## Definition of done
- `python -m data_estate.generate --seed <any>` → `validate` passes → agent runs → `score.py` recall ≥ 0.8, penalty 0.
- Case file readable by a non-engineer.
- Demo rehearsed three times end to end.
