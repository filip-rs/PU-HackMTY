"""Tests for agent/clear.py (#69): not_pursued reasons are grounded in the records.

Every ``clear_reason`` returns either a readable innocent explanation *with
record IDs* or ``None`` when the records cannot confirm it. These tests exercise
the per-detector checks on company_42, the strong-detector never-cleared rule,
the two defensive None paths, and the end-to-end guarantee that a decoy's
``not_pursued`` reason names a record.
"""
from __future__ import annotations

import re
from dataclasses import replace

import pytest

from agent.clear import (
    cancelled_reversed,
    clear_reason,
    contract_on_file,
    po_trail,
    same_bank_only,
    tool_calls_for,
)


# --- per-detector checks on company_42 ---------------------------------------
def test_clear_new_vendor_s00009(ds):
    r = clear_reason("detect_new_vendor_round_amounts", "S00009", [], ds)
    assert r is not None
    assert "5 invoices" in r
    ids = set(ds.goods_receipts["receipt_id"].astype(str))
    gr_in_text = re.findall(r"GR\d+", r)
    assert len([g for g in gr_in_text if g in ids]) >= 3
    assert "JMK241214132" in r


def test_clear_name_twin_s00007(ds):
    r = clear_reason("detect_name_twin_69b", "S00007", [], ds)
    assert r is not None
    assert "SZC9707063JK" in r
    assert "TAO890114RLQ" in r


def test_clear_shared_address_s00026(ds):
    r = clear_reason("detect_shared_supplier_address", "S00026", [], ds)
    assert r is not None
    assert "S00024" in r
    assert "Garza Sada 337" in r


def test_clear_law_firm_s00036(ds):
    r = clear_reason("detect_fast_pay_no_deliverable", "S00036", [], ds)
    assert r is not None
    assert "809BD813-4F13-823B-51F4-A72499503858" in r
    assert "412/2025" in r
    assert "E00001" in r


def test_clear_cash_s00011(ds):
    r = clear_reason("detect_cash_payments", "S00011", [], ds)
    assert r is not None
    assert "1,821.72" in r
    assert "2,000" in r
    assert any(t.startswith("GR") for t in re.findall(r"GR\d+", r))


# --- strong detectors are never cleared -------------------------------------
def test_strong_detector_never_cleared(ds):
    assert clear_reason("detect_efos", "S00030", [], ds) is None
    assert clear_reason("detect_duplicate_payments", "S00017", [], ds) is None


# --- defensive None paths ------------------------------------------------------
def test_goods_category_without_receipt_is_none(ds):
    s00009_uuids = set(
        ds.invoices[
            (ds.invoices["tipo"] == "recibida")
            & (ds.invoices["counterparty_id"].astype(str) == "S00009")
        ]["uuid"].astype(str)
    )
    gr2 = ds.goods_receipts[~ds.goods_receipts["invoice_uuid"].astype(str).isin(s00009_uuids)].copy()
    ds2 = replace(ds, goods_receipts=gr2)
    assert clear_reason("detect_no_receipt", "S00009", [], ds2) is None
    assert clear_reason("detect_new_vendor_round_amounts", "S00009", [], ds2) is None


def test_shared_address_at_employee_home_is_none(ds):
    e = ds.employees[ds.employees["employee_id"].astype(str) == "E00002"].iloc[0]
    sup2 = ds.suppliers.copy()
    mask = sup2["supplier_id"].astype(str) == "S00026"
    sup2.loc[mask, "street"] = e["home_street"]
    sup2.loc[mask, "city"] = e["home_city"]
    ds2 = replace(ds, suppliers=sup2)
    assert clear_reason("detect_shared_supplier_address", "S00026", [], ds2) is None


# --- end-to-end: decoys carry a grounded reason -------------------------------
def _entity_tokens(ds):
    ids = set(ds.all_record_ids())
    rfcs = set(ds.suppliers["rfc"].astype(str))
    ents = (
        set(ds.suppliers["supplier_id"].astype(str))
        | set(ds.customers["customer_id"].astype(str))
        | set(ds.employees["employee_id"].astype(str))
    )
    return ids, rfcs, ents


def test_every_decoy_reason_cites_a_record(dataset_dir, ds, decoy_ids):
    from agent.investigate import run

    case = run(str(dataset_dir), out=None, log=None, no_llm=True)
    reasons = {e["entity"]: e["reason"] for e in case["not_pursued"]}
    assert decoy_ids <= set(reasons)
    ids, rfcs, ents = _entity_tokens(ds)
    for dec in decoy_ids:
        r = reasons[dec]
        assert not r.startswith("unverified:")
        assert any(x in r for x in ids) or any(x in r for x in rfcs) or any(x in r for x in ents)


def test_every_not_pursued_reason_is_grounded_or_unverified(dataset_dir, ds):
    from agent.investigate import run

    case = run(str(dataset_dir), out=None, log=None, no_llm=True)
    ids, rfcs, ents = _entity_tokens(ds)
    for e in case["not_pursued"]:
        r = e["reason"]
        assert r.startswith("unverified:") or any(x in r for x in ids) or any(x in r for x in rfcs) or any(x in r for x in ents)


