"""Typed, in-memory view of a dataset directory (#2) or a judges' estate (#79).

Every detector (#4-#11), the tool layer (#12) and the guard (#14) build on this.
Load rules (see docs/ISSUES.md #2):
- Read every CSV with dtype=str, keep_default_na=False: empty cells stay "", never NaN.
- Convert dates to datetime64 and money/quantities to float64 afterwards.
- Everything else stays str; CLABEs, folio, po_number, account_code must keep
  their leading zeros.
- Never opens anything under hidden/.

The judges' estate (#79) arrives either as an SQLite ``.db`` or a CSV directory
per ``estate_schema.sql`` (tables ``vendors``, ``invoices``, ``ledger``,
``bank_txns``, ``purchase_orders``, ``contracts``, ``employees``, ``efos_list``).
``load`` auto-detects it and remaps those tables onto the same :class:`Dataset`
frames the legacy layout uses, so the detectors, tools and guard work on judge
data unchanged.

Two remaps deserve the reader's attention:

- **PO-as-goods-receipt proxy.** In the judges' schema the only deliverable
  trail is a ``purchase_orders`` row, so each invoice matched to a PO becomes a
  synthetic ``goods_receipts`` row whose ``receipt_id`` is the ``po_id``. The
  ``record_table`` map then points that id at ``purchase_orders`` so an exhibit
  cites the right table. "No deliverable" detectors keep working.
- **Payment-link heuristic.** ``bank_txns`` has no ``invoice_uuid``. We recover
  it by (a) an invoice UUID substring inside the txn ``reference``, else (b) the
  counterparty's CLABE plus ``total == amount`` plus ``date >= issue_date`` on
  the earliest unpaid invoice.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
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
    "purchase_orders": ["date"],
    "contracts": ["start_date"],
}

FLOAT_COLUMNS = {
    "invoices": ["cantidad", "valor_unitario", "subtotal", "iva", "total"],
    "goods_receipts": ["cantidad"],
    "bank_transactions": ["amount"],
    "counterparty_bank": ["amount"],
    "ledger": ["debit", "credit"],
    "purchase_orders": ["amount"],
    "contracts": ["value"],
}

# Canonical (legacy) column sets; judge loads replicate them so no detector,
# tool or guard needs to know the source format.
_SUPPLIER_COLS = ["supplier_id", "name", "rfc", "street", "city", "clabe", "account_holder", "category", "onboarded", "approved_by", "status"]
_CUSTOMER_COLS = ["customer_id", "name", "rfc", "street", "city", "clabe"]
_EMPLOYEE_COLS = ["employee_id", "name", "rfc", "role", "home_street", "home_city", "personal_clabe"]
_INVOICE_COLS = ["uuid", "tipo", "serie", "folio", "fecha", "fecha_timbrado", "rfc_emisor", "nombre_emisor", "rfc_receptor", "nombre_receptor", "uso_cfdi", "forma_pago", "metodo_pago", "clave_prod_serv", "descripcion", "cantidad", "valor_unitario", "subtotal", "iva", "total", "moneda", "po_number", "counterparty_id", "approved_by", "status"]
_GR_COLS = ["receipt_id", "po_number", "supplier_id", "invoice_uuid", "fecha", "descripcion", "cantidad", "received_by", "warehouse"]
_BT_COLS = ["txn_id", "fecha", "account_clabe", "direction", "amount", "counterparty_name", "counterparty_clabe", "reference", "invoice_uuid", "channel"]
_CP_COLS = ["record_id", "entity_name", "entity_clabe", "fecha", "direction", "amount", "counterparty_name", "counterparty_clabe", "reference"]
_LEDGER_COLS = ["entry_id", "fecha", "account_code", "account_name", "debit", "credit", "descripcion", "invoice_uuid", "txn_id", "cost_center", "approver"]
_EFOS_COLS = ["rfc", "nombre", "situacion", "fecha_publicacion"]
_PO_COLS = ["po_id", "vendor_rfc", "date", "amount", "requester", "approver", "description"]
_CONTRACT_COLS = ["contract_id", "vendor_rfc", "start_date", "value", "scope_text"]

_JUDGE_TABLES = ("vendors", "invoices", "ledger", "bank_txns", "purchase_orders", "contracts", "employees", "efos_list")


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
    purchase_orders: pd.DataFrame = field(default_factory=pd.DataFrame)  # po_id, vendor_rfc, date, amount, requester, approver, description
    contracts: pd.DataFrame = field(default_factory=pd.DataFrame)  # contract_id, vendor_rfc, start_date, value, scope_text
    record_table: dict[str, str] = field(default_factory=dict)  # record id -> judges' source_table name
    source_format: str = "legacy"  # "legacy" | "judges"

    def all_record_ids(self) -> set[str]:
        """Invoice uuids | txn_ids | counterparty record_ids | receipt_ids | po_ids | contract_ids."""
        ids: set[str] = set(self.invoices["uuid"])
        ids.update(self.bank_transactions["txn_id"])
        ids.update(self.counterparty_bank["record_id"])
        if len(self.goods_receipts):
            ids.update(self.goods_receipts["receipt_id"])
        if len(self.purchase_orders):
            ids.update(self.purchase_orders["po_id"])
        if len(self.contracts):
            ids.update(self.contracts["contract_id"])
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


def _empty(stem: str) -> pd.DataFrame:
    """Empty frame with the canonical columns for a stem."""
    cols = {
        "suppliers": _SUPPLIER_COLS,
        "customers": _CUSTOMER_COLS,
        "employees": _EMPLOYEE_COLS,
        "invoices": _INVOICE_COLS,
        "goods_receipts": _GR_COLS,
        "bank_transactions": _BT_COLS,
        "counterparty_bank": _CP_COLS,
        "ledger": _LEDGER_COLS,
        "efos_69b": _EFOS_COLS,
        "purchase_orders": _PO_COLS,
        "contracts": _CONTRACT_COLS,
    }[stem]
    return pd.DataFrame(columns=cols)


def _load_legacy(root: Path) -> Dataset:
    """Legacy CSV layout unchanged (company.json + the nine CSV stems)."""
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


# --- judges' estate helpers --------------------------------------------------

def _read_judge_tables(target: Path) -> dict[str, pd.DataFrame]:
    """Read the judges' tables (str-typed, "" for NULL) from a .db or a CSV dir."""
    present: set[str]
    if target.is_file():
        conn = sqlite3.connect(str(target))
        try:
            present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
    else:
        present = {p.stem for p in target.glob("*.csv")}

    out: dict[str, pd.DataFrame] = {}
    for table in _JUDGE_TABLES:
        if table not in present:
            continue
        if target.is_file():
            conn = sqlite3.connect(str(target))
            try:
                df = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
            finally:
                conn.close()
        else:
            df = pd.read_csv(target / f"{table}.csv", dtype=str, keep_default_na=False)
        # str-typed, "" for NULL / missing
        df = df.where(pd.notnull(df), "")
        df = df.astype(str)
        out[table] = df
    return out


