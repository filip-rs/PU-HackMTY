# Issue queue — paste each into GitHub. Label as shown.

## Foundation (do first, by humans / Claude Code)

**#1 Repo skeleton + CI** `needs-human`
Add AGENTS.md, ci.yml, data_estate/ from the zip, freeze out/company_42. DoD: CI green on main.

**#2 Loader module `agent/data.py`** `cc`
Load a dataset directory into pandas frames with typed columns (dates, floats). Expose `load(path) -> Dataset`.
DoD: `tests/test_loader.py` loads company_42 and asserts row counts match the CSVs.

**#3 Case-file contract test** `cc`
`tests/test_case_file_contract.py`: given a case file JSON and a dataset, fail if any evidence ID or accused ID does not exist. DoD: passes on data_estate/out/example_case_file_for_seed42.json, fails on a fabricated ID.

## Detectors (`hermes-ok` — each is one pure function in `agent/detectors.py` + one test)

**#4 `detect_efos(ds)`** `hermes-ok`
Return suppliers whose RFC is on efos_69b with situacion in {Presunto, Definitivo}. DoD: finds both planted EFOS suppliers in company_42, does not return the name-twin decoy. (Use hidden/ground_truth.json ONLY inside the test.)

**#5 `detect_no_receipt(ds)`** `hermes-ok`
Purchase invoices for categories that require goods receipts (materia_prima, refacciones, consumibles) with no matching goods_receipts row. DoD: test on company_42.

**#6 `detect_duplicate_payments(ds)`** `hermes-ok`
Invoice UUIDs with more than one outgoing bank txn. Return (uuid, txn_ids, clabes). DoD: finds the 3 planted, zero false positives.

**#7 `detect_employee_address_match(ds)`** `hermes-ok`
Suppliers whose (street, city) equals an employee's home address. Also flag if approved_by == that employee. DoD: finds the shell; does not flag the shared-office decoy.

**#8 `detect_clabe_not_on_master(ds)`** `hermes-ok`
Outgoing txns whose counterparty_clabe is not the supplier master CLABE for that invoice's supplier. DoD: test.

**#9 `detect_round_trip(ds)`** `hermes-ok`
For each outgoing payment, look in counterparty_bank for a forward of ≥95% of the amount within 5 days, then an incoming payment to us of ≥90% of that within 10 days. Return the chain of IDs. DoD: finds all planted legs.

**#10 `detect_fast_pay_no_deliverable(ds)`** `hermes-ok`
Service invoices with no receipt paid within ≤7 days of invoice date. DoD: test; note this WILL flag the law-firm decoy — that is expected, it's a lead, not an accusation.

**#11 `detect_new_vendor_round_amounts(ds)`** `hermes-ok`
Suppliers onboarded during the fiscal year whose invoices are ≥60% round thousands. DoD: test; flags decoy #1 as a lead (expected).

## Agent loop (Claude Code)

**#12 Tool layer `agent/tools.py`** `cc`
Functions the LLM can call: query_ledger(filter), get_invoices(supplier_id), get_bank_txns(counterparty), trace_flow(clabe, days), check_69b(rfc), get_receipts(invoice_uuid), get_employee(id). Each returns JSON-serialisable dicts. DoD: tests.

**#13 Investigation loop `agent/investigate.py`** `cc`
Run detectors → leads. For each lead: LLM forms hypothesis, calls tools, decides accuse / drop with reason. Writes case file. DoD: on company_42, score.py recall ≥ 0.75 and judgment_penalty == 0.

**#14 Evidence guard** `cc`
Before a finding enters the case file, programmatically verify every evidence ID exists and every rule string is from an allow-list. Drop and log otherwise. DoD: test with a fabricated ID.

## Hermes-safe housekeeping (`hermes-ok`)

**#15** Add `requirements.txt` (pandas, pytest) and a `Makefile` with `test`, `gen`, `score` targets.
**#16** `ruff` config + fix lint in data_estate/. Do not change behaviour; validate.py must still pass.
**#17** Add `--n` flag to generate.py to emit N datasets with seeds seed..seed+N-1 into out/batch_<seed>/. Test.
**#18** `tests/test_generate_batch.py`: 5 random seeds all pass validate. 
