# AGENTS.md — rules for every agent working in this repo (Claude Code, Codex, Hermes)

## What we are building
An AI forensic auditor for the HackMTY 2026 Infosys "Forensic Auditor" track. Given a company's
books it must find invoice fraud, follow the money, and hand in a case file — and must NOT accuse
suppliers it cannot back with a rule broken, a peso amount, and record IDs. See docs/brief.md.

## Layout
- `data_estate/` — synthetic company generator, validator, scorer (stdlib only). Owner: Codex. Read data_estate/README.md first.
- `data_estate/out/company_42/` — FROZEN demo dataset. Never regenerate, never edit. `tests/test_frozen_dataset.py` enforces this.
- `agent/` — the investigation agent: loader, detectors, tools, loop, evidence guard, case-file writer. Owner: Claude Code.
  `agent/detectors/` holds one module per detector (`<name>.py` → `detect_<name>(ds)`), auto-registered by its `__init__.py`; never edit another detector's module.
- `tests/conftest.py` — fixtures `ds` (company_42 loaded), `truth`, `scheme(type)`, `decoy_ids`. Tests may read `hidden/`; `agent/` may not.
- `demo/` — story, live-trace UI, demo script. Owner: human.
- `tests/` — pytest, one file per module (`tests/test_detect_<name>.py` for detectors). CI runs `pytest -q` on every push and PR.
- `docs/` — brief, strategy, plan, issue queue mirror, Hermes brief. `scripts/` — one-off checks such as `check_llm.py`.

## Hard rules
1. Never push to `master`. All work goes through a PR. Humans merge.
2. Never read or copy anything under any `hidden/` directory into `agent/`. The agent must not see ground truth. Tests may read it.
3. Every accusation in a case file must reference record IDs that exist in the dataset. `tests/test_case_file_contract.py` enforces this; do not weaken it.
4. Do not add heavy dependencies without an issue approving it. Stdlib + pandas + the LLM client is the baseline.
5. Do not change the dataset schema or the case-file contract (`data_estate/score.py` docstring). If a change is needed, open an issue labelled `needs-human` and stop.
6. One issue per branch. Branch name `hermes/<n>`, `cc/<n>`, or `codex/<n>`. PR title starts with `#<n>`.
7. Run `python -m pytest -q` before opening a PR. A PR with failing tests will be closed.
8. All LLM calls go to the OpenAI-compatible endpoint configured in `.env` (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`):
   an open-weight model on a teammate's HPC cluster that is approved for sensitive data. Never send dataset rows,
   IDs, RFCs, or CLABEs to any other provider, and never fall back to a hosted API for anything that carries data.
   Never commit `.env`. `.env.example` lists the variables; `python scripts/check_llm.py` verifies the endpoint.

## LLM access
Copy `.env.example` to `.env` and fill it in. Read the variables with `os.environ` or the small loader in
`scripts/check_llm.py`; do not add python-dotenv. Do not hard-code model names or URLs anywhere.

## Case-file contract (summary — full spec in data_estate/score.py)
findings[]: scheme_type, accused[ids], rule, amount_mxn, evidence[record ids]
not_pursued[]: entity, reason

## Scheme types
efos_fake_supplier · kickback_shell · round_trip_sales · duplicate_invoice_payment · other

## How to run things
python -m venv .venv && . .venv/bin/activate && pip install pytest pandas
python -m data_estate.generate --seed 7 --out data_estate/out/company_7     # never write to company_42
python -m data_estate.validate data_estate/out/company_42
python -m data_estate.score data_estate/out/company_42 data_estate/out/example_case_file_for_seed42.json
python -m pytest -q
python scripts/check_llm.py