def test_unknown_detector_is_none(ds):
    assert clear_reason("detect_does_not_exist", "S00009", [], ds) is None


# --- judge-estate checks (#94) -------------------------------------------------
# On a judges' estate the documents that clear a lead are purchase orders, a
# standing contract and the bank code, not a goods receipt and a home address.

# judges_mini: a fixed-fee maintenance vendor (B) is cleared by both a PO and a
# contract; the consulting vendor (A) has neither and is not cleared.
def test_judges_mini_vendor_b_cleared_by_po_trail(judges_mini_dir):
    from agent.data import load

    m = load(judges_mini_dir)
    v, reason, records = po_trail("RFC:BBBB020202BB2", m)
    assert v is True
    assert "PO-0001" in reason
    assert "PO-0001" in records
    assert "Ana Ruiz Medina" in reason


def test_judges_mini_vendor_b_cleared_by_contract_on_file(judges_mini_dir):
    from agent.data import load

    m = load(judges_mini_dir)
    v, reason, records = contract_on_file("RFC:BBBB020202BB2", m)
    assert v is True
    assert "CTR-0001" in reason
    assert "CTR-0001" in records
    assert "46,400.00" in reason


def test_judges_mini_vendor_a_not_cleared(judges_mini_dir):
    from agent.data import load

    m = load(judges_mini_dir)
    assert po_trail("RFC:AAAA010101AA1", m)[0] is False
    assert contract_on_file("RFC:AAAA010101AA1", m)[0] is False


# seed 7 D6/D7 decoys (#81): D6 shares a bank code but no transfer passes; D7 is a
# fixed-fee services decoy under a framework contract.
@pytest.fixture(scope="module")
def seed7_judges(tmp_path_factory):
    """Seed 7 exported to the judges' schema, loaded as a Dataset."""
    from agent.data import load
    from data_estate.export_judges import write_judges_estate
    from data_estate.generate import COMPANY, Generator

    out = tmp_path_factory.mktemp("estate7") / "estate_7"
    estate = Generator(7).build(["threshold", "revenue"])
    write_judges_estate(estate, out, seed=7, company=COMPANY)
    return load(out / "csv")


def test_seed7_d6_cleared_by_same_bank_only(seed7_judges):
    v, reason, records = same_bank_only("RFC:OTH9706272RX", seed7_judges)
    assert v is True
    assert "002" in reason  # bank code shared with the buyer
    assert "EMP:00002" in reason  # the Gerente de Compras
    assert "no transfer" in reason


def test_seed7_d7_cleared_by_contract_on_file(seed7_judges):
    v, reason, records = contract_on_file("RFC:EQF220218ZO1", seed7_judges)
    assert v is True
    assert "CTR-S00013" in reason
    assert "CTR-S00013" in records
    assert "261,000.00" in reason  # value/12 == the 12 equal invoices


def test_seed7_threshold_lead_cleared_by_contract(seed7_judges):
    # The planted threshold-splitting supplier is not under a contract, so it
    # must NOT be cleared; the fixed-fee decoy is.
    from agent.detectors import run_all

    leads = run_all(seed7_judges)["detect_threshold_splitting"]
    planted = {str(r["entity_id"]) for r in leads}
    assert "RFC:EQF220218ZO1" not in planted, "the fixed-fee decoy does not cluster"
    assert planted, "expected the planted threshold-splitting supplier to be a lead"


def test_seed7_revenue_inflation_not_cleared_by_cancelled_reversed(seed7_judges):
    # The planted revenue-inflation customer has cancellations never reversed, so
    # `cancelled_reversed` must NOT clear it (that would hide a real finding).
    v, reason, _recs = cancelled_reversed("RFC:ODL88020677Z", seed7_judges)
    assert v is False
    assert reason == ""


def test_no_receipt_lead_cleared_by_po_trail_on_seed7(seed7_judges):
    # The freight decoy shares an address and never closes a goods receipt, but a
    # PO trail explains its invoices: cleared (grounded), not "unverified".
    r = clear_reason("detect_no_receipt", "RFC:TQC150925LNX", [], seed7_judges)
    assert r is not None


def test_every_not_pursued_entry_has_bookkeeping(dataset_dir, ds):
    from agent.investigate import run

    case = run(str(dataset_dir), out=None, log=None, no_llm=True)
    for e in case["not_pursued"]:
        assert e.get("signal"), f"{e['entity']}: signal must be non-empty"
        assert e.get("tool_calls_made"), f"{e['entity']}: tool_calls_made must be non-empty"
        assert e.get("closed_by") in ("investigator", "challenger", "validator")


def test_tool_calls_for_maps_detectors_to_checks():
    assert tool_calls_for(["detect_no_receipt"]) == ["po_trail"]
    assert tool_calls_for(["detect_threshold_splitting"]) == ["contract_on_file"]
    assert tool_calls_for(["detect_kickback_outflow"]) == ["same_bank_only"]
    assert tool_calls_for(["detect_revenue_inflation"]) == ["cancelled_reversed"]
    assert tool_calls_for(["detect_efos"]) == ["presunto_only"]
    # deduped and ordered
    assert tool_calls_for(["detect_no_receipt", "detect_fast_pay_no_deliverable"]) == ["po_trail"]
