"""agent/clear.py — grounds the "why we did NOT accuse" reasons in the records (#69).

The investigation loop drops every lead without a scheme signature. Historically
that produced one canned sentence per detector, written without looking at the
data, so on a judge's hand-edited dataset it could be *false*, and the honest
answer to "how do you know?" was "it is hard-coded". This module replaces those
clauses with pure pandas checks that return a readable reason **with record IDs**
when the innocent explanation actually holds, and ``None`` when it cannot be
confirmed from the books. A ``None`` becomes an honest ``"unverified: ..."``
reason in ``not_pursued`` (and, in #70, an escalation to the model).

``agent.investigate._drop_reason`` drives it: for each detector on a dossier it
calls :func:`clear_reason`; if every call returns a sentence the entity is
*cleared* (all reasons joined with ``"; "``), otherwise the entity is
*unverified*.

Pure and deterministic: no I/O, no LLM, never reads ``hidden/``. Unknown
detector -> ``None`` (never raises).
"""
from __future__ import annotations

from typing import Callable

from .data import Dataset
from .rules import _active_69b_supplier_ids

# Categories that never carry a goods receipt by generator construction.
_SERVICE_CATEGORIES = {"servicios", "logistica", "renta_util"}
# Categories that *should* carry a goods receipt; a missing one is a red flag.
_GOODS_CATEGORIES = {"consumibles", "materia_prima", "refacciones"}

_CATEGORY_LABEL = {
    "servicios": "service",
    "logistica": "logistics",
    "renta_util": "rental",
    "consumibles": "consumables",
    "materia_prima": "raw material",
    "refacciones": "spare parts",
}


# --- formatting helpers -----------------------------------------------------
def _fmt_mxn(value) -> str:
    """Format a peso amount as ``MXN 1,234.56``."""
    try:
        return f"MXN {float(value):,.2f}"
    except (TypeError, ValueError):
        return "MXN 0.00"


def _ids_text(ids: list[str], n: int = 3) -> str:
    """First ``n`` IDs joined with ', '; append ' and N more' when more exist."""
    ids = [str(i) for i in ids]
    if not ids:
        return ""
    if len(ids) <= n:
        return ", ".join(ids)
    return ", ".join(ids[:n]) + f" and {len(ids) - n} more"


def _supplier_row(ds: Dataset, entity_id: str):
    """The suppliers row for ``entity_id`` or ``None`` if it is not a supplier."""
    if len(ds.suppliers) == 0:
        return None
    sub = ds.suppliers[ds.suppliers["supplier_id"].astype(str) == str(entity_id)]
    return sub.iloc[0] if len(sub) else None


def _recibida(ds: Dataset, entity_id: str):
    """``recibida`` invoices of the supplier ``entity_id``."""
    if len(ds.invoices) == 0:
        return ds.invoices
    return ds.invoices[
        (ds.invoices["tipo"] == "recibida")
        & (ds.invoices["counterparty_id"].astype(str) == str(entity_id))
    ]


def _receipt_ids_for(ds: Dataset, invoice_uuids) -> list[str]:
    """goods_receipt ``receipt_id``s for the given invoice UUIDs."""
    uuids = {str(u) for u in invoice_uuids}
    if not uuids or len(ds.goods_receipts) == 0:
        return []
    sub = ds.goods_receipts[ds.goods_receipts["invoice_uuid"].astype(str).isin(uuids)]
    return sorted({str(r) for r in sub["receipt_id"]})


def _largest_invoice(ds: Dataset, entity_id: str):
    """The largest ``total`` recibida invoice of the supplier, or None."""
    invs = _recibida(ds, entity_id)
    if len(invs) == 0:
        return None
    row = invs.sort_values("total", ascending=False).iloc[0]
    return {
        "uuid": str(row["uuid"]),
        "total": float(row["total"]),
        "descripcion": str(row.get("descripcion", "") or ""),
        "approved_by": str(row.get("approved_by", "") or ""),
        "tipo": str(row.get("tipo", "") or ""),
    }


# --- 69-B / bank helpers ------------------------------------------------------
def _rfc_live_69b(ds: Dataset, entity_id: str) -> bool:
    """Is this supplier's RFC on the 69-B list in a live state?"""
    return str(entity_id) in _active_69b_supplier_ids(ds)