def _s(row, col: str) -> str:
    return str(row.get(col, "")) if col in row else ""


def _f(row, col: str) -> float:
    v = _s(row, col)
    try:
        return float(v) if v != "" else 0.0
    except ValueError:
        return 0.0


def _dt(s: str):
    try:
        return pd.to_datetime(s)
    except (ValueError, TypeError):
        return pd.NaT


def _identity(rfc: str) -> str:
    return f"RFC:{rfc}"


def _employees_by_name(employees: pd.DataFrame) -> dict[str, str]:
    """Employee name -> emp_id."""
    out: dict[str, str] = {}
    if employees is None or not len(employees):
        return out
    for _, r in employees.iterrows():
        name = _s(r, "name")
        emp = _s(r, "emp_id")
        if name:
            out.setdefault(name, emp)
    return out


def _derive_company(vendors, invoices, bank_txns) -> tuple[str, str]:
    """company_rfc + company_clabe."""
    # rfc = receiver_rfc on most invoices whose issuer is a vendor
    if len(invoices) and len(vendors):
        vendor_rfcs = set(_s(r, "rfc") for _, r in vendors.iterrows())
        sub = invoices[invoices["issuer_rfc"].isin(vendor_rfcs)] if "issuer_rfc" in invoices.columns else invoices.iloc[0:0]
        rfc = sub["receiver_rfc"].mode().iloc[0] if len(sub) else ""
    else:
        rfc = ""
    # clabe = most frequent from_clabe among txns whose to_clabe is a vendor bank_clabe
    clabe = ""
    if len(bank_txns) and len(vendors):
        vendor_clabes = set(_s(r, "bank_clabe") for _, r in vendors.iterrows())
        sub = bank_txns[bank_txns["to_clabe"].isin(vendor_clabes)] if "to_clabe" in bank_txns.columns else bank_txns.iloc[0:0]
        if len(sub) and "from_clabe" in sub.columns:
            clabes = sub["from_clabe"]
            clabe = clabes.mode().iloc[0] if len(clabes) else ""
    return rfc, clabe


