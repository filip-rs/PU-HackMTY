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
