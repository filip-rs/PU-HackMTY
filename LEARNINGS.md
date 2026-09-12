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