def _map_suppliers(vendors, purchase_orders, employees_by_name) -> pd.DataFrame:
    rows: list[dict] = []
    for _, v in (vendors.iterrows() if vendors is not None and len(vendors) else []):
        rfc = _s(v, "rfc")
        approved_by = ""
        if purchase_orders is not None and len(purchase_orders) and "vendor_rfc" in purchase_orders.columns:
            sub = purchase_orders[purchase_orders["vendor_rfc"] == rfc]
            if len(sub) and "approver" in sub.columns:
                appr = sub["approver"].mode().iloc[0]
                approved_by = employees_by_name.get(str(appr), "")
        rows.append({
            "supplier_id": _identity(rfc),
            "name": _s(v, "legal_name"),
            "rfc": rfc,
            "street": _s(v, "address"),
            "city": "",
            "clabe": _s(v, "bank_clabe"),
            "account_holder": _s(v, "legal_name"),
            "category": _s(v, "category"),
            "onboarded": _s(v, "registered_date"),
            "approved_by": approved_by,
            "status": "activo",
        })
    return pd.DataFrame(rows, columns=_SUPPLIER_COLS)


def _match_po(purchase_orders, vendor_rfc, total, issue_date, used_po) -> tuple[str, str, str, str]:
    """Return (po_id, po_date, po_approver, po_description) for the best PO, else all ''.

    Same vendor_rfc, |po.amount - total| <= 0.01, po.date <= issue_date + 30 days;
    earliest unmatched PO wins, one PO per invoice.
    """
    if purchase_orders is None or not len(purchase_orders) or not vendor_rfc:
        return "", "", "", ""
    sub = purchase_orders
    if "vendor_rfc" in sub.columns:
        sub = sub[sub["vendor_rfc"] == vendor_rfc]
    if not len(sub):
        return "", "", "", ""
    best = None  # (po_date, po_id, po_approver, po_description)
    for _, p in sub.iterrows():
        po_id = _s(p, "po_id")
        if po_id in used_po:
            continue
        amt = 0.0
        if _s(p, "amount") != "":
            try:
                amt = float(_s(p, "amount"))
            except ValueError:
                amt = 0.0
        if abs(amt - total) > 0.01:
            continue
        po_date = _dt(_s(p, "date"))
        if pd.isna(issue_date):
            if not pd.isna(po_date):
                continue
        elif pd.isna(po_date) or po_date > issue_date + pd.Timedelta(days=30):
            continue
        if best is None:
            best = (po_date, po_id, _s(p, "approver"), _s(p, "description"))
        elif (pd.isna(po_date) and not pd.isna(best[0])) or (not pd.isna(po_date) and (pd.isna(best[0]) or po_date < best[0])):
            best = (po_date, po_id, _s(p, "approver"), _s(p, "description"))
    if best is None:
        return "", "", "", ""
    used_po.add(best[1])
    return best[1], best[0], best[2], best[3]


