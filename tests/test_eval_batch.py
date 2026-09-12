"""scripts/eval_batch.py (#25): batch recall/penalty/evidence over fresh seeds.

Skips if agent.investigate is not importable (until #13 lands), so it never blocks
CI for the detector PRs. Tests may read hidden/ground_truth.json; agent/ may not.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("agent.investigate")

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("eval_batch", ROOT / "scripts" / "eval_batch.py")
assert SPEC is not None and SPEC.loader is not None
eval_batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eval_batch)


def test_parse_seeds_range_and_list():
    assert eval_batch.parse_seeds("101-103,200") == [101, 102, 103, 200]


def test_parse_seeds_refuses_frozen_42():
    with pytest.raises(SystemExit):
        eval_batch.parse_seeds("42")


def test_plan_all_clean_and_list():
    assert eval_batch.plan([101], "all") == [(101, ["efos", "kickback", "roundtrip", "duplicate"])]
    assert eval_batch.plan([101], "clean") == [(101, [])]
    assert eval_batch.plan([101], "efos,kickback") == [(101, ["efos", "kickback"])]


def test_plan_random_is_deterministic_per_seed():
    a = eval_batch.plan([101, 102], "random")
    b = eval_batch.plan([101, 102], "random")
    assert a == b
    # every scheme name is valid
    for _, sch in a:
        assert set(sch) <= set(eval_batch.ALL_SCHEMES)


def test_run_batch_scores_planted_and_clean(tmp_path):
    rows, summary = eval_batch.run_batch(
        [
            (101, ["efos", "kickback", "roundtrip", "duplicate"]),
            (102, []),
        ],
        no_llm=True,
        workdir=tmp_path,
    )

    assert len(rows) == 2
    by_seed = {r["seed"]: r for r in rows}

    row101 = by_seed[101]
    assert row101["recall"] == 1.0
    assert row101["penalty"] == 0
    assert set(row101["found"]) == {
        "efos_fake_supplier",
        "kickback_shell",
        "round_trip_sales",
        "duplicate_invoice_payment",
    }

    row102 = by_seed[102]
    assert row102["found"] == []
    assert row102["penalty"] == 0

    assert summary["clean_seeds_with_findings"] == []
    assert summary["seeds_with_penalty"] == []


def test_to_markdown_has_header_and_one_line_per_seed(tmp_path):
    rows, summary = eval_batch.run_batch(
        [(101, ["efos"]), (102, [])],
        no_llm=True,
        workdir=tmp_path,
    )
    md = eval_batch.to_markdown(rows, summary, ["python", "scripts/eval_batch.py"])

    assert "| seed | schemes | recall |" in md
    assert "| 101 |" in md
    assert "| 102 |" in md
