# Forensic Auditor — data estate generator

Synthetic books for one fiscal year (2025) of a small Monterrey manufacturing company,
with planted fraud schemes, honest-but-suspicious decoys, and a hidden ground truth for scoring.

```bash
python -m data_estate.generate --seed 42 --out data_estate/out/company_42     # all four schemes
python -m data_estate.generate --seed 7 --schemes efos,kickback --out data_estate/out/demo
python -m data_estate.generate --seed 100 --n 5 --out data_estate/out/batch_100  # 5 seeds: company_100..company_104
python -m data_estate.generate --seed 5 --schemes "" --out data_estate/out/clean   # honest books, decoys only
python -m data_estate.validate data_estate/out/company_42                    # integrity checks (run in CI)
python -m data_estate.score data_estate/out/company_42 case_file.json        # score an agent's output
```

No dependencies beyond the standard library.

## Files the agent sees (`data_estate/out/<name>/`)

| File | What it is | Key columns |
|---|---|---|
| `company.json` | The audited company | `name, rfc, clabe` |
| `suppliers.csv` | Supplier master | `supplier_id, name, rfc, street, city, clabe, account_holder, category, onboarded, approved_by` |
| `customers.csv` | Customer master | `customer_id, name, rfc, clabe` |
| `employees.csv` | Staff | `employee_id, name, role, home_street, home_city, personal_clabe` |
| `invoices.csv` | CFDI 4.0-shaped. `tipo=recibida` (purchases) / `emitida` (sales) | `uuid, fecha, rfc_emisor, rfc_receptor, uso_cfdi, forma_pago, metodo_pago, clave_prod_serv, descripcion, subtotal, iva, total, po_number, counterparty_id, approved_by` |
| `goods_receipts.csv` | Proof of delivery for purchases | `receipt_id, po_number, invoice_uuid, fecha, received_by, warehouse` |
| `bank_transactions.csv` | The company's own statement | `txn_id, fecha, direction, amount, counterparty_name, counterparty_clabe, reference, invoice_uuid` |
| `counterparty_bank.csv` | Statements obtained for some third parties (subpoena-style) | `record_id, entity_name, entity_clabe, fecha, direction, amount, counterparty_name, counterparty_clabe` |
| `ledger.csv` | General ledger, links to invoices and txns | `entry_id, fecha, account_code, account_name, debit, credit, invoice_uuid, txn_id` |
| `efos_69b.csv` | Mock SAT Art. 69-B list (~60 noise rows + planted) | `rfc, nombre, situacion, fecha_publicacion` |

Ledger accounts: `1020 Bancos`, `1180 IVA acreditable`, `1200 Clientes`, `2100 Proveedores`,
`2180 IVA trasladado`, `4000 Ventas`, `6000 Gastos <category>`, `6100 Sueldos`.

## Hidden (`data_estate/out/<name>/hidden/ground_truth.json`) — never mount into the agent

Per scheme: `type, description, rule, entities (with every planted invoice/txn/record ID), amount_mxn, how_to_prove`.
Per decoy: `supplier_id, looks_like, why_honest`.

## Planted schemes

| `type` | What was planted | Naive tell | Proof |
|---|---|---|---|
| `efos_fake_supplier` | 2 consulting suppliers, no deliverables, on 69-B | RFC on 69-B | 69-B match + no goods receipt + paid within days |
| `kickback_shell` | Shell registered at purchasing manager's home, approved by him, sends 40% back to his personal CLABE | supplier address == employee address | same-approver + counterparty statement outflows to employee CLABE |
| `round_trip_sales` | Money out as "marketing", forwarded to a customer, comes back as a "sale" days later | new customer whose only inflows come from our supplier | amount chain ±2% within ~10 days |
| `duplicate_invoice_payment` | Real invoices paid twice, second time to a CLABE not on master, booked to expense | two txns with the same `invoice_uuid` | CLABE mismatch + ledger bypasses AP. **The supplier is honest — accuse the payment, not the vendor.** |

## Decoys (always present)

1. New vendor, round amounts — but goods receipts exist.
2. Name nearly identical to a 69-B company — but different RFC.
3. Shares an address with another supplier — commercial building, not an employee home.
4. One large fast-paid law-firm invoice, no goods receipt — cites a court case; approved by the director.
5. Cash payments — each under the MXN 2,000 deductibility cap.

An agent that accuses any of these loses double in `score.py`.

## Case file contract

See docstring in `data_estate/score.py`. Every finding needs `scheme_type`, `accused` IDs,
`rule`, `amount_mxn`, and `evidence` (record IDs). Unknown or non-existent evidence IDs count against you.

## Extending

- New scheme: add a `scheme_<name>` method on `Generator`, append to `self.e.truth["schemes"]`,
  register it in `build()`'s table, and add its naive tell to `validate.py`.
- Judges' live injection: call `generate` with a fresh seed and a scheme subset the agent has never seen.
