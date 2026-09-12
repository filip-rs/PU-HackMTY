"""Human-readable case file (#23) — turns a case-file JSON into markdown a CFO can read.

``case_file.json`` is for the scorer; :func:`render` produces a document an auditor
can defend line by line: one section per finding with the rule broken, the peso
amount, the **tax exposure in pesos**, the **money trail as a dated table** built
from the records the finding cites, and a section listing every lead that was
cleared and why.

Deterministic, no LLM, pure function of the case file and the dataset: every
number is recomputed from the dataset rows for the accused entities, so the
document can be verified against the books. Never reads ``hidden/``.

CLI::

    python -m agent.report <dataset_dir> <case_file.json> [--out case_file.md] [--log runs/<ts>.jsonl]

Exits 1, printing the errors, when ``agent.contract.validate_case_file`` rejects
the file — an invalid case file is never rendered.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .contract import validate_case_file
from .data import Dataset, load

# LISR Art. 9 corporate income tax rate. Stated as an assumption in the document.
ISR_RATE = 0.30
# IVA / VAT rate on the invoices.
IVA_RATE = 0.16

# Plain-words scheme names for the report.
_PLAIN = {
    "efos_fake_supplier": "Fake supplier on the SAT 69-B list",
    "kickback_shell": "Kickback through a related-party shell",
    "round_trip_sales": "Round-trip sales (fictitious revenue)",
    "duplicate_invoice_payment": "Duplicate payment diverted to an unregistered account",
    "other": "Other",
}

_CLABE_WARN = " ⚠ CLABE not on supplier master"


def _money(x: float) -> str:
    return f"{x:,.2f}"


def _fmt_date(d) -> str:
    if d is None or str(d) == "":
        return ""
    try:
        return pd.Timestamp(d).date().isoformat()
    except Exception:
        return str(d)


# --- name resolution ---------------------------------------------------------
def _entity_name(ds: Dataset, eid: str) -> tuple[str, str]:
    """Resolve an S*/C*/E* id to (name, qualifier); qualifier is category/role/city."""
    if len(ds.suppliers):
        sub = ds.suppliers[ds.suppliers["supplier_id"] == eid]
        if len(sub):
            r = sub.iloc[0]
            return str(r["name"]), str(r.get("category", ""))
    if len(ds.customers):
        sub = ds.customers[ds.customers["customer_id"] == eid]
        if len(sub):
            r = sub.iloc[0]
            return str(r["name"]), str(r.get("city", ""))
    if len(ds.employees):
        sub = ds.employees[ds.employees["employee_id"] == eid]
        if len(sub):
            r = sub.iloc[0]
            return str(r["name"]), str(r.get("role", ""))
    return eid, ""


def _describe(eid: str, ds: Dataset) -> str:
    name, qual = _entity_name(ds, eid)
    return f"{name} ({eid}, {qual})" if qual else f"{name} ({eid})"


def _supplier_name(ds: Dataset, sid: str) -> str:
    name, _ = _entity_name(ds, sid)
    return name


def _employee_name(ds: Dataset, eid: str) -> str:
    name, _ = _entity_name(ds, eid)
    return name


# --- exposure ----------------------------------------------------------------
def _accused_of(ds: Dataset, accused: list[str], kind: str) -> list[str]:
    """Accused ids that are actual suppliers/customers/employees."""
    if kind == "supplier":
        ids = set(ds.suppliers["supplier_id"]) if len(ds.suppliers) else set()
    elif kind == "customer":
        ids = set(ds.customers["customer_id"]) if len(ds.customers) else set()
    else:
        ids = set(ds.employees["employee_id"]) if len(ds.employees) else set()
    return [a for a in accused if a in ids]


def _recibida_subtotal_iva(ds: Dataset, supplier_ids: list[str]) -> tuple[float, float]:
    """(sum subtotal, sum iva) over every recibida invoice of the accused suppliers.

    The scheme amount is the full book of the accused supplier(s): a finding
    represents the whole scheme, so its exposure is the supplier's entire
    recibida book, not a subset of cited invoices. A scheme that spans several
    suppliers aggregates across all of them (e.g. EFOS S00030 + S00020).
    """
    if not supplier_ids or len(ds.invoices) == 0:
        return 0.0, 0.0
    rec = ds.invoices[ds.invoices["tipo"] == "recibida"]
    sub = rec[rec["counterparty_id"].isin(supplier_ids)]
    if len(sub) == 0:
        return 0.0, 0.0
    return float(sub["subtotal"].sum()), float(sub["iva"].sum())


def _paid_to_employee(ds: Dataset, employee_ids: list[str]) -> float:
    """Sum of counterparty-bank outflows to the accused employee's personal CLABE."""
    if not employee_ids or len(ds.counterparty_bank) == 0 or len(ds.employees) == 0:
        return 0.0
    total = 0.0
    cp_out = ds.counterparty_bank[ds.counterparty_bank["direction"] == "out"]
    for eid in employee_ids:
        sub = ds.employees[ds.employees["employee_id"] == eid]
        if len(sub) == 0:
            continue
        clabe = str(sub.iloc[0]["personal_clabe"])
        rows = cp_out[cp_out["counterparty_clabe"] == clabe]
        total += float(rows["amount"].sum()) if len(rows) else 0.0
    return total


