"""LLM endpoint configuration (#22).

One place that decides *where* the model lives, so the investigation loop (#13) only
cares about leads and evidence and never builds an HTTP client. Reads plain
``KEY=VALUE`` lines from ``.env``; real environment variables win over the file.
No python-dotenv (AGENTS.md rule 4).

The body of :func:`load_env` was moved here from ``scripts/check_llm.py`` so the
script and anything else that needs the settings share a single reader.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")


def load_env(path: Path = ROOT / ".env") -> dict[str, str]:
    """Read ``.env``: ``KEY=VALUE`` lines, ``#`` comments, optional quotes.

    Real environment variables win over the file (so an operator can override the
    endpoint per-run without touching `.env`).
    """
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    env.update({k: os.environ[k] for k in KEYS if os.environ.get(k)})
    return env


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str
    model: str


def settings(path: Path = ROOT / ".env") -> Settings | None:
    """Return :class:`Settings` when every key is present and non-empty, else ``None``.

    ``None`` is the CI signal (there is no ``.env`` on CI) that the caller should
    fall back to the deterministic offline path rather than attempt a network call.
    """
    env = load_env(path)
    if any(not env.get(k) for k in KEYS):
        return None
    return Settings(base_url=env["LLM_BASE_URL"], api_key=env["LLM_API_KEY"], model=env["LLM_MODEL"])
