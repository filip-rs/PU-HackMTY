#!/usr/bin/env python3
"""One command for a live investigation; hidden scoring stays outside agent/."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.data import load  # noqa: E402
from agent.investigate import replay, run  # noqa: E402
from agent.report import render  # noqa: E402
from agent.steplog import parse_lines  # noqa: E402
from api.server import RunRegistry as APIRegistry  # noqa: E402
from api.server import dataset_entry, serve  # noqa: E402
from data_estate.generate import Generator, write_estate  # noqa: E402
from data_estate.score import score  # noqa: E402
from data_estate.validate import check  # noqa: E402

ALL_SCHEMES = ["efos", "kickback", "roundtrip", "duplicate", "threshold", "revenue"]
LIVE = ROOT / "data_estate/out/live"


class RunRegistry(APIRegistry):
    """The fixed-path log copy is an alias, not another failed investigation."""

    def _disk_ids(self):
        return super()._disk_ids() - {"latest"}


@contextmanager
def stage(name):
    start = time.perf_counter()
    try:
        yield
    finally:
        print(f"TIME {name}: {time.perf_counter() - start:.3f} s", flush=True)


def replay_log(src, dst, delay=0.3):
    """Copy a trace at presentation speed, flushing so SSE can tail each line."""
    with Path(src).open(encoding="utf-8") as source, Path(dst).open("w", encoding="utf-8") as target:
        for line in source:
            target.write(line)
            target.flush()
            time.sleep(delay)


def execute(args, schemes):
    start = time.perf_counter()
    dataset = (args.estate or args.dataset or LIVE / f"company_{args.seed}").resolve()
    if args.replay_from:
        with stage("replay input"):
            entries, _ = parse_lines(args.replay_from.read_text(encoding="utf-8"))
            source_dataset = next((e["payload"].get("dataset") for e in entries if e["kind"] == "run_start"), None)
            if not source_dataset:
                raise ValueError(f"{args.replay_from}: no run_start with a dataset path")
            dataset = Path(source_dataset)
    elif not (args.estate or args.dataset):
        with stage("generate"):
            write_estate(Generator(args.seed).build(schemes), dataset)
        with stage("validate"):
            errors = check(dataset)
            if errors:
                print("\n".join(errors), file=sys.stderr)
                return 1
    with stage("judge sheet"):
        ds = load(dataset)
        print(f"Company: {ds.company['name']}")
        print(f"Suppliers: {len(ds.suppliers)}; customers: {len(ds.customers)}; "
              f"invoices: {len(ds.invoices)}; bank transactions: "
              f"{len(ds.bank_transactions) + len(ds.counterparty_bank)}")
    server = None
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    if args.replay_from:
        run_id = "replay_" + run_id
    registry = RunRegistry(args.runs)
    try:
        if args.serve or args.replay_from:
            with stage("serve"):
                server = serve("127.0.0.1", args.port, args.runs, LIVE)
                server.registry = registry
                threading.Thread(target=server.serve_forever, daemon=True).start()
                print(f"API: http://127.0.0.1:{server.server_port}", flush=True)
        registry.start(run_id, str(dataset))
        out = registry.case_path(run_id)
        log = registry.log_path(run_id)
        artifacts = dict(out=str(out), submission=str(registry.submission_path(run_id)),
                         report=str(registry.html_path(run_id)))
        with stage("replay" if args.replay_from else "investigate"):
            if args.replay_from:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    copying = pool.submit(replay_log, args.replay_from, log, 0.3)
                    case = replay(str(args.replay_from), **artifacts)
                    copying.result()
            else:
                case = run(dataset, log=str(log), no_llm=args.no_llm,
                           max_leads=args.max_leads, workers=args.workers, seed=args.seed,
                           **artifacts)

        with stage("report"):
            entries, _ = parse_lines(log.read_text(encoding="utf-8"))
            registry.report_path(run_id).write_text(render(case, ds, log=entries), encoding="utf-8")
        with stage("score"):
            if not args.replay_from and not args.estate and dataset_entry(dataset)["has_truth"]:
                print("SCORE (uses hidden ground truth; show the judges only when they ask)")
                print(json.dumps(score(dataset, case), indent=2))
        if dataset.suffix == ".db":
            with stage("submission validation"):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/judges/validate_format.py"),
                     "--submission", str(registry.submission_path(run_id)), "--estate", str(dataset)],
                    capture_output=True, text=True,
                )
                print(result.stdout, end="")
                if result.returncode:
                    registry.fail(run_id, "submission validation failed")
                    print(result.stderr, file=sys.stderr, end="")
                    return 1
        # Publish fixed-name hand-ins only after all validation succeeds.
        shutil.copyfile(log, args.runs / "latest.jsonl")
        shutil.copyfile(registry.submission_path(run_id), args.runs / "submission.json")
        shutil.copyfile(registry.html_path(run_id), args.runs / "report.html")
        for artifact in (out, log, registry.report_path(run_id), args.runs / "submission.json", args.runs / "report.html"):
            print(artifact)
        registry.finish(run_id, len(case["findings"]))
        meta = case["run_metadata"]
        calls, cost = (0, 0.0) if args.replay_from else (meta['llm_calls'], meta['mxn_cost'])
        print(f"LLM calls: {calls}; MXN cost: {cost}; "
              f"wall-clock seconds: {time.perf_counter() - start:.3f}", flush=True)
        if server:
            print("Serving until Ctrl-C", flush=True)
            threading.Event().wait()
        return 0
    except KeyboardInterrupt:
        if registry.active() == run_id:
            registry.fail(run_id, "interrupted")
            return 130
        return 0
    except Exception as exc:
        registry.fail(run_id, str(exc))
        raise
    finally:
        if server:
            server.shutdown()
            server.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, help="generation seed (default: 7)")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--dataset", type=Path)
    inputs.add_argument("--estate", type=Path)
    inputs.add_argument("--replay-from", type=Path, help="rebuild offline and serve a paced trace; keep its dataset available")
    parser.add_argument("--schemes", default="all")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--max-leads", type=int, default=12)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if args.seed is None and not (args.estate or args.dataset or args.replay_from):
        args.seed = 7
    if args.seed == 42 and (args.dataset is None or args.dataset.resolve() != ROOT / "data_estate/out/company_42"):
        parser.error("seed 42 is frozen; use --dataset data_estate/out/company_42 explicitly")
    selection = (args.schemes or "all").strip().lower()
    schemes = (list(ALL_SCHEMES) if selection == "all" else [] if selection == "clean"
               else [name.strip() for name in selection.split(",") if name.strip()])
    bad = [name for name in schemes if name not in ALL_SCHEMES]
    if bad:
        parser.error("unknown scheme(s): " + ", ".join(bad))
    try:
        return execute(args, schemes)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
