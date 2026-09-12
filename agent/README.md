# `agent/` — the investigation agent

Given a company's books, the agent finds the fraud, follows the money, and hands
in a case file. It never accuses anyone it cannot back with a rule broken, a
peso amount, and record IDs (`docs/brief.md`). This package is the backend; the
frontend (built separately, outside this repo) reads the step log and the API
server.

## Modules

| module | what it does |
|---|---|
| `data.py` | load a dataset directory into a typed `Dataset` (#2). Never opens `hidden/`. |
| `detectors/` | one module per detector; `detect_<name>(ds) -> list[dict]`, pure & deterministic. Auto-registered. |
| `leads.py` | aggregate detector output into ranked dossiers + `scheme_hint` (#44). |
| `tools.py` | read-only tool layer the LLM may call; every result carries record IDs (#12). |
| `llm.py` | OpenAI-compatible client (via `.env`), disk cache, retries, `FakeLLM` for tests (#22). |
| `config.py` | the `.env` settings loader (`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`) (#22). |
| `rules.py` | the rule catalog R1–R5 (legal strings) (#14). |
| `guard.py` | the evidence guard: contract, recognised rule, evidence belongs to accused, kinds, 25 % amount recompute (#14). |
| `contract.py` | case-file contract validation (`findings[]`, `not_pursued[]`) (#14). |
| `steplog.py` | the step-log contract as code: `KINDS`, `REQUIRED_PAYLOAD`, `parse_lines`, `validate_entries` (#67). |
| `investigate.py` | the loop: detectors → units → (`--no-llm` fallback or LLM loop) → case file + step log (#13). |
| `report.py` | human-readable case file: `render`, `exposure`, `money_trail` (#23). |

## CLI commands

All are run as `python -m agent.<module>`:

- `python -m agent.investigate <dataset_dir> [--out case_file.json] [--log runs/T.jsonl] [--max-leads 12] [--max-steps 12] [--no-llm]`
- `python -m agent.leads <dataset_dir> [--json] [--top N]`
- `python -m agent.steplog <log_file>` — validate a step log ("OK N entries").
- `python -m agent.report <dataset_dir> <case_file.json> [--out case_file.md] [--log runs/T.jsonl]`
- `python -m agent.guard <dataset_dir> <case_file.json>` and `python -m agent.contract <dataset_dir> <case_file.json>` for the guard / contract checks.

The LLM client is only reachable when `.env` is configured (see `.env.example`
and `scripts/check_llm.py`); without it the default path is the deterministic
`--no-llm` fallback.

## Two execution paths

1. **Deterministic (`--no-llm`, or no `.env`).** Turn the four known scheme
   signatures directly into findings through the same evidence guard. This is the
   stage-safe path and what CI exercises; it needs no LLM.
2. **LLM loop.** For each unit the model forms a hypothesis and calls the tool
   layer (#12) to prove it. Every `record_finding` goes through the guard (#14);
   a rejection is fed back so the model can fix and retry (up to `MAX_GUARD_RETRIES`,
   then a deterministic fallback for signature units) — so LLM and `--no-llm`
   agree on the four known schemes.

## Where outputs go

- The case file (JSON) at `--out` (default `case_file.json`).
- The step log (JSONL) at `--log` (default `runs/<UTC ts>.jsonl`), streamed and
  flushed per event. See [`docs/STEP_LOG.md`](../docs/STEP_LOG.md) for the full
  contract and how to tail it.
- The human-readable report at `--out` of `agent.report`.

The case-file contract (`findings[]`, `not_pursued[]`, scheme types) is defined
in `data_estate/score.py`; `agent/contract.py` enforces it.