def _revenue_overstated(ds: Dataset, customer_ids: list[str]) -> float:
    """Sum of subtotal over every emitida invoice to the accused customer."""
    if not customer_ids or len(ds.invoices) == 0:
        return 0.0
    em = ds.invoices[ds.invoices["tipo"] == "emitida"]
    sub = em[em["counterparty_id"].isin(customer_ids)]
    return float(sub["subtotal"].sum()) if len(sub) else 0.0


def _duplicate_cash_loss(ds: Dataset, supplier_ids: list[str]) -> float:
    """Sum over the accused supplier's invoices paid more than once of (payments − total).

    The scheme: an invoice is paid twice; the second payment is the diverted amount.
    """
    if not supplier_ids or len(ds.invoices) == 0 or len(ds.bank_transactions) == 0:
        return 0.0
    rec = ds.invoices[ds.invoices["tipo"] == "recibida"]
    rec = rec[rec["counterparty_id"].isin(supplier_ids)]
    inv_uuids = set(rec["uuid"])
    if not inv_uuids:
        return 0.0
    out = ds.bank_transactions[
        (ds.bank_transactions["direction"] == "out")
        & (ds.bank_transactions["invoice_uuid"].isin(inv_uuids))
    ]
    if len(out) == 0:
        return 0.0
    total = 0.0
    for uuid_, grp in out.groupby("invoice_uuid"):
        inv = rec[rec["uuid"] == uuid_]
        if len(inv) == 0:
            continue
        inv_total = float(inv.iloc[0]["total"])
        paid = float(grp["amount"].sum())
        if len(grp) >= 2:
            total += paid - inv_total
    return total


def exposure(finding: dict, ds: Dataset) -> dict:
    """Compute the scheme's exposure fields (see the table in ISSUES #23)."""
    accused = finding.get("accused", []) or []
    scheme_type = finding.get("scheme_type", "")
    suppliers = _accused_of(ds, accused, "supplier")
    customers = _accused_of(ds, accused, "customer")
    employees = _accused_of(ds, accused, "employee")
    out: dict[str, float] = {}

    if scheme_type in ("efos_fake_supplier", "kickback_shell", "round_trip_sales"):
        subtotal, iva = _recibida_subtotal_iva(ds, suppliers)
        out["isr_deduction_at_risk"] = round(ISR_RATE * subtotal, 2)
        out["iva_credit_at_risk"] = round(iva, 2)

    if scheme_type == "kickback_shell":
        out["paid_to_employee"] = round(_paid_to_employee(ds, employees), 2)

    if scheme_type == "round_trip_sales":
        out["revenue_overstated"] = round(_revenue_overstated(ds, customers), 2)

    if scheme_type == "duplicate_invoice_payment":
        cash = _duplicate_cash_loss(ds, suppliers)
        out["cash_loss"] = round(cash, 2)
        out["isr_deduction_at_risk"] = round(ISR_RATE * cash, 2)

    return out