def _address_matches_employee_home(ds: Dataset, street, city) -> bool:
    if len(ds.employees) == 0:
        return False
    sub = ds.employees[
        (ds.employees["home_street"].astype(str) == str(street))
        & (ds.employees["home_city"].astype(str) == str(city))
    ]
    return len(sub) > 0


def _outflow_to_employee(ds: Dataset, entity_clabe) -> bool:
    if len(ds.counterparty_bank) == 0 or len(ds.employees) == 0:
        return False
    emp_clabes = {str(c) for c in ds.employees["personal_clabe"]}
    if not emp_clabes:
        return False
    out = ds.counterparty_bank[
        (ds.counterparty_bank["entity_clabe"].astype(str) == str(entity_clabe))
        & (ds.counterparty_bank["direction"].astype(str) == "out")
    ]
    if len(out) == 0:
        return False
    return any(str(c) in emp_clabes for c in out["counterparty_clabe"])


def _has_employee_link(ds: Dataset, supplier_row) -> bool:
    """True when the address matches an employee home OR money flows to an employee."""
    if _address_matches_employee_home(ds, supplier_row["street"], supplier_row["city"]):
        return True
    return _outflow_to_employee(ds, supplier_row["clabe"])


# --- per-detector checks ------------------------------------------------------
def _clear_name_twin_69b(entity_id: str, leads: list[dict], ds: Dataset) -> str | None:
    row = _supplier_row(ds, entity_id)
    if row is None:
        return None
    rfc = str(row["rfc"])
    # Reuse the tool's 69-B resolution rather than re-implementing the logic.
    from .tools import Tools

    info = Tools(ds).check_69b(rfc)
    if info.get("listed"):
        return None
    matches = info.get("name_matches", []) or []
    twins = "; ".join(
        f"{m['rfc']} ({m['nombre']}, {m['situacion']})"
        for m in matches
        if m.get("rfc")
    )
    invs = _recibida(ds, entity_id)
    uuids = set(invs["uuid"])
    rec_ids = _receipt_ids_for(ds, uuids)
    receipt_txt = ""
    if rec_ids:
        receipt_txt = f"; {len(rec_ids)} of {len(invs)} invoices have goods receipts"
    if twins:
        return (
            f"the 69-B list is matched on RFC, not on name — the supplier's RFC {rfc} "
            f"is not listed; its name twin on 69-B is {twins}; NOT this supplier{receipt_txt}"
        )
    return (
        f"the 69-B list is matched on RFC, not on name — the supplier's RFC {rfc} "
        f"is not on the list{receipt_txt}"
    )


def _clear_shared_supplier_address(entity_id: str, leads: list[dict], ds: Dataset) -> str | None:
    row = _supplier_row(ds, entity_id)
    if row is None:
        return None
    if _address_matches_employee_home(ds, row["street"], row["city"]):
        return None
    if _outflow_to_employee(ds, row["clabe"]):
        return None
    street = str(row["street"])
    # The other suppliers sharing this address (the reason it is not a red flag).
    siblings = ds.suppliers[
        (ds.suppliers["street"].astype(str) == street)
        & (ds.suppliers["city"].astype(str) == str(row["city"]))
        & (ds.suppliers["supplier_id"].astype(str) != str(entity_id))
    ]
    sibling_txt = ""
    if len(siblings):
        parts = [f"{s['supplier_id']} ({s['name']})" for _, s in siblings.iterrows()]
        sibling_txt = f" with {_ids_text(parts)}"
    invs = _recibida(ds, entity_id)
    rec_ids = _receipt_ids_for(ds, set(invs["uuid"]))
    rec_txt = ""
    if len(invs):
        rec_txt = f"; {len(rec_ids)} of {len(invs)} invoices have goods receipts"
    if rec_ids:
        rec_txt += f" ({_ids_text(rec_ids)})"
    return (
        f"shares its address ({street}){sibling_txt}; it matches no employee's home "
        f"and its bank statement shows no outflow to an employee account{rec_txt}"
    )


