#!/usr/bin/env python3
"""Batch evaluation (#25): run the agent on N fresh datasets and score each run.

  python scripts/eval_batch.py --seeds 101-110 [--schemes all|clean|random|efos,kickback]
        [--no-llm] [--out docs/eval/<YYYY-MM-DD>.md] [--workdir data_estate/out/batch]
        [--max-leads 12] [--min-recall 0.8] [--max-penalty 0]

This is the "on records it has never seen" number for the pitch and the go/no-go
gate before the feature freeze (docs/PLAN.md hours 12-24: mean recall >= 0.8 and
judgment penalty 0 on every seed). One command generates N fresh datasets, runs the
agent on each, scores every run, and prints a table plus a markdown file for slides.

The CLI and the test share the same functions: run_batch, parse_seeds, plan,
to_markdown. Stdlib only (argparse, statistics, time, traceback) plus the existing
``data_estate`` and ``agent`` packages. No new dependencies.

Seed 42 is refused: company_42 is frozen and its answer file is in the repo, so it is
not "unseen". CI does not run this (it needs the whole agent and, in LLM mode, .env);
it is a manual gate a human runs before the freeze.

Exit code 1 when mean_recall < --min-recall, or any seed's penalty > --max-penalty,
or any clean seed produced a finding; 0 otherwise.
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ALL_SCHEMES = ["efos", "kickback", "roundtrip", "duplicate"]


def parse_seeds(text: str) -> list[int]:
    """Parse "101-103,200" -> [101, 102, 103, 200].

    Refuses seed 42 (frozen company_42 is not "unseen").
    """
    out: list[int] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            a, b = token.split("-", 1)
            lo, hi = int(a), int(b)
            if lo > hi:
                lo, hi = hi, lo
            out.extend(range(lo, hi + 1))
        else:
            out.append(int(token))
    if 42 in out:
        print(
            "error: seed 42 is the frozen company_42 and its answer file is in the repo; "
            "not 'unseen'. Choose a different range.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return out


def plan(seeds: list[int], schemes_arg: str) -> list[tuple[int, list[str]]]:
    """Map each seed to its scheme list based on the --schemes argument.

    "all" (default) plants the four schemes; "clean" plants none; "random" picks,
    per seed, a deterministic subset via ``random.Random(seed).sample(...)`` of
    random size 0-4; an explicit comma list plants exactly those names.
    """
    arg = (schemes_arg or "all").strip().lower()
    if arg == "all":
        per_seed: list[str] = list(ALL_SCHEMES)
        randomized = False
    elif arg == "clean":
        per_seed = []
        randomized = False
    elif arg == "random":
        per_seed = []
        randomized = True
    else:
        names = [x.strip() for x in arg.split(",") if x.strip()]
        bad = [n for n in names if n not in ALL_SCHEMES]
        if bad:
            print("error: unknown scheme(s): " + ", ".join(bad), file=sys.stderr)
            raise SystemExit(2)
        per_seed = names
        randomized = False

    out: list[tuple[int, list[str]]] = []
    for seed in seeds:
        if randomized:
            r = random.Random(seed)
            k = r.randint(0, len(ALL_SCHEMES))
            ss = r.sample(ALL_SCHEMES, k)
        else:
            ss = list(per_seed)
        out.append((seed, ss))
    return out


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    srt = sorted(values)
    if len(srt) == 1:
        return srt[0]
    idx = min(len(srt) - 1, max(0, round(0.95 * (len(srt) - 1))))
    return srt[idx]


def _row(seed: int, schemes: list[str]) -> dict:
    return {
        "seed": seed,
        "schemes": list(schemes),
        "recall": 0.0,
        "found": [],
        "missed": [],
        "penalty": 0,
        "false_acc": [],
        "decoys_acc": [],
        "evidence_validity": 0.0,
        "not_pursued": 0,
        "contract_errors": 0,
        "wall_s": 0.0,
        "error": "",
    }


def run_batch(
    seed_plan: list[tuple[int, list[str]]],
    *,
    no_llm: bool,
    workdir: str | Path,
    max_leads: int = 12,
) -> tuple[list[dict], dict]:
    """Run the agent on each (seed, schemes) pair and score it.

    Returns ``(rows, summary)``. An exception inside any per-seed step is caught,
    printed with its traceback, and recorded as recall 0 / penalty 0 with ``error``
    set so the batch always finishes. Rows and the summary keep the seed/schemes
    fields so the markdown output is self-describing.
    """
    from agent.config import settings
    from agent.contract import validate_case_file
    from agent.data import load as load_ds
    from agent.investigate import run
    from data_estate import validate
    from data_estate.generate import Generator, write_estate
    from data_estate.score import score

    out_root = Path(workdir)
    out_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    wall_times: list[float] = []
    for seed, schemes in seed_plan:
        t0 = time.time()
        row = _row(seed, schemes)
        try:
            estate = Generator(seed).build(list(schemes))
            dataset_dir = out_root / f"company_{seed}"
            write_estate(estate, dataset_dir)
            check_errs = validate.check(dataset_dir)
            if check_errs:
                raise RuntimeError("dataset failed validation: " + "; ".join(check_errs))
            case = run(
                dataset_dir,
                out=str(out_root / f"case_{seed}.json"),
                log=str(out_root / f"log_{seed}.jsonl"),
                no_llm=no_llm,
                max_leads=max_leads,
            )
            res = score(dataset_dir, case)
            row["recall"] = float(res["results_recall"])
            row["found"] = sorted(res["found"])
            row["missed"] = sorted(res["missed"])
            row["penalty"] = int(res["judgment_penalty"])
            row["false_acc"] = sorted(res["false_accusations"])
            row["decoys_acc"] = sorted(res["decoys_accused"])
            row["evidence_validity"] = float(res["evidence_validity"])
            row["not_pursued"] = int(res["not_pursued_listed"])
            row["contract_errors"] = len(validate_case_file(case, load_ds(dataset_dir)))
        except Exception as exc:  # noqa: BLE001 - batch must always finish
            row["error"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        row["wall_s"] = round(time.time() - t0, 3)
        wall_times.append(row["wall_s"])
        rows.append(row)

    s = settings()
    if no_llm or s is None:
        mode = "no-llm"
        model = ""
    else:
        mode = "llm"
        model = str(s.model)
    mode_label = f"{mode} ({model})" if model else mode

    recall_vals = [r["recall"] for r in rows]
    ev_vals = [r["evidence_validity"] for r in rows]
    summary = {
        "seeds": [r["seed"] for r in rows],
        "mode": mode_label,
        "model": model,
        "mean_recall": sum(recall_vals) / len(recall_vals) if recall_vals else 0.0,
        "min_recall": min(recall_vals) if recall_vals else 0.0,
        "seeds_with_penalty": [r["seed"] for r in rows if r["penalty"] > 0],
        "clean_seeds_with_findings": [r["seed"] for r in rows if not r["schemes"] and r["found"]],
        "mean_evidence_validity": sum(ev_vals) / len(ev_vals) if ev_vals else 0.0,
        "wall_p50_s": statistics.median(wall_times) if wall_times else 0.0,
        "wall_p95_s": _p95(wall_times),
        "n_errors": len([r for r in rows if r["error"]]),
    }
    return rows, summary


_COLUMNS = [
    "seed",
    "schemes",
    "recall",
    "found",
    "missed",
    "penalty",
    "false_acc",
    "decoys_acc",
    "evidence_validity",
    "not_pursued",
    "contract_errors",
    "wall_s",
    "error",
]


def _cell(key: str, value) -> str:
    if key in ("schemes", "found", "missed", "false_acc", "decoys_acc"):
        return ",".join(str(v) for v in value) if isinstance(value, (list, tuple)) else str(value)
    if key in ("recall", "evidence_validity"):
        return f"{float(value):.3f}" if isinstance(value, (int, float)) else str(value)
    if key == "wall_s":
        return f"{float(value):.2f}" if isinstance(value, (int, float)) else str(value)
    return str(value)


def to_markdown(rows: list[dict], summary: dict, argv: list[str]) -> str:
    """Render the rows as a markdown table plus a summary block."""
    header = "| " + " | ".join(_COLUMNS) + " |"
    sep = "| " + " | ".join(["---"] * len(_COLUMNS)) + " |"
    lines = [header, sep]
    for row in rows:
        cells = [_cell(c, row.get(c)) for c in _COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- seeds: {summary['seeds']}")
    lines.append(f"- mode: {summary['mode']}")
    lines.append(f"- mean_recall: {summary['mean_recall']:.3f}")
    lines.append(f"- min_recall: {summary['min_recall']:.3f}")
    lines.append(f"- seeds_with_penalty: {summary['seeds_with_penalty']}")
    lines.append(f"- clean_seeds_with_findings: {summary['clean_seeds_with_findings']}")
    lines.append(f"- mean_evidence_validity: {summary['mean_evidence_validity']:.3f}")
    lines.append(f"- wall_p50_s: {summary['wall_p50_s']:.2f}")
    lines.append(f"- wall_p95_s: {summary['wall_p95_s']:.2f}")
    if summary.get("n_errors"):
        lines.append(f"- errors: {summary['n_errors']}")
    lines.append(f"- command: {' '.join(argv)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/eval_batch.py")
    parser.add_argument("--seeds", required=True, help="range 'a-b', comma list, or both, e.g. 101-105,200")
    parser.add_argument("--schemes", default="all", help="all|clean|random|comma list of scheme names")
    parser.add_argument("--no-llm", action="store_true", help="use the deterministic fallback path")
    parser.add_argument("--out", default=None, help="also write a markdown table to this path")
    parser.add_argument("--workdir", default="data_estate/out/batch", help="dir for generated datasets")
    parser.add_argument("--max-leads", type=int, default=12)
    parser.add_argument("--min-recall", type=float, default=0.8)
    parser.add_argument("--max-penalty", type=int, default=0)
    args = parser.parse_args(argv)

    seeds = parse_seeds(args.seeds)
    seed_plan = plan(seeds, args.schemes)
    rows, summary = run_batch(seed_plan, no_llm=args.no_llm, workdir=args.workdir, max_leads=args.max_leads)
    summary["command_line"] = " ".join(sys.argv)

    # Print an aligned table on stdout.
    cells = [[_cell(c, r.get(c)) for c in _COLUMNS] for r in rows]
    widths = [len(_COLUMNS[i]) for i in range(len(_COLUMNS))]
    for c in cells:
        for i, val in enumerate(c):
            widths[i] = max(widths[i], len(val))

    def pad(items):
        return "  ".join(v.ljust(widths[i]) for i, v in enumerate(items))

    print(pad(_COLUMNS))
    print(pad(["-" * w for w in widths]))
    for c in cells:
        print(pad(c))

    print("\nSummary")
    for key in ("seeds", "mode", "mean_recall", "min_recall", "seeds_with_penalty",
                "clean_seeds_with_findings", "mean_evidence_validity", "wall_p50_s", "wall_p95_s"):
        print(f"  {key}: {summary[key]}")
    print(f"  command_line: {summary.get('command_line', '')}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(to_markdown(rows, summary, sys.argv), encoding="utf-8")
        print(f"\nwrote {out_path}")

    gate_fail = (
        summary["mean_recall"] < args.min_recall
        or any(r["penalty"] > args.max_penalty for r in rows)
        or bool(summary["clean_seeds_with_findings"])
    )
    return 1 if gate_fail else 0


if __name__ == "__main__":
    sys.exit(main())