# --- money trail -------------------------------------------------------------
def _record_kind(record_id: str, ds: Dataset) -> str | None:
    if len(ds.invoices) and (ds.invoices["uuid"] == record_id).any():
        return "invoice"
    if len(ds.bank_transactions) and (ds.bank_transactions["txn_id"] == record_id).any():
        return "txn"
    if len(ds.counterparty_bank) and (ds.counterparty_bank["record_id"] == record_id).any():
        return "cp"
    if len(ds.goods_receipts) and (ds.goods_receipts["receipt_id"] == record_id).any():
        return "receipt"
    return None


def _invoice_row(ds: Dataset, uuid_: str) -> pd.Series | None:
    sub = ds.invoices[ds.invoices["uuid"] == uuid_]
    return sub.iloc[0] if len(sub) else None


def _txn_row(ds: Dataset, txn_id: str) -> pd.Series | None:
    sub = ds.bank_transactions[ds.bank_transactions["txn_id"] == txn_id]
    return sub.iloc[0] if len(sub) else None


def _cp_row(ds: Dataset, record_id: str) -> pd.Series | None:
    sub = ds.counterparty_bank[ds.counterparty_bank["record_id"] == record_id]
    return sub.iloc[0] if len(sub) else None


def _gr_row(ds: Dataset, receipt_id: str) -> pd.Series | None:
    sub = ds.goods_receipts[ds.goods_receipts["receipt_id"] == receipt_id]
    return sub.iloc[0] if len(sub) else None


def _receipt_note(ds: Dataset, invoice_uuid: str) -> str:
    gr = ds.goods_receipts[ds.goods_receipts["invoice_uuid"] == invoice_uuid]
    if len(gr):
        return f"receipt {str(gr.iloc[0]['receipt_id'])}"
    return "no goods receipt"


def _clabe_warning(ds: Dataset, txn) -> str:
    """Append the CLABE warning when the TX pays a clabe other than the supplier's master."""
    inv_uuid = str(txn.get("invoice_uuid", ""))
    if not inv_uuid:
        return ""
    row = _invoice_row(ds, inv_uuid)
    if row is None:
        return ""
    sid = str(row["counterparty_id"])
    if sid not in set(ds.suppliers["supplier_id"]):
        return ""
    seg = ds.suppliers[ds.suppliers["supplier_id"] == sid]
    if len(seg) == 0:
        return ""
    master = str(seg.iloc[0]["clabe"])
    if str(txn.get("counterparty_clabe", "")) != master:
        return _CLABE_WARN
    return ""


def _employee_clabe_note(ds: Dataset, clabe: str) -> str:
    """' = personal CLABE of <name> (<role>)' when a counterparty clabe is an employee's."""
    if not clabe or len(ds.employees) == 0:
        return ""
    sub = ds.employees[ds.employees["personal_clabe"] == clabe]
    if len(sub) == 0:
        return ""
    r = sub.iloc[0]
    return f" = personal CLABE of {r['name']} ({r['role']})"


def _company_name(ds: Dataset) -> str:
    return str(ds.company.get("name", ""))


def _build_trail_row(step: int, fecha, kind: str, record_id: str, _from: str, _to: str, amount: float, note: str) -> dict:
    return {
        "step": step,
        "fecha": _fmt_date(fecha),
        "kind": kind,
        "record_id": record_id,
        "from": _from,
        "to": _to,
        "amount_mxn": round(amount, 2),
        "note": note,
    }


