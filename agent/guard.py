"""The evidence guard (#14): "the LLM proposes, deterministic code proves."

Nothing from the investigation loop enters a case file unless every cited ID
exists, the rule is one we recognise, the evidence belongs to the accused
entities, and the peso amount is consistent with the accused entities' records
(25% tolerance, the same tolerance the scorer uses). This is the answer to "how
do you know it did not hallucinate?".

:func:`guard` is a pure check over a single proposed finding and the Dataset:
it never raises, never touches ``hidden/``, and returns the *cleaned* finding
plus a list of reasons when it has to reject.

CLI (sanity check): ``python -m agent.guard <dataset_dir> <finding.json>``
prints ACCEPTED <json> or REJECTED and the reasons.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .contract import validate_case_file
from .data import Dataset, load
from .rules import LEGAL_TO_ID, RULES

# 25% — the same tolerance data_estate.score uses for a finding to count.
AMOUNT_TOLERANCE = 0.25
NARRATIVE_MAX = 1000


# --- helpers -----------------------------------------------------------------

def _entity_clabe(entity_id: str, ds: Dataset) -> str:
    """The CLABE the accused entity owns, or ``""`` if it owns none."""
    if len(ds.suppliers):
        sub = ds.suppliers[ds.suppliers["supplier_id"] == entity_id]
        if len(sub):
            return str(sub.iloc[0]["clabe"])
    if len(ds.customers):
        sub = ds.customers[ds.customers["customer_id"] == entity_id]
        if len(sub):
            return str(sub.iloc[0]["clabe"])
    if len(ds.employees):
        sub = ds.employees[ds.employees["employee_id"] == entity_id]
        if len(sub):
            return str(sub.iloc[0]["personal_clabe"])
    return ""


def _acceptable_evidence(accused: list[str], ds: Dataset) -> set[str]:
    """Every record ID that belongs to at least one accused entity.

    "Belongs to" = an invoice the entity is the counterparty of, the bank
    transactions that reference one of those invoices, the goods receipts for
    those invoices, and the counterparty-statement rows that involve the
    entity's CLABE (as the account holder or as the counterparty).
    """
    ok: set[str] = set()
    if len(accused) == 0:
        return ok
    inv_df = ds.invoices if len(ds.invoices) else None
    btx_df = ds.bank_transactions if len(ds.bank_transactions) else None
    cp_df = ds.counterparty_bank if len(ds.counterparty_bank) else None
    gr_df = ds.goods_receipts if len(ds.goods_receipts) else None

    for ent in accused:
        # the entity's invoices (as counterparty)
        inv_uuids: set[str] = set()
        if inv_df is not None:
            sub = inv_df[inv_df["counterparty_id"] == ent]
            inv_uuids = set(sub["uuid"])
            ok |= inv_uuids
        # bank transactions referencing those invoices
        if inv_uuids and btx_df is not None:
            sub = btx_df[btx_df["invoice_uuid"].isin(inv_uuids)]
            ok |= set(sub["txn_id"])
        # goods receipts for those invoices
        if inv_uuids and gr_df is not None:
            sub = gr_df[gr_df["invoice_uuid"].isin(inv_uuids)]
            ok |= set(sub["receipt_id"])
        # counterparty-statement rows involving the entity's CLABE
        clabe = _entity_clabe(ent, ds)
        if clabe and cp_df is not None:
            sub = cp_df[cp_df["entity_clabe"] == clabe]
            ok |= set(sub["record_id"])
            sub = cp_df[cp_df["counterparty_clabe"] == clabe]
            ok |= set(sub["record_id"])
    return ok


def _evidence_kind(record_id: str, ds: Dataset) -> str | None:
    """Classify a record id as invoice/txn/cp/receipt, or ``None`` if unknown."""
    if len(ds.invoices) and (ds.invoices["uuid"] == record_id).any():
        return "invoice"
    if len(ds.bank_transactions) and (ds.bank_transactions["txn_id"] == record_id).any():
        return "txn"
    if len(ds.counterparty_bank) and (ds.counterparty_bank["record_id"] == record_id).any():
        return "cp"
    if len(ds.goods_receipts) and (ds.goods_receipts["receipt_id"] == record_id).any():
        return "receipt"
    return None


def _dedupe(seq: list[str]) -> list[str]:
    """Dedupe while keeping first-occurrence order."""
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


# --- the guard ---------------------------------------------------------------

def guard(finding: dict, ds: Dataset) -> tuple[dict | None, list[str]]:
    """Return ``(clean_finding, [])`` when the finding is sound, else ``(None, reasons)``.

    Every check is collected; a single failure rejects the finding. Never raises.
    """
    reasons: list[str] = []
    if not isinstance(finding, dict):
        return None, ["finding: expected an object"]

    # Normalise first: dedupe the ID lists so the contract (which rejects
    # duplicates) validates the cleaned view and step 6's dedupe is meaningful.
    raw_accused = finding.get("accused", [])
    raw_evidence = finding.get("evidence", [])
    accused = _dedupe(raw_accused) if isinstance(raw_accused, list) else raw_accused
    evidence = _dedupe(raw_evidence) if isinstance(raw_evidence, list) else raw_evidence
    check = {**finding, "accused": accused, "evidence": evidence}

    # 1. case-file contract checks on this (deduped) finding.
    for err in validate_case_file({"findings": [check], "not_pursued": []}, ds):
        reasons.append(err)
    if reasons:
        return None, reasons

    scheme_type = finding.get("scheme_type")
    rule_ref = finding.get("rule")

    # 2. known rule, and it may be used with this scheme type.
    rule = None
    if isinstance(rule_ref, str) and rule_ref in RULES:
        rule = RULES[rule_ref]
    elif isinstance(rule_ref, str) and rule_ref in LEGAL_TO_ID:
        rule = RULES[LEGAL_TO_ID[rule_ref]]
    else:
        reasons.append(f"rule: {rule_ref!r} is not a recognised rule id or legal string")
    if rule is None:
        return None, reasons
    if scheme_type not in rule.scheme_types:
        reasons.append(f"rule {rule.id} ({rule.scheme_types}) is not valid for scheme_type {scheme_type!r}")

    # 3. every cited evidence record belongs to an accused entity.
    acceptable = _acceptable_evidence(accused, ds)
    for e in evidence:
        if e not in acceptable:
            reasons.append(f"evidence {e} does not belong to any accused entity")

    # 4. evidence is drawn from kinds the rule allows; an invoice is required.
    if rule.evidence_kinds:
        kinds = [_evidence_kind(e, ds) for e in evidence]
        if any(k is None for k in kinds):
            reasons.append("evidence contains a record of unrecognised kind")
        for e in evidence:
            kind = _evidence_kind(e, ds)
            if kind is not None and kind not in rule.evidence_kinds:
                reasons.append(f"evidence {e} is kind {kind}, not allowed for rule {rule.id}")
        if "invoice" not in kinds:
            reasons.append(f"rule {rule.id} requires at least one invoice in evidence")

    # 5. amount within 25% of the rule's recomputation.
    if rule.id != "R5":
        recompute = rule.recompute_amount(check, ds)
        amount = float(finding["amount_mxn"])
        if recompute <= 0:
            reasons.append(f"amount_mxn {amount:.2f} cannot be validated (rule {rule.id} recomputes to 0)")
        elif abs(amount - recompute) > AMOUNT_TOLERANCE * recompute:
            reasons.append(
                f"amount_mxn {amount:.2f} is not within 25% of the recomputed {recompute:.2f}"
            )

    if reasons:
        return None, reasons

    # 6. clean up: strip unknown fields, keep narrative (truncated), dedupe, round.
    clean = {
        "scheme_type": scheme_type,
        "accused": accused,
        "rule": rule.legal,
        "amount_mxn": round(float(finding["amount_mxn"]), 2),
        "evidence": evidence,
    }
    narrative = finding.get("narrative")
    if isinstance(narrative, str) and narrative:
        clean["narrative"] = narrative[:NARRATIVE_MAX]

    return clean, []


# --- CLI ---------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("usage: python -m agent.guard <dataset_dir> <finding.json>", file=sys.stderr)
        return 2
    ds = load(argv[0])
    finding = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    clean, reasons = guard(finding, ds)
    if clean is not None:
        print("ACCEPTED")
        print(json.dumps(clean, ensure_ascii=False, indent=2))
        return 0
    print("REJECTED")
    for r in reasons:
        print(f"  - {r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
