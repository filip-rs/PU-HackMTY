"""Tests for detect_round_trip (issue #9).

Tests may read hidden/ground_truth.json via the fixtures; the detector may not.
"""
from __future__ import annotations

import json

from agent.detectors.round_trip import detect_round_trip


def test_counts_match_ground_truth(ds, scheme):
    ent = scheme("round_trip_sales")["entities"][0]
    result = detect_round_trip(ds)
    assert len(result) == len(ent["legs"]) == 3


def test_legs_are_the_planted_chains(ds, scheme):
    ent = scheme("round_trip_sales")["entities"][0]
    result = detect_round_trip(ds)
    found = {(r["out_txn"], r["forward_record"], r["in_txn"]) for r in result}
    expected = {(leg["out_txn"], leg["forward_record"], leg["in_txn"]) for leg in ent["legs"]}
    assert found == expected


def test_row_fields_match_leg(ds, scheme):
    ent = scheme("round_trip_sales")["entities"][0]
    legs_by_key = {
        (leg["out_txn"], leg["forward_record"], leg["in_txn"]): leg for leg in ent["legs"]
    }
    result = detect_round_trip(ds)
    for r in result:
        leg = legs_by_key[(r["out_txn"], r["forward_record"], r["in_txn"])]
        assert r["purchase_invoice"] == leg["purchase_invoice"]
        assert r["sales_invoice"] == leg["sales_invoice"]
        assert r["entity_id"] == ent["supplier_id"]
        assert r["customer_id"] == ent["customer_id"]
        assert 0.8 <= r["amount_in"] / r["amount_forward"] <= 1.0
        assert 0 <= r["days_forward_to_in"] <= 14
        assert 0 <= r["days_out_to_forward"] <= 7


def test_iva_effect_0_90_finds_nothing(ds):
    # Documents the IVA effect so nobody "fixes" the threshold back to 0.90.
    assert detect_round_trip(ds, return_min_ratio=0.90) == []


def test_no_decoys(ds, decoy_ids):
    result = detect_round_trip(ds)
    assert all(r["entity_id"] not in decoy_ids for r in result)
    assert all(r["customer_id"] not in decoy_ids for r in result)


def test_well_formed_leads_and_serializable(ds):
    result = detect_round_trip(ds)
    record_ids = ds.all_record_ids()
    entity_ids = ds.all_entity_ids()
    for r in result:
        assert r["entity_id"] in entity_ids
        assert r["customer_id"] in entity_ids
        assert r["out_txn"] in record_ids
        assert r["forward_record"] in record_ids
        assert r["in_txn"] in record_ids
        assert r["evidence"] and all(e in record_ids for e in r["evidence"])
        assert isinstance(r["amount_out"], float)
        assert isinstance(r["amount_forward"], float)
        assert isinstance(r["amount_in"], float)
        assert isinstance(r["days_out_to_forward"], int)
        assert isinstance(r["days_forward_to_in"], int)
        assert isinstance(r["purchase_invoice"], str)
        assert isinstance(r["sales_invoice"], str)
    assert json.dumps(result)


def test_sorted_deterministically(ds):
    result = detect_round_trip(ds)
    assert result == sorted(
        result, key=lambda r: (r["out_txn"], r["forward_record"], r["in_txn"])
    )