def _services_no_receipt_reason(entity_id: str, leads: list[dict], ds: Dataset) -> str | None:
    """Shared logic for ``detect_no_receipt`` and ``detect_fast_pay_no_deliverable``."""
    row = _supplier_row(ds, entity_id)
    if row is None:
        return None
    category = str(row["category"])
    # A goods category with missing receipts is a genuine red flag: not innocent.
    if category in _GOODS_CATEGORIES:
        return None
    if category not in _SERVICE_CATEGORIES:
        return None
    if _rfc_live_69b(ds, entity_id):
        return None
    if _has_employee_link(ds, row):
        return None
    invs = _recibida(ds, entity_id)
    if len(invs) == 0:
        return None
    largest = _largest_invoice(ds, entity_id)
    label = _CATEGORY_LABEL.get(category, category)
    noun = f"{len(invs)} {label} invoice{'s' if len(invs) != 1 else ''}"
    if largest:
        noun = (
            f"{noun}, the largest ({largest['uuid']}, {_fmt_mxn(largest['total'])}) "
            f"describing '{largest['descripcion']}', approved by {largest['approved_by']}"
        )
    rfc = str(row["rfc"])
    return (
        f"{noun}; {label} deliveries carry no goods receipt (LISR deductible regardless); "
        f"RFC {rfc} is not on the 69-B list"
    )


def _clear_cash_payments(entity_id: str, leads: list[dict], ds: Dataset) -> str | None:
    row = _supplier_row(ds, entity_id)
    if row is None:
        return None
    invs = _recibida(ds, entity_id)
    if len(invs) == 0:
        return None
    cash = invs[invs["forma_pago"].astype(str) == "01"]
    if len(cash) == 0:
        return None
    if (cash["total"].astype(float) > 2000.0).any():
        return None
    by_uuid = ds.goods_receipts
    if len(by_uuid) == 0:
        return None
    have = set(by_uuid["invoice_uuid"].astype(str))
    if not all(str(u) in have for u in cash["uuid"]):
        return None
    largest = float(cash["total"].astype(float).max())
    rec_ids = _receipt_ids_for(ds, set(cash["uuid"]))
    return (
        f"{len(cash)} cash invoice{'s' if len(cash) != 1 else ''}, the largest "
        f"{_fmt_mxn(largest)}, all under the MXN 2,000 deductibility cap (LISR Art. 27-III), "
        f"goods received ({_ids_text(rec_ids)})"
    )


def _clear_strong(entity_id: str, leads: list[dict], ds: Dataset) -> str | None:
    """A strong (scheme-defining) detector with no complete signature is never cleared."""
    return None


# --- judge-estate checks (#94) ------------------------------------------------
# On a judges' estate the documents that clear a lead are purchase orders, a
# standing contract and the bank code, not a goods receipt and a home address.
# Each check is a pure predicate that returns ``(verified, reason, records)``:
# ``verified`` is True exactly when the innocent explanation actually holds, the
# ``reason`` names record IDs, and ``records`` is the list of records that prove it.


def _po_approver_name(ds: Dataset, row, list_fallback: bool = False) -> str:
    """The name that approved the vendor's POs, or the invoice-level approver id."""
    if len(ds.purchase_orders):
        rfc = str(row["rfc"])
        sub = ds.purchase_orders[ds.purchase_orders["vendor_rfc"].astype(str) == rfc]
        names = [str(a) for a in sub["approver"] if str(a)]
        if names:
            return names[0]
    return str(row.get("approved_by", "") or "")


def po_trail(entity_id: str, ds: Dataset) -> tuple[bool, str, list[str]]:
    """Share of the vendor's ``recibida`` invoices with a purchase order.

    On a judges' estate a PO is the only deliverable trail, so an invoice that
    was ordered has one; on our legacy layout ``goods_receipts`` (or the invoice's
    own ``po_number``) is the proxy. Clears ``detect_no_receipt`` /
    ``detect_fast_pay_no_deliverable`` when at least 80% of the invoices have a PO.
    """
    row = _supplier_row(ds, entity_id)
    if row is None:
        return False, "", []
    invs = _recibida(ds, entity_id)
    if len(invs) == 0:
        return False, "", []
    uuids = set(invs["uuid"].astype(str))
    have: set[str] = set()
    po_map: dict[str, str] = {}
    if len(ds.purchase_orders) and "po_number" in invs.columns:
        for u, pn in zip(invs["uuid"].astype(str), invs["po_number"].astype(str)):
            if pn:
                have.add(u)
                po_map[u] = pn
    if len(ds.goods_receipts):
        gr = ds.goods_receipts[ds.goods_receipts["invoice_uuid"].astype(str).isin(uuids)]
        for u, rid in zip(gr["invoice_uuid"].astype(str), gr["receipt_id"].astype(str)):
            have.add(u)
            po_map.setdefault(u, rid)
    if not have:
        return False, "", []
    if len(have) / len(invs) < 0.80:
        return False, "", []
    po_ids = sorted({po_map[u] for u in have})
    approver = _po_approver_name(ds, row)
    noun = f"purchase order{'' if len(po_ids) == 1 else 's'} {_ids_text(po_ids)}"
    who = f", approved by {approver}" if approver else ""
    return (
        True,
        f"{len(have)}/{len(invs)} invoices have {noun}{who}",
        po_ids,
    )


