"""Tests for agent/data.py judges'-estate loader (#79)."""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest

from agent.data import load
from agent.detectors import run_all
from agent.detectors.efos import detect_efos
from agent.leads import aggregate

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "judges_mini"
TABLES = ("vendors", "invoices", "ledger", "bank_txns", "purchase_orders", "contracts", "employees", "efos_list")


def _build_db(src: Path, db: Path) -> None:
    """Build mini.db from the fixture CSVs (all columns TEXT, exact strings)."""
    con = sqlite3.connect(str(db))
    try:
        for table in TABLES:
            with open(src / f"{table}.csv", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            if not rows:
                continue
            fields = list(rows[0].keys())
            colsdef = ", ".join(f'"{f}" TEXT' for f in fields)
            con.execute(f'CREATE TABLE "{table}" ({colsdef})')
            ph = ", ".join("?" for _ in fields)
            for row in rows:
                con.execute(f'INSERT INTO "{table}" VALUES ({ph})', [row.get(f, "") for f in fields])
    finally:
        con.commit()
        con.close()


def _norm(df):
    """Sort by the first (unique) column so CSV-dir and DB orders match."""
    if len(df) == 0:
        return df
    col = df.columns[0]
    return df.sort_values(col).reset_index(drop=True)


@pytest.fixture(scope="module")
def mini_db(tmp_path_factory):
    db = tmp_path_factory.mktemp("minidb") / "mini.db"
    _build_db(FIXTURE, db)
    return db


def test_dir_and_db_loads_identical(mini_db):
    ds_dir = load(FIXTURE)
    ds_db = load(mini_db)
    for attr in (
        "suppliers", "customers", "employees", "invoices", "goods_receipts",
        "bank_transactions", "counterparty_bank", "ledger", "efos_69b",
        "purchase_orders", "contracts",
    ):
        assert _norm(getattr(ds_dir, attr)).equals(_norm(getattr(ds_db, attr))), attr
    assert ds_dir.company == ds_db.company
    assert ds_dir.record_table == ds_db.record_table
    assert ds_dir.source_format == ds_db.source_format == "judges"


def test_company_identity(mini_db):
    ds = load(FIXTURE)
    assert ds.company["rfc"] == "EMP920101AB1"
    assert ds.company["clabe"] == "000000000000000099"


def test_suppliers_and_customers(mini_db):
    ds = load(FIXTURE)
    assert set(ds.suppliers["supplier_id"]) == {"RFC:AAAA010101AA1", "RFC:BBBB020202BB2"}
    assert set(ds.customers["customer_id"]) == {"RFC:CCCC030303CC3"}


def test_payment_link_recovery(mini_db):
    ds = load(FIXTURE)
    by_txn = dict(zip(ds.bank_transactions["txn_id"], ds.bank_transactions["invoice_uuid"]))
    assert by_txn["TX-001"] == "FA-0001"   # recovered from the reference text
    assert by_txn["TX-002"] == "FB-0002"   # recovered from vendor CLABE + amount + date
    assert by_txn["TX-004"] == ""          # payroll transfer, no invoice
    assert len(ds.bank_transactions) == 4
    assert len(ds.counterparty_bank) == 1
    assert ds.counterparty_bank["direction"].iloc[0] == "out"


def test_po_proxy_and_record_table(mini_db):
    ds = load(FIXTURE)
    assert len(ds.goods_receipts) == 1
    row = ds.goods_receipts.iloc[0]
    assert row["receipt_id"] == "PO-0001"
    assert row["invoice_uuid"] == "FB-0002"
    assert ds.record_table["PO-0001"] == "purchase_orders"
    assert ds.record_table["TX-001"] == "bank_txns"


def test_efos_and_employees(mini_db):
    ds = load(FIXTURE)
    assert ds.efos_69b["situacion"].iloc[0] == "Definitivo"
    assert set(ds.employees["personal_clabe"]) == {"333333333333333333", "444444444444444444"}


def test_pipeline_runs_and_detects_efos(mini_db):
    ds = load(FIXTURE)
    assert run_all(ds)  # runs without error
    assert aggregate(ds)  # runs without error
    assert "RFC:AAAA010101AA1" in {d["entity_id"] for d in detect_efos(ds)}


def test_legacy_still_legacy():
    """The legacy loader path is untouched and still detected as legacy."""
    from tests.conftest import COMPANY_42
    ds = load(COMPANY_42)
    assert ds.source_format == "legacy"
    assert len(ds.suppliers) > 0
