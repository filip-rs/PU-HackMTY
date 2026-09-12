"""Typed, in-memory view of a dataset directory (#2).

Every detector (#4-#11), the tool layer (#12) and the guard (#14) build on this.
Load rules (see docs/ISSUES.md #2):
- Read every CSV with dtype=str, keep_default_na=False: empty cells stay "", never NaN.
- Convert dates to datetime64 and money/quantities to float64 afterwards.
- Everything else stays str; CLABEs, folio, po_number, account_code must keep
  their leading zeros.
- Never opens anything under hidden/.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DATE_COLUMNS = {
    "suppliers": ["onboarded"],
    "invoices": ["fecha", "fecha_timbrado"],
    "goods_receipts": ["fecha"],
    "bank_transactions": ["fecha"],
    "counterparty_bank": ["fecha"],
    "ledger": ["fecha"],
    "efos_69b": ["fecha_publicacion"],
}

FLOAT_COLUMNS = {
    "invoices": ["cantidad", "valor_unitario", "subtotal", "iva", "total"],
    "goods_receipts": ["cantidad"],
    "bank_transactions": ["amount"],
    "counterparty_bank": ["amount"],
    "ledger": ["debit", "credit"],
}


@dataclass
class Dataset:
    path: Path
    company: dict  # company.json: name, rfc, clabe, city
    suppliers: pd.DataFrame  # supplier_id, name, rfc, street, city, clabe, account_holder, category, onboarded, approved_by, status
    customers: pd.DataFrame  # customer_id, name, rfc, street, city, clabe
    employees: pd.DataFrame  # employee_id, name, rfc, role, home_street, home_city, personal_clabe
    invoices: pd.DataFrame  # uuid, tipo, serie, folio, fecha, fecha_timbrado, rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor, uso_cfdi, forma_pago, metodo_pago, clave_prod_serv, descripcion, cantidad, valor_unitario, subtotal, iva, total, moneda, po_number, counterparty_id, approved_by
    goods_receipts: pd.DataFrame  # receipt_id, po_number, supplier_id, invoice_uuid, fecha, descripcion, cantidad, received_by, warehouse
    bank_transactions: pd.DataFrame  # txn_id, fecha, account_clabe, direction, amount, counterparty_name, counterparty_clabe, reference, invoice_uuid
    counterparty_bank: pd.DataFrame  # record_id, entity_name, entity_clabe, fecha, direction, amount, counterparty_name, counterparty_clabe, reference
    ledger: pd.DataFrame  # entry_id, fecha, account_code, account_name, debit, credit, descripcion, invoice_uuid, txn_id
    efos_69b: pd.DataFrame  # rfc, nombre, situacion, fecha_publicacion

    def all_record_ids(self) -> set[str]:
        """Invoice uuids | txn_ids | counterparty record_ids | receipt_ids."""
        ids: set[str] = set(self.invoices["uuid"])
        ids.update(self.bank_transactions["txn_id"])
        ids.update(self.counterparty_bank["record_id"])
        ids.update(self.goods_receipts["receipt_id"])
        return ids

    def all_entity_ids(self) -> set[str]:
        """supplier_ids | customer_ids | employee_ids."""
        ids: set[str] = set(self.suppliers["supplier_id"])
        ids.update(self.customers["customer_id"])
        ids.update(self.employees["employee_id"])
        return ids


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")


def _convert(df: pd.DataFrame, stem: str) -> pd.DataFrame:
    df = df.copy()
    for col in DATE_COLUMNS.get(stem, []):
        df[col] = pd.to_datetime(df[col]).astype("datetime64[ns]")
    for col in FLOAT_COLUMNS.get(stem, []):
        df[col] = df[col].astype("float64")
    return df


def load(path: str | Path) -> Dataset:
    """Load a dataset directory into a Dataset. Never touches hidden/."""
    root = Path(path)
    frames: dict[str, pd.DataFrame] = {}
    for stem in (
        "suppliers",
        "customers",
        "employees",
        "invoices",
        "goods_receipts",
        "bank_transactions",
        "counterparty_bank",
        "ledger",
        "efos_69b",
    ):
        df = _read_csv(root / f"{stem}.csv")
        frames[stem] = _convert(df, stem)
    company = json.loads((root / "company.json").read_text(encoding="utf-8"))
    return Dataset(path=root, company=company, **frames)