def _contract_row(ds: Dataset, entity_id: str):
    """The contract(s) covering this vendor, matched by the supplier's RFC."""
    row = _supplier_row(ds, entity_id)
    if row is None or len(ds.contracts) == 0:
        return row, None
    rfc = str(row["rfc"])
    sub = ds.contracts[ds.contracts["vendor_rfc"].astype(str) == rfc]
    if len(sub) == 0:
        return row, None
    return row, sub.iloc[0]


def contract_on_file(entity_id: str, ds: Dataset) -> tuple[bool, str, list[str]]:
    """A standing contract that fixes the monthly fee explains repeated equal invoices.

    Clears ``detect_new_vendor_round_amounts`` and ``detect_threshold_splitting``
    leads when a contract covers the vendor and the invoice amounts match
    ``value / 12`` within 5%.
    """
    row, c = _contract_row(ds, entity_id)
    if row is None or c is None:
        return False, "", []
    invs = _recibida(ds, entity_id)
    if len(invs) == 0:
        return False, "", []
    try:
        monthly = float(c["value"]) / 12.0
    except (TypeError, ValueError):
        return False, "", []
    if monthly <= 0:
        return False, "", []
    totals = [float(t) for t in invs["total"]]
    if any(abs(t - monthly) > 0.05 * monthly for t in totals):
        return False, "", []
    cid = str(c["contract_id"])
    return (
        True,
        f"contract {cid} (fixed monthly fee {_fmt_mxn(monthly)}) explains "
        f"{len(totals)} equal invoice{'s' if len(totals) != 1 else ''}",
        [cid],
    )


def _employee_bank_code(ds: Dataset, emp_ids: list[str]) -> list[str]:
    """Employee ids whose accounts share a bank code, with the vendor's own excluded."""
    return [str(e) for e in emp_ids]


def same_bank_only(entity_id: str, ds: Dataset) -> tuple[bool, str, list[str]]:
    """A vendor that banks at the same institution as an employee is not a kickback.

    Clears ``detect_kickback_outflow``-adjacent leads and any vendor whose CLABE
    shares a bank code with an employee when the accounts differ and no transfer
    ever passes between them.
    """
    row = _supplier_row(ds, entity_id)
    if row is None or len(ds.employees) == 0:
        return False, "", []
    clabe = str(row["clabe"])
    if not clabe:
        return False, "", []
    bank = clabe[:3]
    emp = ds.employees
    shared = emp[emp["personal_clabe"].astype(str).str[:3] == bank]
    shared = shared[shared["personal_clabe"].astype(str) != clabe]
    if len(shared) == 0:
        return False, "", []
    # A real kickback moves money to an employee's account; that is not "same bank
    # only", so it must still be a lead. Prefer the vendor's own approver (the buyer)
    # when they share the bank code, so the reason names the co-actor, not a bystander.
    emp_ids = sorted({str(e) for e in shared["employee_id"]})
    if _outflow_to_employee(ds, clabe):
        return False, "", []
    approver = str(row.get("approved_by", "") or "")
    named = [a for a in emp_ids if a == approver] or emp_ids
    who = _ids_text(named)
    return (
        True,
        f"bank code {bank} shared with {who}, accounts differ, "
        f"no transfer between them in bank_txns",
        emp_ids,
    )


