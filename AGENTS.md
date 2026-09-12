# AGENTS.md — rules for every agent working in this repo (Claude Code, Codex, Hermes)

## What we are building
An AI forensic auditor for the HackMTY 2026 Infosys "Forensic Auditor" track. Given a company's
books it must find invoice fraud, follow the money, and hand in a case file — and must NOT accuse
suppliers it cannot back with a rule broken, a peso amount, and record IDs. See docs/brief.md.

## Layout
- `data_estate/` — synthetic company generator, validator, scorer. Owner: Codex. Read data_estate/README.md first.
- `data_estate/out/company_42/` — FROZEN demo dataset. Never regenerate, never edit.
- `agent/` — the investigation agent: tools, loop, case-file writer. Owner: Claude Code.
- `demo/` — story, live-trace UI, demo script. Owner: human.
- `tests/` — pytest. CI runs `pytest -q` on every PR.

## Hard rules
1. Never push to `main`. All work goes through a PR. Humans merge.
2. Never read or copy anything under any `hidden/` directory into `agent/`. The agent must not see ground truth.
3. Every accusation in a case file must reference record IDs that exist in the dataset. `tests/test_case_file_contract.py` enforces this; do not weaken it.
4. Do not add heavy dependencies without an issue approving it. Stdlib + pandas + the LLM client is the baseline.
5. Do not change the dataset schema or the case-file contract (`data_estate/score.py` docstring). If a change is needed, open an issue labelled `needs-human` and stop.
6. One issue per branch. Branch name `hermes/<n>`, `cc/<n>`, or `codex/<n>`. PR title starts with `#<n>`.
7. Run `python -m pytest -q` before opening a PR. A PR with failing tests will be closed.

## Case-file contract (summary — full spec in data_estate/score.py)
findings[]: scheme_type, accused[ids], rule, amount_mxn, evidence[record ids]
not_pursued[]: entity, reason

## Scheme types
efos_fake_supplier · kickback_shell · round_trip_sales · duplicate_invoice_payment · other

## How to run things
python -m data_estate.generate --seed 42 --out data_estate/out/company_42
python -m data_estate.validate data_estate/out/company_42
python -m data_estate.score data_estate/out/company_42 case_file.json
python -m pytest -q