def _map_invoices(invoices, vendors_by_rfc, company_rfc, purchase_orders, ledger, employees_by_name):
    """Map judges' invoices onto the legacy invoice frame (+ `status`)."""
    rows: list[dict] = []
    po_by_uuid: dict[str, tuple] = {}
    used_po: set[str] = set()
    for _, r in invoices.iterrows():
        uuid = _s(r, "uuid")
        issuer = _s(r, "issuer_rfc")
        receiver = _s(r, "receiver_rfc")
        recibida = receiver == company_rfc
        tipo = "recibida" if recibida else "emitida"
        cp = issuer if recibida else receiver
        issue_date = _dt(_s(r, "issue_date"))
        total = _f(r, "total")

        po_id = po_approver = po_date = po_desc = ""
        if recibida:
            po_id, po_date, po_approver, po_desc = _match_po(purchase_orders, issuer, total, issue_date, used_po)
            if po_id:
                po_by_uuid[uuid] = (po_id, po_date, po_approver, po_desc)

        approved_by = ""
        if po_id and po_approver:
            approved_by = employees_by_name.get(str(po_approver), "")
        elif ledger is not None and len(ledger) and "invoice_uuid" in ledger.columns:
            gl = ledger[ledger["invoice_uuid"] == uuid]
            if len(gl) and "approver" in gl.columns:
                appr = str(gl["approver"].mode().iloc[0])
                if appr and appr != "nan":
                    approved_by = employees_by_name.get(appr, "")

        rows.append({
            "uuid": uuid,
            "tipo": tipo,
            "serie": "",
            "folio": "",
            "fecha": _s(r, "issue_date"),
            "fecha_timbrado": _s(r, "issue_date"),
            "rfc_emisor": issuer,
            "nombre_emisor": vendors_by_rfc.get(issuer, ""),
            "rfc_receptor": receiver,
            "nombre_receptor": vendors_by_rfc.get(receiver, ""),
            "uso_cfdi": _s(r, "uso_cfdi"),
            "forma_pago": _s(r, "forma_pago"),
            "metodo_pago": _s(r, "metodo_pago"),
            "clave_prod_serv": "",
            "descripcion": _s(r, "concepto_text"),
            "cantidad": 1.0,
            "valor_unitario": _f(r, "subtotal"),
            "subtotal": _f(r, "subtotal"),
            "iva": _f(r, "iva"),
            "total": total,
            "moneda": "MXN",
            "po_number": po_id,
            "counterparty_id": _identity(cp),
            "approved_by": approved_by,
            "status": _s(r, "status") or "vigente",
        })
    return pd.DataFrame(rows, columns=_INVOICE_COLS), po_by_uuid, used_po


def _map_goods_receipts(invoice_df, po_by_uuid, employees_by_name) -> pd.DataFrame:
    """One synthetic goods_receipts row per invoice matched to a PO (PO proxy)."""
    rows: list[dict] = []
    for _, inv in invoice_df.iterrows():
        uuid = _s(inv, "uuid")
        if uuid not in po_by_uuid:
            continue
        po_id, po_date, po_approver, po_desc = po_by_uuid[uuid]
        received_by = ""
        if po_approver:
            received_by = employees_by_name.get(str(po_approver), str(po_approver))
        rows.append({
            "receipt_id": po_id,
            "po_number": po_id,
            "supplier_id": _s(inv, "counterparty_id"),
            "invoice_uuid": uuid,
            "fecha": po_date.strftime("%Y-%m-%d") if not pd.isna(po_date) else "",
            "descripcion": po_desc,
            "cantidad": 1.0,
            "received_by": received_by,
            "warehouse": "",
        })
    return pd.DataFrame(rows, columns=_GR_COLS)


def _recover_invoice(ref, cp_clabe, amount, txn_date, inv_by_clabe, used_inv, all_uuids) -> str:
    """Recover the invoice_uuid for a company-side bank_txn (see module docstring)."""
    if ref:
        for u in all_uuids:
            if u and u in ref:
                used_inv.add(u)
                return u
    for rec in inv_by_clabe.get(cp_clabe, []):
        u = rec["uuid"]
        if u in used_inv:
            continue
        if abs(rec["total"] - amount) <= 0.01 and (pd.isna(txn_date) or pd.isna(rec["fecha"]) or rec["fecha"] <= txn_date):
            used_inv.add(u)
            return u
    return ""


