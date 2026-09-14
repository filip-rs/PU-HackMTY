# Hide a fresh scheme — judges' quick guide

Run from the repository after `. .venv/bin/activate`. The agent sees the books,
**never `hidden/`**. It must cite records, not guess the answer.

## What it sees

Judges' SQLite `.db` tables, or `<table>.csv` files in a folder:

- `vendors`: supplier RFCs, names, addresses and bank accounts.
- `invoices`: purchases, sales, dates, amounts and cancellation status.
- `ledger`: accounting entries, invoice links and approvers.
- `bank_txns`: transfers, accounts, amounts and payment references.
- `purchase_orders`: orders, amounts, requesters and approvers.
- `contracts`: standing agreements and scope.
- `employees`: staff roles and bank accounts; **no home addresses**.
- `efos_list`: the supplied SAT Article 69-B list.

Legacy files: `company.json` (company), `suppliers.csv` (suppliers), `customers.csv`
(customers), `employees.csv` (staff/home addresses), `invoices.csv` (invoices),
`ledger.csv` (books), `goods_receipts.csv` (deliveries), `bank_transactions.csv`
(company payments), `counterparty_bank.csv` (third-party transfers), `efos_69b.csv` (69-B list).

## Way 1 — choose a seed and what to hide

```sh
python scripts/demo_run.py --seed 7 --schemes efos,kickback,roundtrip,duplicate,threshold,revenue --serve
# Shortcut: make demo SEED=7 SCHEMES=all
```

Choose any integer except **42** (frozen). `all` means all six; `clean` plants none,
leaving honest but suspicious-looking records. `efos` plants paid, unsupported
invoices from listed suppliers. `kickback` pays money back to an approving employee.
`roundtrip` sends money out and back as apparent sales. `duplicate` pays an invoice
twice, including to an off-master account (a control observation, not supplier fraud).
`threshold` splits purchases below an approval limit. `revenue` books unsupported
or cancelled year-end sales. Output: `data_estate/out/live/company_<seed>/`;
reusing a seed replaces those books.

## Way 2 — edit a copy

Never edit frozen books. Copy only the database:
`cp data_estate/out/estate_42/estate.db /tmp/judge-demo.db`.
Use a SQLite editor, or copy the CSV folder and use a spreadsheet. Keep headers,
unique IDs and CLABEs as text (including leading zeros); save/commit before running.

Three recipes in the **judges' schema**:

1. **69-B match:** pick an existing `vendors.rfc` with paid purchase invoices
   (`invoices.issuer_rfc`). Insert that `rfc` and `legal_name` into `efos_list`, with
   `status=definitivo`, `publication_date=2025-01-01` (update if already listed).
   Choose unsupported services without matching `purchase_orders`/`contracts`;
   a list match alone is not proof.
2. **Second payment:** copy an outgoing `bank_txns` row. Give it a new `txn_id`, keep
   `from_clabe` (company), `amount`, `date`, `channel`; change `to_clabe` to a different
   18-digit account. Put the existing `invoices.uuid` in `reference`.
   `bank_txns` has **no `invoice_uuid` column**. Expect a control observation.
3. **Kickback:** choose a paid vendor and an employee; set relevant
   `purchase_orders.approver` and invoice-linked `ledger.approver` to the employee's
   `name`. Add a unique `bank_txns.txn_id`, `from_clabe=vendors.bank_clabe`,
   `to_clabe=employees.bank_clabe`, `amount` equal to 40% of the vendor payment,
   `date` shortly afterwards, a descriptive `reference`, and `channel=SPEI`.
   This supplies the third-party transfer; a shared bank code is not evidence.

Legacy equivalents, on a copy **without `hidden/`**:
(a) supplier `rfc` → `efos_69b.csv`, with `nombre`, `situacion=Definitivo`,
`fecha_publicacion`; (b) copy an `out` row in `bank_transactions.csv`, keep
`invoice_uuid`, `amount`, `fecha`, change `txn_id` and `counterparty_clabe`;
(c) set `suppliers.street`/`city` to `employees.home_street`/`home_city`, link
`approved_by` to `employee_id`, then add `counterparty_bank.csv` rows with unique
`record_id`, supplier `entity_name`/`entity_clabe` (its `clabe`), `fecha`, `direction=out`,
`amount`, employee `counterparty_name`/`counterparty_clabe` (their `personal_clabe`).

```sh
python scripts/demo_run.py --estate /tmp/judge-demo.db --serve
# Judges' CSVs: --estate <csv-folder>; legacy CSVs: --dataset <copied-folder>
```

Hand edits have no valid answer key: omit `hidden/` from legacy copies so no score
prints. `--estate` never checks for an answer key. Output is the trace and case file,
plus `submission.json` and `report.html` under `runs/` (`--runs <folder>` overrides).
Database runs print the judges' format-check PASS/FAIL.

## Live display, fallbacks, limits

Attach the frontend to `http://127.0.0.1:8765`; `/runs` lists runs,
`/runs/<id>/events` streams them. Serving ends with Ctrl-C. Keep the terminal private:
generated runs print a separate **SCORE** section, for judges only when requested;
the judge sheet itself reveals no planted schemes.

Cluster unreachable? Add `--no-llm` for a fresh deterministic run. Or use
`python scripts/demo_run.py --replay-from demo/sample_trace.jsonl --port 8765`:
it automatically serves a paced trace and rebuilds artifacts offline. Keep the
original dataset at the log's recorded path. Your latest trace is `runs/latest.jsonl`.
The final line prints LLM calls, MXN cost and elapsed seconds; replay reports zero
new calls/cost, preserving original measurements in the case.

**Limits:** five scheme types plus control observations; other suspicions remain
unproven with reasons. POs/contracts stand in for delivery proof, not proof a service
happened. Third-party bank legs are visible only when supplied. The 69-B list is only
as fresh as its download. Synthetic books are not a real company.
