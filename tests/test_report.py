"""Tests for agent/report.py (#23): human-readable case file.

The reference case file ``data_estate/out/example_case_file_for_seed42.json``
is the contract: render() must lay out its four findings such that a CFO can
read the money trail, and exposure() must reproduce the verified scheme figures.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent.data import load
from agent.report import exposure, money_trail, render

ROOT = Path(__file__).resolve().parents[1]
COMPANY_42 = ROOT / "data_estate" / "out" / "company_42"
EXAMPLE_FILE = ROOT / "data_estate" / "out" / "example_case_file_for_seed42.json"


@pytest.fixture(scope="module")
def ds():
    return load(COMPANY_42)


@pytest.fixture(scope="module")
def example_case() -> dict:
    return json.loads(EXAMPLE_FILE.read_text(encoding="utf-8"))


def _finding(case: dict, scheme_type: str) -> dict:
    for f in case["findings"]:
        if f["scheme_type"] == scheme_type:
            return f
    raise AssertionError(f"no finding {scheme_type}")


# --- exposure ----------------------------------------------------------------
def test_exposure_efos(ds, example_case):
    expo = exposure(_finding(example_case, "efos_fake_supplier"), ds)
    assert abs(expo["isr_deduction_at_risk"] - 535500.00) <= 0.01
    assert abs(expo["iva_credit_at_risk"] - 285600.00) <= 0.01


def test_exposure_kickback(ds, example_case):
    expo = exposure(_finding(example_case, "kickback_shell"), ds)
    assert abs(expo["isr_deduction_at_risk"] - 148800.00) <= 0.01
    assert abs(expo["iva_credit_at_risk"] - 79360.00) <= 0.01
    assert abs(expo["paid_to_employee"] - 230144.00) <= 0.01


def test_exposure_round_trip(ds, example_case):
    expo = exposure(_finding(example_case, "round_trip_sales"), ds)
    assert abs(expo["revenue_overstated"] - 887068.97) <= 0.01
    assert abs(expo["isr_deduction_at_risk"] - 315000.00) <= 0.01
    assert abs(expo["iva_credit_at_risk"] - 168000.00) <= 0.01


def test_exposure_duplicate(ds, example_case):
    expo = exposure(_finding(example_case, "duplicate_invoice_payment"), ds)
    assert abs(expo["cash_loss"] - 484288.28) <= 0.01
    assert abs(expo["isr_deduction_at_risk"] - 145286.48) <= 0.01


# --- money trail -------------------------------------------------------------
def test_money_trail_round_trip(ds, example_case):
    finding = _finding(example_case, "round_trip_sales")
    rows = money_trail(finding, ds)
    dates = [r["fecha"] for r in rows]
    assert dates == sorted(dates)
    cust_name = str(
        ds.customers[ds.customers["customer_id"] == "C00005"]["name"].iloc[0]
    )
    cp_rows = [r for r in rows if r["kind"] == "cp"]
    assert cp_rows and cp_rows[0]["to"] == cust_name
    txn_in = [r for r in rows if r["kind"] == "txn" and r["from"] == cust_name]
    assert txn_in and txn_in[0]["to"] == str(ds.company["name"])


# --- render ------------------------------------------------------------------
def test_render_contains_reference_numbers(ds, example_case):
    doc = render(example_case, ds)
    for s in ("535,500.00", "230,144.00", "887,068.97", "484,288.28"):
        assert s in doc, f"missing {s}"


def test_render_lays_out_findings(ds, example_case):
    doc = render(example_case, ds)
    assert doc.count("## Finding") == 4
    for name in ("Fake supplier on the SAT 69-B list", "Kickback through a related-party shell",
                 "Round-trip sales (fictitious revenue)", "Duplicate payment diverted to an unregistered account"):
        assert name in doc, f"missing plain-words scheme name {name!r}"


def test_render_names_entities(ds, example_case):
    doc = render(example_case, ds)
    # every accused id is resolved to its name, never a bare id
    for f in example_case["findings"]:
        for accused in f["accused"]:
            name, _qual = _entity_lookup(ds, accused)
            assert name in doc, f"missing name {name!r}"
            assert accused in doc
    assert "(E00002" in doc
    assert "accused: E00002" not in doc


def test_render_contains_evidence_ids(ds, example_case):
    doc = render(example_case, ds)
    for f in example_case["findings"]:
        for e in f["evidence"]:
            assert e in doc, f"missing evidence id {e}"


def test_render_contains_not_pursued_reasons_verbatim(ds, example_case):
    doc = render(example_case, ds)
    for row in example_case["not_pursued"]:
        assert row["reason"] in doc, f"missing not_pursued reason {row['reason']!r}"


# --- helpers -----------------------------------------------------------------
def _entity_lookup(ds, eid):
    from agent.report import _entity_name

    return _entity_name(ds, eid)


# --- CLI ---------------------------------------------------------------------
def _run_cli(args):
    return subprocess.run(
        [sys.executable, "-m", "agent.report", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_cli_writes_output(ds, example_case, tmp_path):
    out = tmp_path / "c42.md"
    res = _run_cli([str(COMPANY_42), str(EXAMPLE_FILE), "--out", str(out)])
    assert res.returncode == 0, res.stderr
    assert out.exists() and "Forensic audit case file" in out.read_text(encoding="utf-8")


def test_cli_rejects_invalid_evidence(ds, example_case, tmp_path):
    bad = tmp_path / "bad.json"
    import copy

    case = copy.deepcopy(example_case)
    case["findings"][0]["evidence"].append("TX99999")
    bad.write_text(json.dumps(case), encoding="utf-8")
    out = tmp_path / "bad.md"
    res = _run_cli([str(COMPANY_42), str(bad), "--out", str(out)])
    assert res.returncode == 1
    assert "TX99999" in res.stderr
    assert not out.exists()
