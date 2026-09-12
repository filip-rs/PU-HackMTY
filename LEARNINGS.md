# LEARNINGS.md — what we tried, what happened, what we changed

The judges said they are as interested in failures as in successes. Every entry: timestamp, tried, happened,
changed. Five minutes every four hours. One person owns it.

## 2026-09-11 23:40 · Repo structured for three agents at once
Tried: run Claude Code, Codex, and an unattended Hermes agent against one repo from hour zero, coordinated only
by GitHub issues and AGENTS.md.
Happened: the planning docs assumed a `main` branch; the repo's default is `master`. Nobody on the team has
admin on the repo, so branch protection has to come from the owner.
Changed: docs say `master`; dataset unpacked to `data_estate/`, CI to `.github/workflows/`; `company_42` frozen
behind a checksum test; the issue queue filed as GitHub issues #1–#18 with `hermes-ok` / `cc` / `needs-human` labels.
Also learned: the generator is deterministic. `--seed 42` reproduces `company_42` byte-for-byte on Python 3.14, so the
checksum test guards against edits and schema drift, not against honest regeneration.

## 2026-09-11 23:40 · All inference on the HPC cluster
Tried: the original plan had Ollama locally with the Gemini free tier as fallback.
Happened: a teammate has open-weight models on an HPC cluster approved for sensitive data, reachable through an
OpenAI-compatible endpoint.
Changed: that endpoint is the only place dataset contents may go (AGENTS.md rule 8). Endpoint and key live in
`.env`; `scripts/check_llm.py` checks reachability so an outage is found before the demo, not during it.

## 2026-09-12 00:40 · Two of eight detector specs were impossible as written
Tried: file the detector issues for the unattended agent straight from the one-line queue in the plan.
Happened: checked every threshold against company_42 in pandas first. "Goods invoices with no receipt" returns
zero rows (every goods invoice has a receipt by construction). The round-trip rule "inbound ≥ 90% of the forward
within 10 days" finds none of the three planted chains: the return leg is a sales invoice issued net of IVA, so the
money that comes back is 0.98 / 1.16 ≈ 0.86 of what was forwarded. "Round thousands" only works on `subtotal`;
on `total` (with 16% IVA) the kickback shell scores 0.0. The 7-day fast-pay window is exact on this seed but
business-day rolling can push it to 9 on others.
Changed: no-receipt detector broadened (every purchase without a receipt, with a `receipt_required` flag), round-trip
return threshold 0.80, round-amount test on `subtotal`, fast-pay window 10 days. Every issue now states the exact
expected hits on company_42 and the test that proves them. Rule for the rest of the hackathon: a spec for an
unattended agent must name the number it should find, or it is not a spec.

## 2026-09-12 19:00 · LLM mode lost findings the deterministic path kept
Tried: the same investigation loop with the cluster model (GLM-5.3-Flash) on company_42, seven runs, against the
`--no-llm` path on the same data.
Happened: `--no-llm` scored 4/4 every time; LLM mode scored 1/4, 1/4, 3/4, 3/4, 3/4, 4/4, 4/4. Two causes, both visible
in `runs/*.jsonl`: (1) `record_finding` arguments arrived truncated (`scheme_type` and `rule` missing) because the
completion budget was too small for a reasoning model that spends tokens before the tool call; (2) the model cites
ledger entry IDs (`GL*`) it saw through `query_ledger` as evidence, the contract only accepts invoice/TX/CP/GR IDs,
and a rejected finding ended the lead instead of retrying. Precision was perfect in every run: no decoy accused.
Changed: `max_tokens` raised to 8192 (PR #64). Filed #65 (the guard sets ledger IDs aside instead of rejecting) and
#66 (guard reasons go back to the model for a retry; when it still fails, the deterministic finding stands in and the
trace says where it came from). Rule for the loop: the guard's job is to reject, the loop's job is to recover. A
rejection must never end a lead that the deterministic path can prove.

## 2026-09-12 19:00 · The step log could not be tailed
Tried: point a live UI at the JSONL step log while the agent ran.
Happened: the file is written in one go after `run_end`, so a viewer sees nothing until the run is over. The UI is
now being built outside this repo, which made the missing contract obvious: the only spec was a docstring.
Changed: #67 streams and flushes each line as it is emitted and writes the contract down (`docs/STEP_LOG.md`) with a
validator that fails the build when the writer drifts; #68 exposes the same lines over HTTP as server-sent events.
`demo/sample_trace.jsonl` is a real 4/4 LLM run to build against in the meantime. Also learned: the Hermes brief said
the agent may not touch `agent/`, yet it delivered the tool layer, the guard, the loop and the report without incident.
The brief now says it may work anywhere except the frozen dataset and three protected tests, and merges its own PRs
once CI is green.
