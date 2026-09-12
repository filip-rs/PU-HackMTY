#!/usr/bin/env python3
"""Round-trip one prompt through the LLM endpoint configured in .env. Stdlib only.

  python scripts/check_llm.py            # uses .env in the repo root
  python scripts/check_llm.py --models   # also list the models the endpoint serves

Exit 0 on success, 1 otherwise. Run it from the venue before the demo.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")


def load_env(path: Path = ROOT / ".env") -> dict[str, str]:
    """Minimal .env reader (KEY=VALUE, # comments, optional quotes). Real env vars win over the file."""
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


def request(env: dict[str, str], path: str, payload: dict | None = None, timeout: float = 60) -> dict:
    url = env["LLM_BASE_URL"].rstrip("/") + path
    headers = {"Authorization": f"Bearer {env.get('LLM_API_KEY', '')}", "Content-Type": "application/json"}
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", action="store_true", help="list models served by the endpoint")
    args = ap.parse_args()
    env = load_env()
    missing = [k for k in KEYS if not env.get(k)]
    if missing:
        print(f"missing in .env: {', '.join(missing)}  (cp .env.example .env and fill it in)")
        return 1
    try:
        if args.models:
            ms = request(env, "/models")
            print("models:", ", ".join(m["id"] for m in ms.get("data", [])) or ms)
        t0 = time.time()
        res = request(env, "/chat/completions", {
            "model": env["LLM_MODEL"],
            "messages": [{"role": "user", "content": "Reply with the single word OK."}],
            "max_tokens": 8,
            "temperature": 0,
        })
        text = res["choices"][0]["message"]["content"].strip()
        print(f"OK  {env['LLM_MODEL']} @ {env['LLM_BASE_URL']}  {time.time() - t0:.1f}s  reply={text!r}")
        return 0
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} from {e.url}: {e.read()[:300]!r}")
    except Exception as e:  # noqa: BLE001
        print(f"FAILED: {type(e).__name__}: {e}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