def _map_bank(bank_txns, company_clabe, vendors_by_rfc, vendor_rfc_to_clabe, employees_by_clabe, invoice_df):
    """Map judges' bank_txns onto bank_transactions (company side) + counterparty_bank (third-party legs)."""
    # Index recibida invoices by their vendor's CLABE for the amount+date recovery heuristic.
    inv_by_clabe: dict[str, list[dict]] = {}
    for _, r in invoice_df.iterrows():
        if _s(r, "tipo") != "recibida":
            continue
        clabe = vendor_rfc_to_clabe.get(_s(r, "rfc_emisor"), "")
        if not clabe:
            continue
        inv_by_clabe.setdefault(clabe, []).append({"uuid": _s(r, "uuid"), "total": _f(r, "total"), "fecha": _dt(_s(r, "fecha"))})
    for clabe in inv_by_clabe:
        inv_by_clabe[clabe].sort(key=lambda d: d["fecha"] if not pd.isna(d["fecha"]) else pd.Timestamp.max)

    all_uuids = [_s(r, "uuid") for _, r in invoice_df.iterrows() if _s(r, "uuid")]
    used_inv: set[str] = set()

    vendor_name_by_clabe = {clabe: vendors_by_rfc.get(vendor_rfc_to_clabe.get(clabe, ""), "") for clabe in vendor_rfc_to_clabe.values()}

    bank_rows: list[dict] = []
    cp_rows: list[dict] = []
    txn_inv: dict[str, str] = {}
    for _, t in bank_txns.iterrows():
        txn_id = _s(t, "txn_id")
        from_c = _s(t, "from_clabe")
        to_c = _s(t, "to_clabe")
        amount = _f(t, "amount")
        fecha = _dt(_s(t, "date"))
        ref = _s(t, "reference")
        channel = _s(t, "channel")

        if from_c == company_clabe:
            direction, cp_clabe = "out", to_c
        elif to_c == company_clabe:
            direction, cp_clabe = "in", from_c
        else:
            # Third-party leg (e.g. vendor -> employee): keep as a counterparty statement row.
            entity_name = vendor_name_by_clabe.get(from_c, employees_by_clabe.get(from_c, ""))
            cp_name = vendor_name_by_clabe.get(to_c, employees_by_clabe.get(to_c, ""))
            cp_rows.append({
                "record_id": txn_id,
                "entity_name": entity_name,
                "entity_clabe": from_c,
                "fecha": _s(t, "date"),
                "direction": "out",
                "amount": amount,
                "counterparty_name": cp_name,
                "counterparty_clabe": to_c,
                "reference": ref,
            })
            txn_inv[txn_id] = "bank_txns"
            continue

        counterparty_name = vendor_name_by_clabe.get(cp_clabe, employees_by_clabe.get(cp_clabe, ""))
        inv_uuid = _recover_invoice(ref, cp_clabe, amount, fecha, inv_by_clabe, used_inv, all_uuids)
        bank_rows.append({
            "txn_id": txn_id,
            "fecha": _s(t, "date"),
            "account_clabe": company_clabe,
            "direction": direction,
            "amount": amount,
            "counterparty_name": counterparty_name,
            "counterparty_clabe": cp_clabe,
            "reference": ref,
            "invoice_uuid": inv_uuid,
            "channel": channel,
        })
        txn_inv[txn_id] = "bank_txns"

    return pd.DataFrame(bank_rows, columns=_BT_COLS), pd.DataFrame(cp_rows, columns=_CP_COLS), txn_inv


