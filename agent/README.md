# agent/

Owner: Sondre / Claude Code. Filled in by issues #2 (loader), #4–#11 (detectors), #12 (tools), #13 (loop), #14 (evidence guard).

Planned modules: `data.py` (load a dataset dir into pandas), `detectors.py` (pure functions → leads),
`tools.py` (functions the LLM may call; every result carries record IDs), `investigate.py` (lead →
hypothesis → tool calls → accuse | drop), `guard.py` (every evidence ID must exist, rule from allow-list).

The LLM is reached only through the endpoint in `.env` (see `.env.example`, AGENTS.md rule 8).
