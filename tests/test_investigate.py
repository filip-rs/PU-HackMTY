"""Tests for agent/investigate.py (issue #13).

Tests may read hidden/ground_truth.json via the fixtures; agent/ code may not.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.llm import FakeLLM, Reply, ToolCall


def _read_log(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_fakellm_drives_one_lead(tmp_path, dataset_dir):
    """A scripted FakeLLM drives one lead end to end without a network."""
    from agent.investigate import run

    out = tmp_path / "case.json"
    log = tmp_path / "run.jsonl"
    replies = [
        Reply(
            text="Checking the supplier and its kickback outflow.",
            tool_calls=[ToolCall(id="call_1", name="get_supplier", args={"supplier_id": "S00004"})],
            cached=False,
            usage={},
            raw={},
        ),
        Reply(
            text="",
            tool_calls=[
                ToolCall(
                    id="call_2",
                    name="record_finding",
                    args={
                        "scheme_type": "kickback_shell",
                        "accused": ["S00004", "E00002"],
                        "rule": "R2",
                        "amount_mxn": 575360.0,
                        "evidence": [
                            "BFEEB533-ACF5-9149-B1C9-D0DCA38CC35F",
                            "EAC97D37-B587-8D33-1D5B-D8B04027B283",
                        ],
                        "narrative": "test",
                    },
                )
            ],
            cached=False,
            usage={},
            raw={},
        ),
    ]
    case = run(str(dataset_dir), out=str(out), log=str(log), max_leads=1, llm=FakeLLM(replies))

    kinds = [e["kind"] for e in _read_log(log)]
    assert kinds == [
        "run_start",
        "lead",
        "hypothesis",
        "tool_call",
        "tool_result",
        "decision",
        "guard",
        "run_end",
    ]
    assert len(case["findings"]) == 1
    finding = case["findings"][0]
    assert finding["scheme_type"] == "kickback_shell"
    assert finding["accused"] == ["S00004", "E00002"]
    assert finding["amount_mxn"] == 575360.0

    from agent.contract import validate_case_file
    from agent.data import load

    assert validate_case_file(case, load(dataset_dir)) == []


def test_run_returns_same_dict_and_identical_files(tmp_path, dataset_dir):
    from agent.investigate import run

    replies = [
        Reply(
            text="no case here",
            tool_calls=[ToolCall(id="c", name="drop_lead", args={"entity_id": "S00004", "reason": "test drop"})],
            cached=False,
            usage={},
            raw={},
        )
    ]
    o1 = tmp_path / "a.json"
    l1 = tmp_path / "a.jsonl"
    o2 = tmp_path / "b.json"
    l2 = tmp_path / "b.jsonl"
    case1 = run(str(dataset_dir), out=str(o1), log=str(l1), max_leads=1, llm=FakeLLM(list(replies)))
    case2 = run(str(dataset_dir), out=str(o2), log=str(l2), max_leads=1, llm=FakeLLM(list(replies)))
    assert case1 == case2
    assert json.loads(Path(o1).read_text()) == case1
    assert json.loads(Path(o2).read_text()) == case2
    assert Path(o1).read_bytes() == Path(o2).read_bytes()


def test_no_llm_scores(dataset_dir, decoy_ids):
    """--no-llm on company_42 must pass the DoD scores."""
    from agent.investigate import run
    from data_estate.score import score

    case = run(str(dataset_dir), out=None, log=None, no_llm=True)
    res = score(dataset_dir, case)
    assert res["results_recall"] >= 0.75
    assert res["found"] == sorted(res["found"])
    assert res["judgment_penalty"] == 0
    assert res["false_accusations"] == []
    assert res["decoys_accused"] == []
    assert res["evidence_validity"] >= 0.9
    pursued = {e["entity"] for e in case["not_pursued"]}
    assert decoy_ids <= pursued

    # Every finding is well-formed and the case file validates.
    from agent.contract import validate_case_file
    from agent.data import load

    assert validate_case_file(case, load(dataset_dir)) == []
    assert {f["scheme_type"] for f in case["findings"]} == {
        "efos_fake_supplier",
        "kickback_shell",
        "round_trip_sales",
        "duplicate_invoice_payment",
    }


def test_run_default_falls_back_without_env(dataset_dir, decoy_ids):
    """Without .env, settings() is None so the default run uses the fallback."""
    from agent.config import settings
    from agent.investigate import run

    if settings() is not None:
        pytest.skip(".env present; fallback not selected")
    case = run(str(dataset_dir), out=None, log=None)
    pursued = {e["entity"] for e in case["not_pursued"]}
    assert decoy_ids <= pursued
    assert {f["scheme_type"] for f in case["findings"]} == {
        "efos_fake_supplier",
        "kickback_shell",
        "round_trip_sales",
        "duplicate_invoice_payment",
    }


@pytest.mark.llm
def test_llm_end_to_end_with_real_endpoint(dataset_dir):
    from agent.config import settings

    if settings() is None:
        pytest.skip("no .env; skipping the live LLM end-to-end")
    from agent.investigate import run
    from data_estate.score import score

    case = run(str(dataset_dir), out=None, log=None, no_llm=False)
    res = score(dataset_dir, case)
    assert res["results_recall"] >= 0.75
    assert res["judgment_penalty"] == 0
