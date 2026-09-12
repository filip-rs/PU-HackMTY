"""Shared fixtures. Tests MAY read hidden/ground_truth.json; agent/ code must never (AGENTS.md rule 2)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMPANY_42 = ROOT / "data_estate" / "out" / "company_42"


@pytest.fixture(scope="session")
def dataset_dir() -> Path:
    return COMPANY_42


@pytest.fixture(scope="session")
def ds(dataset_dir):
    from agent.data import load

    return load(dataset_dir)


@pytest.fixture(scope="session")
def truth() -> dict:
    """Ground truth for company_42: {"schemes": [...], "decoys": [...], "meta": {...}}."""
    return json.loads((COMPANY_42 / "hidden" / "ground_truth.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def scheme(truth):
    """scheme("efos_fake_supplier") -> that scheme's ground-truth dict."""
    by_type = {s["type"]: s for s in truth["schemes"]}
    return lambda t: by_type[t]


@pytest.fixture(scope="session")
def decoy_ids(truth) -> set[str]:
    return {d["supplier_id"] for d in truth["decoys"]}
