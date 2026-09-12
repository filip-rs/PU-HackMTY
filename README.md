# PU-HackMTY — The Forensic Auditor

HackMTY 2026, Infosys track 2. An AI agent that takes a company's books plus the hint "something is wrong",
follows the money, and hands in a case file: scheme, accused entities, rule broken, peso amount, evidence record
IDs, and the leads it declined to pursue and why.

Start here: [`AGENTS.md`](AGENTS.md) (rules, binding for humans and agents) → [`docs/brief.md`](docs/brief.md)
(what the judges asked) → [`docs/PLAN.md`](docs/PLAN.md) (who does what, when) → [`docs/STRATEGY.md`](docs/STRATEGY.md).

## Layout
| Path | What | Owner |
|---|---|---|
| `data_estate/` | Synthetic Monterrey company: generator, validator, scorer (stdlib only) | Filip / Codex |
| `data_estate/out/company_42/` | Frozen demo dataset. Never regenerate. Checksum-tested. | — |
| `agent/` | Loader, detectors, tools, investigation loop, evidence guard, case-file writer | Sondre / Claude Code |
| `demo/` | Story, live-trace UI, demo script | whoever is free |
| `tests/` | pytest; CI runs it on every push and PR | everyone |
| `docs/` | Brief, strategy, plan, issue-queue mirror, Hermes brief, transcript, PDF | — |
| `scripts/` | One-off checks (`check_llm.py`) | — |

## Setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install pytest pandas
cp .env.example .env          # fill in the HPC endpoint, key, and model
python scripts/check_llm.py   # round-trips one prompt through the endpoint
python -m pytest -q
```

## Everyday commands
```bash
python -m data_estate.generate --seed 7 --out data_estate/out/company_7   # fresh dataset; company_42 is frozen
python -m data_estate.validate data_estate/out/company_7
python -m data_estate.score data_estate/out/company_42 case_file.json
```

## How work flows
GitHub issues are the queue (`docs/ISSUES.md` is the mirror). Labels: `hermes-ok` the unattended Hermes agent
may take it · `cc` Claude Code · `codex` Codex · `needs-human` a person decides. One issue per branch
(`hermes/<n>`, `cc/<n>`, `codex/<n>`), PR title starts with `#<n>`, CI must be green, humans merge.

The LLM runs on a teammate's HPC cluster approved for sensitive data. Dataset contents never go to any other
provider (AGENTS.md rule 8).

## Learnings
The judges asked for failures and learnings. `LEARNINGS.md` gets an entry whenever something breaks, changes, or surprises us.