def cancelled_reversed(entity_id: str, ds: Dataset) -> tuple[bool, str, list[str]]:
    """Every cancelled sale invoice has a reversing 4000 debit.

    Clears ``detect_revenue_inflation`` leads when every invoice a customer
    cancelled was also fully reversed in the ledger (a chargeback, not a fictitious
    sale). ``entity_id`` is a customer on the sales side.
    """
    if len(ds.invoices) == 0:
        return False, "", []
    sales = ds.invoices[ds.invoices["tipo"].astype(str) == "emitida"] if "tipo" in ds.invoices else ds.invoices
    sub = sales[sales["counterparty_id"].astype(str) == str(entity_id)]
    if len(sub) == 0:
        return False, "", []
    cancelled = sub[sub["status"].astype(str) == "cancelado"] if "status" in sub.columns else sub.iloc[0:0]
    if len(cancelled) == 0:
        return False, "", []
    c_uuids = set(cancelled["uuid"].astype(str))
    reversed_uuids: set[str] = set()
    if len(ds.ledger):
        acct = ds.ledger[ds.ledger["account_code"].astype(str) == "4000"]
        if len(acct):
            rev = acct[acct["debit"].astype(float) > 0]
            reversed_uuids = set(rev["invoice_uuid"].astype(str))
    if not c_uuids <= reversed_uuids:
        return False, "", []
    entry_ids = sorted(
        str(e) for e in ds.ledger[
            ds.ledger["invoice_uuid"].astype(str).isin(c_uuids)
            & (ds.ledger["account_code"].astype(str) == "4000")
            & (ds.ledger["debit"].astype(float) > 0)
        ]["entry_id"]
    )
    return (
        True,
        f"every cancelled invoice ({_ids_text(sorted(c_uuids))}) has a reversing 4000 debit "
        f"({_ids_text(entry_ids)})",
        sorted(c_uuids),
    )


def presunto_only(entity_id: str, ds: Dataset) -> tuple[bool, str, list[str]]:
    """A ''presunto'' (presumed, not confirmed) 69-B listing stays a lead.

    Never clears, but the reason says the status and the publication date so the
    reader can tell a presumed listing from a sanctioned one.
    """
    row = _supplier_row(ds, entity_id)
    if row is None or len(ds.efos_69b) == 0:
        return False, "", []
    rfc = str(row["rfc"])
    sub = ds.efos_69b[ds.efos_69b["rfc"].astype(str) == rfc]
    if len(sub) == 0:
        return False, "", []
    status = str(sub.iloc[0]["situacion"]).strip()
    published = str(sub.iloc[0].get("fecha_publicacion", "") or "").strip()
    if "presunt" not in status.lower():
        return False, "", []
    date_txt = f"published {published}" if published else "no publication date on file"
    return (
        False,
        f"the 69-B listing status is '{status}' ({date_txt}); presumed, not confirmed",
        [rfc],
    )


# --- judge-estate per-detector handlers ---------------------------------------
def _clear_no_receipt(entity_id: str, leads: list[dict], ds: Dataset) -> str | None:
    v, r, _recs = po_trail(entity_id, ds)
    if v:
        return r
    return _services_no_receipt_reason(entity_id, leads, ds)


def _clear_fast_pay_no_deliverable(entity_id: str, leads: list[dict], ds: Dataset) -> str | None:
    v, r, _recs = po_trail(entity_id, ds)
    if v:
        return r
    return _services_no_receipt_reason(entity_id, leads, ds)


def _clear_new_vendor_round_amounts(entity_id: str, leads: list[dict], ds: Dataset) -> str | None:
    v, r, _recs = contract_on_file(entity_id, ds)
    if v:
        return r
    return _clear_new_vendor_round_amounts_legacy(entity_id, leads, ds)


def _clear_new_vendor_round_amounts_legacy(entity_id: str, leads: list[dict], ds: Dataset) -> str | None:
    row = _supplier_row(ds, entity_id)
    if row is None:
        return None
    if _rfc_live_69b(ds, entity_id):
        return None
    invs = _recibida(ds, entity_id)
    if len(invs) == 0:
        return None
    uuids = set(invs["uuid"])
    rec_ids = _receipt_ids_for(ds, uuids)
    # Innocent iff every invoice has at least one goods receipt.
    by_uuid = ds.goods_receipts  # count receipts per invoice
    if len(by_uuid) == 0:
        return None
    have = set(by_uuid["invoice_uuid"].astype(str))
    if not all(str(u) in have for u in uuids):
        return None
    rfc = str(row["rfc"])
    return (
        f"new vendor with round amounts, but all {len(invs)} invoices have "
        f"warehouse-signed goods receipts ({_ids_text(rec_ids)}) and RFC {rfc} is not on the 69-B list"
    )