def money_trail(finding: dict, ds: Dataset) -> list[dict]:
    """One row per cited record, sorted by (fecha, record_id)."""
    company = _company_name(ds)
    rows: list[dict] = []
    for record_id in finding.get("evidence", []) or []:
        kind = _record_kind(record_id, ds)
        if kind == "invoice":
            row = _invoice_row(ds, record_id)
            if row is None:
                continue
            tipo = str(row["tipo"])
            if tipo == "recibida":
                sid = str(row["counterparty_id"])
                rows.append(
                    _build_trail_row(
                        0, row["fecha"], "invoice", record_id,
                        _supplier_name(ds, sid), company, float(row["total"]),
                        f"{row['descripcion']} — {_receipt_note(ds, record_id)}",
                    )
                )
            else:  # emitida
                cid = str(row["counterparty_id"])
                cname, _ = _entity_name(ds, cid)
                rows.append(
                    _build_trail_row(
                        0, row["fecha"], "invoice", record_id,
                        company, cname, float(row["total"]), str(row["descripcion"]),
                    )
                )
        elif kind == "txn":
            row = _txn_row(ds, record_id)
            if row is None:
                continue
            direction = str(row["direction"])
            amount = float(row["amount"])
            note = str(row.get("reference", "")) or ""
            note += _clabe_warning(ds, row)
            if direction == "out":
                rows.append(
                    _build_trail_row(
                        0, row["fecha"], "txn", record_id,
                        company, str(row["counterparty_name"]), amount, note,
                    )
                )
            else:
                rows.append(
                    _build_trail_row(
                        0, row["fecha"], "txn", record_id,
                        str(row["counterparty_name"]), company, amount, note,
                    )
                )
        elif kind == "cp":
            row = _cp_row(ds, record_id)
            if row is None:
                continue
            note = str(row.get("reference", "")) or ""
            note += _employee_clabe_note(ds, str(row.get("counterparty_clabe", "")))
            rows.append(
                _build_trail_row(
                    0, row["fecha"], "cp", record_id,
                    str(row["entity_name"]), str(row["counterparty_name"]),
                    float(row["amount"]), note,
                )
            )
        elif kind == "receipt":
            row = _gr_row(ds, record_id)
            if row is None:
                continue
            rows.append(
                _build_trail_row(
                    0, row["fecha"], "receipt", record_id,
                    _supplier_name(ds, str(row["supplier_id"])), str(row["warehouse"]),
                    float(row["cantidad"]) if row.get("cantidad") is not None else 0.0,
                    _employee_name(ds, str(row["received_by"])),
                )
            )

    rows.sort(key=lambda r: (r["fecha"], r["record_id"]))
    for i, r in enumerate(rows, 1):
        r["step"] = i
    return rows


def _trail_table(rows: list[dict]) -> str:
    header = "| # | Date | Kind | Record | From | To | Amount (MXN) | Note |"
    sep = "|---:|---|---|---|---|---:|---|"
    lines = [header, sep]
    for r in rows:
        lines.append(
            f"| {r['step']} | {r['fecha']} | {r['kind']} | {r['record_id']} "
            f"| {r['from']} | {r['to']} | {_money(r['amount_mxn'])} | {r['note']} |"
        )
    return "\n".join(lines)


def _group_evidence(evidence: list[str], ds: Dataset) -> list[tuple[str, list[str]]]:
    """Group evidence by kind (invoices, bank transactions, counterparty records, receipts)."""
    groups: dict[str, list[str]] = {}
    for e in evidence:
        kind = _record_kind(e, ds) or "unknown"
        groups.setdefault(kind, []).append(e)
    order = ["invoice", "txn", "cp", "receipt", "unknown"]
    labels = {
        "invoice": "Invoices",
        "txn": "Bank transactions",
        "cp": "Counterparty records",
        "receipt": "Goods receipts",
        "unknown": "Other",
    }
    out = []
    for kind in order:
        if kind in groups:
            out.append((labels[kind], sorted(groups[kind])))
    return out


# --- render ------------------------------------------------------------------
def _primary_exposure(expo: dict) -> str:
    for key in ("isr_deduction_at_risk", "paid_to_employee", "revenue_overstated", "cash_loss"):
        if key in expo:
            return _money(expo[key])
    return "—"