def _map_customers(invoice_df, bank_df, vendors_by_rfc) -> pd.DataFrame:
    """Distinct receivers on emitida invoices -> customers."""
    emitida = invoice_df[invoice_df["tipo"] == "emitida"] if len(invoice_df) else pd.DataFrame()
    cust_inv: dict[str, set[str]] = {}
    for _, r in emitida.iterrows():
        rfc = _s(r, "rfc_receptor")
        if rfc:
            cust_inv.setdefault(rfc, set()).add(_s(r, "uuid"))
    from_clabe_by_inv: dict[str, list[str]] = {}
    if len(bank_df):
        inb = bank_df[bank_df["direction"] == "in"]
        for _, t in inb.iterrows():
            inv = _s(t, "invoice_uuid")
            if inv:
                from_clabe_by_inv.setdefault(inv, []).append(_s(t, "counterparty_clabe"))
    rows: list[dict] = []
    for rfc, uuids in cust_inv.items():
        all_from = [c for u in uuids for c in from_clabe_by_inv.get(u, [])]
        clabe = max(set(all_from), key=all_from.count) if all_from else ""
        rows.append({
            "customer_id": _identity(rfc),
            "name": vendors_by_rfc.get(rfc, ""),
            "rfc": rfc,
            "street": "",
            "city": "",
            "clabe": clabe,
        })
    return pd.DataFrame(rows, columns=_CUSTOMER_COLS)


def _map_employees(employees) -> pd.DataFrame:
    rows: list[dict] = []
    for _, r in employees.iterrows():
        rows.append({
            "employee_id": _s(r, "emp_id"),
            "name": _s(r, "name"),
            "rfc": "",
            "role": _s(r, "role"),
            "home_street": "",
            "home_city": "",
            "personal_clabe": _s(r, "bank_clabe"),
        })
    return pd.DataFrame(rows, columns=_EMPLOYEE_COLS)


def _map_ledger(ledger) -> pd.DataFrame:
    rows: list[dict] = []
    for _, r in ledger.iterrows():
        rows.append({
            "entry_id": _s(r, "entry_id"),
            "fecha": _s(r, "date"),
            "account_code": _s(r, "account_code"),
            "account_name": _s(r, "account_name"),
            "debit": _f(r, "debit"),
            "credit": _f(r, "credit"),
            "descripcion": _s(r, "description"),
            "invoice_uuid": _s(r, "invoice_uuid"),
            "txn_id": "",
            "cost_center": _s(r, "cost_center"),
            "approver": _s(r, "approver"),
        })
    return pd.DataFrame(rows, columns=_LEDGER_COLS)


def _map_efos(efos) -> pd.DataFrame:
    rows: list[dict] = []
    for _, r in efos.iterrows():
        status = _s(r, "status").strip().capitalize()
        rows.append({
            "rfc": _s(r, "rfc"),
            "nombre": _s(r, "legal_name"),
            "situacion": status,
            "fecha_publicacion": _s(r, "publication_date"),
        })
    return pd.DataFrame(rows, columns=_EFOS_COLS)


def _map_purchase_orders(pos) -> pd.DataFrame:
    rows: list[dict] = []
    for _, r in pos.iterrows():
        rows.append({
            "po_id": _s(r, "po_id"),
            "vendor_rfc": _s(r, "vendor_rfc"),
            "date": _s(r, "date"),
            "amount": _f(r, "amount"),
            "requester": _s(r, "requester"),
            "approver": _s(r, "approver"),
            "description": _s(r, "description"),
        })
    return pd.DataFrame(rows, columns=_PO_COLS)


def _map_contracts(contracts) -> pd.DataFrame:
    rows: list[dict] = []
    for _, r in contracts.iterrows():
        rows.append({
            "contract_id": _s(r, "contract_id"),
            "vendor_rfc": _s(r, "vendor_rfc"),
            "start_date": _s(r, "start_date"),
            "value": _f(r, "value"),
            "scope_text": _s(r, "scope_text"),
        })
    return pd.DataFrame(rows, columns=_CONTRACT_COLS)