def _clear_threshold_splitting(entity_id: str, leads: list[dict], ds: Dataset) -> str | None:
    v, r, _recs = contract_on_file(entity_id, ds)
    return r if v else None


def _clear_revenue_inflation(entity_id: str, leads: list[dict], ds: Dataset) -> str | None:
    v, r, _recs = cancelled_reversed(entity_id, ds)
    return r if v else None


def _clear_kickback_outflow(entity_id: str, leads: list[dict], ds: Dataset) -> str | None:
    v, r, _recs = same_bank_only(entity_id, ds)
    return r if v else None


def _clear_presunto_efos(entity_id: str, leads: list[dict], ds: Dataset) -> str | None:
    """A ''presunto'' 69-B listing is not confirmed; keep it a lead (#94)."""
    v, r, _recs = presunto_only(entity_id, ds)
    return r if v else None


# --- dispatch ---------------------------------------------------------------
_DISPATCH: dict[str, Callable[[str, list[dict], Dataset], str | None]] = {
    "detect_new_vendor_round_amounts": _clear_new_vendor_round_amounts,
    "detect_name_twin_69b": _clear_name_twin_69b,
    "detect_shared_supplier_address": _clear_shared_supplier_address,
    "detect_no_receipt": _clear_no_receipt,
    "detect_fast_pay_no_deliverable": _clear_fast_pay_no_deliverable,
    "detect_cash_payments": _clear_cash_payments,
    # Judge-estate checks (#94): POs, contracts, same bank code, cancellations.
    "detect_threshold_splitting": _clear_threshold_splitting,
    "detect_revenue_inflation": _clear_revenue_inflation,
    "detect_kickback_outflow": _clear_kickback_outflow,
    "detect_efos": _clear_presunto_efos,
    # Strong detectors never clear a lead without a complete scheme signature.
    "detect_employee_address_match": _clear_strong,
    "detect_round_trip": _clear_strong,
    "detect_duplicate_payments": _clear_strong,
    "detect_clabe_not_on_master": _clear_strong,
}


def clear_reason(detector: str, entity_id: str, leads: list[dict], ds: Dataset) -> str | None:
    """One grounded innocent explanation for ``entity_id`` under ``detector``, or None.

    Returns a non-engineer-readable sentence ending with record IDs when the
    innocent explanation actually holds, and ``None`` when it cannot be confirmed
    from the data (or the detector is unknown). Never raises.
    """
    fn = _DISPATCH.get(detector)
    if fn is None:
        return None
    try:
        return fn(entity_id, leads or [], ds)
    except Exception:
        return None


# The check name that clears each detector, so the loop can report what it ran
# (``tool_calls_made``) in a declined lead's ``not_pursued`` entry (#94).
CHECK_BY_DETECTOR: dict[str, str] = {
    "detect_no_receipt": "po_trail",
    "detect_fast_pay_no_deliverable": "po_trail",
    "detect_new_vendor_round_amounts": "contract_on_file",
    "detect_threshold_splitting": "contract_on_file",
    "detect_revenue_inflation": "cancelled_reversed",
    "detect_kickback_outflow": "same_bank_only",
    "detect_efos": "presunto_only",
    "detect_name_twin_69b": "check_69b",
    "detect_shared_supplier_address": "shared_supplier_address",
    "detect_cash_payments": "cash_deductibility",
    "detect_employee_address_match": "strong_signature",
    "detect_round_trip": "strong_signature",
    "detect_duplicate_payments": "strong_signature",
    "detect_clabe_not_on_master": "strong_signature",
}


def tool_calls_for(detectors: list[str]) -> list[str]:
    """The distinct check names that would clear ``detectors``, in a stable order.

    Used by the loop to fill a declined lead's ``tool_calls_made``; the LLM-mode
    log's own tool calls are appended by ``agent.submit`` (#94).
    """
    seen: list[str] = []
    for det in sorted(set(str(d) for d in detectors)):
        name = CHECK_BY_DETECTOR.get(det)
        if name and name not in seen:
            seen.append(name)
    return seen