def _exposure_lines(finding: dict, ds: Dataset, expo: dict) -> list[str]:
    st = finding.get("scheme_type", "")
    lines: list[str] = []
    if "isr_deduction_at_risk" in expo:
        suppliers = _accused_of(ds, finding.get("accused", []), "supplier")
        subtotal, _iva = _recibida_subtotal_iva(ds, suppliers)
        if st == "duplicate_invoice_payment":
            lines.append(
                f"ISR deduction at risk: MXN {_money(expo['isr_deduction_at_risk'])} "
                f"(30% of the MXN {_money(expo['cash_loss'])} duplicated payment)"
            )
        else:
            lines.append(
                f"ISR deduction at risk: MXN {_money(expo['isr_deduction_at_risk'])} "
                f"(30% of MXN {_money(subtotal)} subtotal)"
            )
    if "iva_credit_at_risk" in expo:
        lines.append(f"IVA credit at risk: MXN {_money(expo['iva_credit_at_risk'])} (16% of numerator)")
    if "paid_to_employee" in expo:
        lines.append(f"Paid to employee: MXN {_money(expo['paid_to_employee'])}")
    if "revenue_overstated" in expo:
        lines.append(f"Revenue overstated: MXN {_money(expo['revenue_overstated'])}")
    if "cash_loss" in expo:
        lines.append(f"Cash loss: MXN {_money(expo['cash_loss'])}")
    return lines


def _finding_section(idx: int, finding: dict, ds: Dataset, expo: dict) -> str:
    st = finding.get("scheme_type", "")
    title = _PLAIN.get(st, "Other")
    parts: list[str] = [f"## Finding {idx} — {title}", ""]

    accused = finding.get("accused", []) or []
    names = "; ".join(_describe(a, ds) for a in accused)
    parts.append(f"**Accused:** {names}")
    parts.append("")
    parts.append(f"**Rule broken:** {finding.get('rule', '')}")
    parts.append("")
    parts.append(f"**Amount:** MXN {_money(finding.get('amount_mxn', 0.0))}")
    parts.append("")
    parts.append("**Exposure:**")
    for line in _exposure_lines(finding, ds, expo):
        parts.append(f"- {line}")
    parts.append("")

    if finding.get("narrative"):
        parts.append(f"**Narrative:** {finding['narrative']}")
        parts.append("")

    parts.append("**Money trail:**")
    trail = money_trail(finding, ds)
    if trail:
        parts.append(_trail_table(trail))
        parts.append("")
    else:
        parts.append("No cited record resolved to a dated movement.")
        parts.append("")

    parts.append("**Evidence:**")
    for label, ids in _group_evidence(finding.get("evidence", []), ds):
        parts.append(f"- {label}: {', '.join(ids)}")
    parts.append("")
    return "\n".join(parts)


def _trace_lines(log: list[dict], ds: Dataset) -> list[str]:
    out: list[str] = []
    for entry in log:
        kind = entry.get("kind")
        payload = entry.get("payload") or {}
        eid = entry.get("entity_id", "")
        if not eid:
            continue
        name = _describe(eid, ds) if eid else ""
        if kind == "decision":
            action = payload.get("action", "")
            if action == "record_finding":
                finding = payload.get("finding") or {}
                out.append(f"- {name}: recorded a finding — {finding.get('scheme_type', '')} MXN {_money(finding.get('amount_mxn', 0.0))}")
            elif action == "drop_lead":
                out.append(f"- {name}: dropped the lead — {payload.get('reason', '')}")
            else:
                out.append(f"- {name}: {action} — {payload.get('reason', '')}")
        elif kind == "guard":
            finding = payload.get("finding") or {}
            accepted = payload.get("accepted")
            if accepted:
                out.append(f"- {name}: guard accepted — {finding.get('scheme_type', '')} MXN {_money(finding.get('amount_mxn', 0.0))}")
            else:
                reasons = payload.get("reasons") or []
                out.append(f"- {name}: guard rejected — {'; '.join(str(r) for r in reasons)}")
    return out


