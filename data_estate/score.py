"""
Score an agent's case file against hidden ground truth.

  python -m data_estate.score out/company_42 case_file.json

Case file contract (what the agent must output):
{
  "findings": [
    {
      "scheme_type": "efos_fake_supplier",          # one of the four types, or "other"
      "accused": ["S00030"],                          # supplier/customer/employee IDs it is accusing
      "rule": "CFF Art. 69-B",
      "amount_mxn": 2070600.00,
      "evidence": ["<invoice uuid>", "TX00079", "CP00002", ...]   # record IDs the finding rests on
    }
  ],
  "not_pursued": [
    {"entity": "S00009", "reason": "new vendor with round amounts, but goods receipts on every invoice"}
  ]
}

Scoring (mirrors the judging criteria):
  results   : recall of planted schemes (a scheme counts as found if >=1 planted entity is accused
              under the right type and the amount is within 25%)
  judgment  : precision — every accused entity that is not planted is a false accusation;
              accusing a decoy is a double penalty
  evidence  : share of cited evidence IDs that actually exist AND belong to the planted scheme
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .validate import load


def planted_entities(scheme: dict) -> set[str]:
    out = set()
    for ent in scheme["entities"]:
        for k in ("supplier_id", "customer_id", "employee_id"):
            if ent.get(k):
                out.add(ent[k])
    return out


def planted_evidence(scheme: dict) -> set[str]:
    ids = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and (x[:2] in ("TX", "CP", "GR") or (len(x) == 36 and x.count("-") == 4)):
            ids.add(x)
    walk(scheme["entities"])
    return ids


def score(out: Path, case: dict) -> dict:
    d = load(out)
    truth = d["truth"]
    all_ids = {i["uuid"] for i in d["invoices"]} | {t["txn_id"] for t in d["bank"]} \
        | {c["record_id"] for c in d["cp"]} | {r["receipt_id"] for r in d["receipts"]}
    decoy_ids = {x["supplier_id"] for x in truth["decoys"]}
    planted_all = set().union(*(planted_entities(s) for s in truth["schemes"])) if truth["schemes"] else set()

    found = []
    false_acc, decoy_acc = set(), set()
    ev_total = ev_valid = 0
    for f in case.get("findings", []):
        accused = set(f.get("accused", []))
        matched = None
        for s in truth["schemes"]:
            if s["type"] == f.get("scheme_type") and accused & planted_entities(s):
                amt_ok = abs(f.get("amount_mxn", 0) - s["amount_mxn"]) <= 0.25 * s["amount_mxn"]
                if amt_ok:
                    matched = s
                    break
        if matched and matched["type"] not in found:
            found.append(matched["type"])
        for a in accused - planted_all:
            (decoy_acc if a in decoy_ids else false_acc).add(a)
        pe = planted_evidence(matched) if matched else set()
        for e in f.get("evidence", []):
            ev_total += 1
            if e in all_ids and (not matched or e in pe):
                ev_valid += 1

    n = len(truth["schemes"])
    return {
        "results_recall": len(found) / n if n else 1.0,
        "found": found,
        "missed": [s["type"] for s in truth["schemes"] if s["type"] not in found],
        "false_accusations": sorted(false_acc),
        "decoys_accused": sorted(decoy_acc),
        "judgment_penalty": len(false_acc) + 2 * len(decoy_acc),
        "evidence_validity": ev_valid / ev_total if ev_total else 0.0,
        "not_pursued_listed": len(case.get("not_pursued", [])),
    }


def main():
    out, case_path = Path(sys.argv[1]), Path(sys.argv[2])
    res = score(out, json.loads(case_path.read_text(encoding="utf-8")))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