def _load_judges(target: Path) -> Dataset:
    """Load a judges' estate (SQLite .db or CSV dir per estate_schema.sql)."""
    tbls = _read_judge_tables(target)
    vendors = tbls.get("vendors", pd.DataFrame())
    invs = tbls.get("invoices", pd.DataFrame())
    bank_txns = tbls.get("bank_txns", pd.DataFrame())
    pos = tbls.get("purchase_orders", pd.DataFrame())
    contracts = tbls.get("contracts", pd.DataFrame())
    employees = tbls.get("employees", pd.DataFrame())
    ledger = tbls.get("ledger", pd.DataFrame())
    efos = tbls.get("efos_list", pd.DataFrame())

    company_rfc, company_clabe = _derive_company(vendors, invs, bank_txns)

    vendors_by_rfc = {_s(v, "rfc"): _s(v, "legal_name") for _, v in vendors.iterrows()}
    vendor_rfc_to_clabe = {_s(v, "rfc"): _s(v, "bank_clabe") for _, v in vendors.iterrows()}
    employees_by_name = _employees_by_name(employees)
    employees_by_clabe = {_s(e, "bank_clabe"): _s(e, "name") for _, e in (employees.iterrows() if len(employees) else [])}

    suppliers = _convert(_map_suppliers(vendors, pos, employees_by_name), "suppliers")
    employees_df = _convert(_map_employees(employees), "employees")
    invoice_df, po_by_uuid, _ = _map_invoices(invs, vendors_by_rfc, company_rfc, pos, ledger, employees_by_name)
    invoice_c = _convert(invoice_df, "invoices")
    purchase_orders_c = _convert(_map_purchase_orders(pos), "purchase_orders")
    goods_receipts_c = _convert(_map_goods_receipts(invoice_df, po_by_uuid, employees_by_name), "goods_receipts")
    bank_c, cp_c, txn_inv = _map_bank(bank_txns, company_clabe, vendors_by_rfc, vendor_rfc_to_clabe, employees_by_clabe, invoice_df)
    bank_c = _convert(bank_c, "bank_transactions")
    cp_c = _convert(cp_c, "counterparty_bank")
    customers_c = _convert(_map_customers(invoice_c, bank_c, vendors_by_rfc), "customers")
    ledger_c = _convert(_map_ledger(ledger), "ledger")
    contracts_c = _convert(_map_contracts(contracts), "contracts")
    efos_c = _convert(_map_efos(efos), "efos_69b")

    record_table: dict[str, str] = dict(txn_inv)
    for u in invoice_c["uuid"]:
        if str(u):
            record_table[str(u)] = "invoices"
    for p in purchase_orders_c["po_id"]:
        if str(p):
            record_table[str(p)] = "purchase_orders"
    for c in contracts_c["contract_id"]:
        if str(c):
            record_table[str(c)] = "contracts"
    for e in ledger_c["entry_id"]:
        if str(e):
            record_table[str(e)] = "ledger"
    for _, v in vendors.iterrows():
        record_table[_s(v, "rfc")] = "vendors"
    for _, e in employees.iterrows():
        record_table[_s(e, "emp_id")] = "employees"
    for _, f in efos.iterrows():
        record_table[_s(f, "rfc")] = "efos_list"

    return Dataset(
        path=target,
        company={"name": company_rfc, "rfc": company_rfc, "clabe": company_clabe, "city": ""},
        suppliers=suppliers,
        customers=customers_c,
        employees=employees_df,
        invoices=invoice_c,
        goods_receipts=goods_receipts_c,
        bank_transactions=bank_c,
        counterparty_bank=cp_c,
        ledger=ledger_c,
        efos_69b=efos_c,
        purchase_orders=purchase_orders_c,
        contracts=contracts_c,
        record_table=record_table,
        source_format="judges",
    )


def load(path: str | Path) -> Dataset:
    """Load a dataset directory into a Dataset. Never touches hidden/.

    Auto-detects the legacy CSV layout, a judges' SQLite ``.db``, or a judges'
    CSV directory (``vendors.csv`` present).
    """
    root = Path(path)
    if root.is_file():
        return _load_judges(root)
    if (root / "suppliers.csv").exists() or (root / "company.json").exists():
        return _load_legacy(root)
    if (root / "vendors.csv").exists():
        return _load_judges(root)
    raise FileNotFoundError(f"No dataset found at {root}: expected a legacy or judges' estate layout")