def render(
    case: dict,
    ds: Dataset,
    *,
    log: list[dict] | None = None,
    generated_at: str | None = None,
) -> str:
    """Render the case file as a markdown document. Pure function, no LLM."""
    company = _company_name(ds)
    rfc = str(ds.company.get("rfc", ""))
    findings = case.get("findings", [])
    not_pursued = case.get("not_pursued", [])

    # Fiscal year from the invoice date range.
    if len(ds.invoices):
        dates = ds.invoices["fecha"].dropna()
        year_min = _fmt_date(dates.min())[:4]
        year_max = _fmt_date(dates.max())[:4]
        fiscal_year = f"{year_min}–{year_max}" if year_min and year_max else ""
    else:
        fiscal_year = ""

    generated_at = generated_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    parts: list[str] = []
    parts.append(f"# {company} — Forensic audit case file")
    parts.append("")
    parts.append(f"**RFC:** {rfc} · **Fiscal year:** {fiscal_year}")
    parts.append(f"**Generated at:** {generated_at}")
    parts.append("")

    total_amount = sum(float(f.get("amount_mxn", 0.0)) for f in findings)
    parts.append(
        f"This case file documents **{len(findings)}** finding(s) totalling "
        f"**MXN {_money(total_amount)}**, and **{len(not_pursued)}** lead(s) that "
        f"were examined and cleared."
    )
    parts.append("")

    # Summary table
    parts.append("## Summary")
    parts.append("")
    parts.append("| # | Scheme | Accused | Amount (MXN) | Main exposure |")
    parts.append("|---:|---|---|---:|---|")
    for i, f in enumerate(findings, 1):
        st = f.get("scheme_type", "")
        expo = exposure(f, ds)
        acc_names = "; ".join(_describe(a, ds) for a in (f.get("accused", []) or []))
        parts.append(
            f"| {i} | {_PLAIN.get(st, 'Other')} | {acc_names} "
            f"| {_money(f.get('amount_mxn', 0.0))} | {_primary_exposure(expo)} |"
        )
    parts.append("")

    for i, f in enumerate(findings, 1):
        expo = exposure(f, ds)
        parts.append(_finding_section(i, f, ds, expo))

    parts.append("## Leads not pursued")
    parts.append("")
    parts.append("| Entity | Reason |")
    parts.append("|---|---|")
    for row in not_pursued:
        parts.append(f"| {_describe(row['entity'], ds)} | {row.get('reason', '')} |")
    parts.append("")

    parts.append("## Method")
    parts.append("")
    parts.append(
        "The investigation runs deterministic detectors over the books to surface leads, "
        "forms a hypothesis per lead, then resolves it through data tools that return "
        "record IDs, and passes every accusation through an evidence guard that rejects "
        "anything lacking a recognised rule, a peso amount consistent with the accused "
        "entities' records (25% tolerance), and evidence IDs that exist and belong to the "
        "accused. The ISR rate (30%, LISR Art. 9) and IVA rate (16%) are stated assumptions."
    )
    parts.append("")
    parts.append(
        "What the books cannot prove: the materiality of a service with no underlying "
        "contract, and the identity of counterparties beyond the statements recorded in "
        "the counterparty bank ledger."
    )
    parts.append("")

    if log:
        parts.append("## Investigation trace")
        parts.append("")
        lines = _trace_lines(log, ds)
        if lines:
            parts.extend(lines)
        else:
            parts.append("No decision or guard events in the supplied log.")
        parts.append("")

    return "\n".join(parts).strip() + "\n"


# --- CLI ---------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="python -m agent.report")
    parser.add_argument("dataset_dir")
    parser.add_argument("case_file")
    parser.add_argument("--out", default=None)
    parser.add_argument("--log", default=None)
    args = parser.parse_args(argv)

    case_path = Path(args.case_file)
    out_path = Path(args.out) if args.out else case_path.with_suffix(".md")

    ds = load(args.dataset_dir)
    try:
        case = json.loads(case_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"{args.case_file}: invalid JSON: {exc}", file=sys.stderr)
        return 1

    errors = validate_case_file(case, ds)
    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1

    log = None
    if args.log:
        log_path = Path(args.log)
        if log_path.exists():
            log = []
            for line in log_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    log.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    doc = render(case, ds, log=log)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
