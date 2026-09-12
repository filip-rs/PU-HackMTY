# Issue queue — snapshot of the GitHub issues (regenerated 2026-09-12). GitHub is the source of truth: `gh issue view <n>`.

| # | Label | Title |
|---|---|---|
| #1 | `needs-human` | Repo skeleton + CI |
| #2 | `cc` | Loader module agent/data.py |
| #3 | `cc` | Case-file contract test |
| #4 | `hermes-ok` | detect_efos(ds) |
| #5 | `hermes-ok` | detect_no_receipt(ds) |
| #6 | `hermes-ok` | detect_duplicate_payments(ds) |
| #7 | `hermes-ok` | detect_employee_address_match(ds) |
| #8 | `hermes-ok` | detect_clabe_not_on_master(ds) |
| #9 | `hermes-ok` | detect_round_trip(ds) |
| #10 | `hermes-ok` | detect_fast_pay_no_deliverable(ds) |
| #11 | `hermes-ok` | detect_new_vendor_round_amounts(ds) |
| #12 | `cc` | Tool layer agent/tools.py |
| #13 | `cc` | Investigation loop agent/investigate.py |
| #14 | `cc` | Evidence guard agent/guard.py + rule catalog agent/rules.py |
| #15 | `hermes-ok` | requirements.txt + Makefile |
| #16 | `hermes-ok` | ruff config + fix lint in data_estate/ |
| #17 | `hermes-ok` | --n flag for generate.py (batch of seeds) |
| #18 | `hermes-ok` | tests/test_generate_batch.py: 5 seeds validate |

---

## #1 Repo skeleton + CI  `needs-human`

## Goal
A repo that three agents (Claude Code, Codex, Hermes) can work in from hour zero, coordinated only by GitHub issues and `AGENTS.md`.

## Done (commit `c5a46d6` and the follow-up that added `agent/detectors/` and `tests/conftest.py`)
- [x] `data_estate/` unpacked from the zip (generator, validator, scorer, README); the zip and the duplicate `out/c42` removed
- [x] `data_estate/out/company_42/` committed (including `hidden/`) and frozen behind `tests/test_frozen_dataset.py` (sha256 of every byte)
- [x] CI at `.github/workflows/ci.yml`: pytest + pandas, `data_estate.validate` on company_42, `pytest -q`, on every push and PR
- [x] `AGENTS.md` (rules, `master` not `main`, rule 8: all LLM calls via the `.env` HPC endpoint), `CLAUDE.md` imports it
- [x] `docs/` (brief, STRATEGY, PLAN, ISSUES mirror, HERMES_BRIEF, transcript, PDF), `README.md`, `LEARNINGS.md`
- [x] `.env.example`, `scripts/check_llm.py`, `.gitignore`, `.gitattributes`, `pyproject.toml` (pytest config)
- [x] `agent/detectors/__init__.py` auto-registry (one module per detector, no shared-file edits) and `tests/conftest.py` fixtures
- [x] Labels `hermes-ok`, `cc`, `codex`, `needs-human`; issues #1–#18 filed

## Definition of done
- [ ] `master` pushed and the first CI run is green
- [ ] Repo owner enables branch protection on `master`: require a PR and the `ci / test` check (nobody else has admin)
- [ ] Hermes host set up per `docs/HERMES_BRIEF.md` and has opened its first PR (expected: #15)

---

## #2 Loader module agent/data.py  `cc`

## Goal
One typed, in-memory view of a dataset directory that every detector (#4–#11), the tool layer (#12) and the guard (#14) build on. Everything downstream assumes the dtypes below, so get them exactly right here.

## Spec
```python
# agent/data.py
@dataclass
class Dataset:
    path: Path
    company: dict                     # company.json: name, rfc, clabe, city
    suppliers: pd.DataFrame           # supplier_id, name, rfc, street, city, clabe, account_holder, category, onboarded, approved_by, status
    customers: pd.DataFrame           # customer_id, name, rfc, street, city, clabe
    employees: pd.DataFrame           # employee_id, name, rfc, role, home_street, home_city, personal_clabe
    invoices: pd.DataFrame            # uuid, tipo, serie, folio, fecha, fecha_timbrado, rfc_emisor, nombre_emisor, rfc_receptor, nombre_receptor, uso_cfdi, forma_pago, metodo_pago, clave_prod_serv, descripcion, cantidad, valor_unitario, subtotal, iva, total, moneda, po_number, counterparty_id, approved_by
    goods_receipts: pd.DataFrame      # receipt_id, po_number, supplier_id, invoice_uuid, fecha, descripcion, cantidad, received_by, warehouse
    bank_transactions: pd.DataFrame   # txn_id, fecha, account_clabe, direction, amount, counterparty_name, counterparty_clabe, reference, invoice_uuid
    counterparty_bank: pd.DataFrame   # record_id, entity_name, entity_clabe, fecha, direction, amount, counterparty_name, counterparty_clabe, reference
    ledger: pd.DataFrame              # entry_id, fecha, account_code, account_name, debit, credit, descripcion, invoice_uuid, txn_id
    efos_69b: pd.DataFrame            # rfc, nombre, situacion, fecha_publicacion

    def all_record_ids(self) -> set[str]: ...   # invoice uuids | txn_ids | counterparty record_ids | receipt_ids
    def all_entity_ids(self) -> set[str]: ...   # supplier_ids | customer_ids | employee_ids

def load(path: str | Path) -> Dataset: ...
```
Typing rules:
- Read every CSV with `pd.read_csv(..., dtype=str, keep_default_na=False, encoding="utf-8")` first, then convert. Empty cells must stay `""`, never NaN (joins on NaN silently fail). In company_42: 12 bank rows (payroll) have empty `invoice_uuid` and `counterparty_clabe`; 156 issued invoices have empty `po_number`; 1,791 ledger lines have empty `txn_id`.
- Dates → `datetime64[ns]`: `fecha`, `fecha_timbrado`, `onboarded`, `fecha_publicacion`.
- Money/quantity → `float64`: `subtotal`, `iva`, `total`, `cantidad`, `valor_unitario`, `amount`, `debit`, `credit`.
- Everything else stays `str`, in particular CLABEs (18 digits, 88% start with `0`), `folio` (all digits), `po_number`, `account_code` (`1020`, `2100`, …), `rfc`.
- `load` must never open anything under `hidden/`; it must work on a directory that has no `hidden/` at all.
- Also add the `ds` fixture to `tests/conftest.py`:
  ```python
  @pytest.fixture(scope="session")
  def ds(dataset_dir):
      from agent.data import load
      return load(dataset_dir)
  ```

## Test: `tests/test_loader.py`
- Row count of every frame equals the count from `csv.DictReader` on the same file (compute in-test, do not hard-code). For reference company_42 has suppliers 42, customers 19, employees 16, invoices 597, goods_receipts 357, bank_transactions 612, counterparty_bank 22, ledger 3015, efos_69b 62.
- dtypes: `invoices.fecha` is datetime64, `invoices.total` float, `suppliers.clabe` object/str; `ds.company["clabe"]` (`012580001234567890`) appears verbatim in `bank_transactions.account_clabe` (leading zero survived).
- `(ds.bank_transactions.invoice_uuid == "").sum() == 12` and no NaN anywhere (`frame.isna().sum().sum() == 0` for every frame).
- `ds.all_record_ids()` contains `"TX00001"`, `"GR00001"`, `"CP00001"` and every `evidence` ID in `data_estate/out/example_case_file_for_seed42.json`; `ds.all_entity_ids()` contains every `accused` and `not_pursued.entity` ID in that file.
- Copy company_42 to `tmp_path` without `hidden/` and `load` it: same row counts.

## Definition of done
- [ ] `agent/data.py` as specified, `ds` fixture in `tests/conftest.py`, `tests/test_loader.py` green
- [ ] No reference to `hidden` anywhere in `agent/` (`grep -r hidden agent/` is empty apart from the package docstring)
- [ ] `python -m pytest -q` green

---

## #3 Case-file contract test  `cc`

## Goal
The mechanical half of AGENTS.md rule 3: a case file that names an ID which does not exist in the dataset is invalid, full stop. This check is reused by the evidence guard (#14) and can be run by hand before the demo.

## Spec
```python
# agent/contract.py
SCHEME_TYPES = {"efos_fake_supplier", "kickback_shell", "round_trip_sales", "duplicate_invoice_payment", "other"}

def validate_case_file(case: dict, ds: Dataset) -> list[str]:
    """Return [] when valid, else one human-readable error per problem, e.g.
    'findings[0].evidence: TX99999 not in dataset'  'findings[2].accused: S99999 not in dataset'."""
```
Checks, all of them:
- top level has `findings` (list) and `not_pursued` (list); nothing else is required
- each finding: `scheme_type ∈ SCHEME_TYPES`; `accused` non-empty list of str, each in `ds.all_entity_ids()`; `rule` non-empty str; `amount_mxn` int/float > 0; `evidence` non-empty list of str, each in `ds.all_record_ids()`; no duplicate IDs inside `accused` or `evidence`
- each not_pursued: `entity` in `ds.all_entity_ids()`, `reason` non-empty str
- an entity may not appear both in some finding's `accused` and in `not_pursued`
- CLI: `python -m agent.contract <dataset_dir> <case_file.json>` prints the errors and exits 1, or prints `OK` and exits 0

Contract reference: docstring of `data_estate/score.py`. Do not change that contract.

## Test: `tests/test_case_file_contract.py`
- `data_estate/out/example_case_file_for_seed42.json` → `[]`
- same file with one evidence ID replaced by `"TX99999"` → exactly one error, containing `TX99999` and `findings[<i>]`
- accused `"S99999"` → one error; `scheme_type: "bribery"` → one error; `amount_mxn: 0` → one error; an entity both accused and not_pursued → one error
- a finding with `evidence: []` → one error
- CLI: `subprocess.run([...agent.contract, dataset, bad_file])` returns 1, good file returns 0

## Definition of done
- [ ] `agent/contract.py` + `tests/test_case_file_contract.py` green; AGENTS.md rule 3 now points at a real file
- [ ] `python -m pytest -q` green

**Depends on #2** (`all_record_ids`, `all_entity_ids`).

---

## #4 detect_efos(ds)  `hermes-ok`

## Goal
The cheapest, strongest lead: a supplier whose RFC is on SAT's Article 69-B list (EFOS). Match on **RFC**, never on name: one decoy in every dataset has the same *name* as a listed company but a different RFC.

## Spec
`agent/detectors/efos.py` → `detect_efos(ds) -> list[dict]`
1. Inner-join `ds.suppliers` to `ds.efos_69b` on `rfc` (exact, case-sensitive string equality).
2. Keep rows with `situacion` in `{"Presunto", "Definitivo"}`. `Desvirtuado` and `Sentencia favorable` mean SAT cleared them: not a lead.
3. Do **not** filter on `fecha_publicacion`. In company_42 the Definitivo supplier was published 2025-11-15, after every one of its invoices (Feb–Aug 2025). That lag is the whole point of the scheme; the finding still stands.
4. One dict per matched supplier, sorted by `entity_id`:
   - `entity_id`: supplier_id · `rfc` · `name` · `situacion` · `fecha_publicacion` (ISO str)
   - `n_invoices`, `total_mxn`: count and sum of `total` over that supplier's `invoices` rows with `tipo == "recibida"` and `counterparty_id == supplier_id`
   - `evidence`: those invoice UUIDs plus the `txn_id` of every `bank_transactions` row with `direction == "out"` whose `invoice_uuid` is one of them

## Data facts (company_42, verified)
- `efos_69b` has 62 rows: 17 Presunto, 17 Definitivo, 13 Desvirtuado, 15 Sentencia favorable. Exactly 2 supplier RFCs match with an active status; one is Presunto (published 2025-07-10), one Definitivo (2025-11-15). Each has 5 invoices.
- Decoy: supplier `Refacciones San Nicolás S de RL de CV` has the same name as a Definitivo entry but a different RFC. It must not appear.

### Conventions for every detector
- **Module:** `agent/detectors/<name>.py` with exactly one public function `detect_<name>(ds, **params) -> list[dict]`. The package `agent/detectors/__init__.py` discovers it on import (registry `DETECTORS`, runner `run_all`). Do not edit `__init__.py` or any other detector module.
- **`ds`** is `agent.data.Dataset` (#2): one pandas DataFrame per CSV, named after the file stem: `ds.suppliers`, `ds.customers`, `ds.employees`, `ds.invoices`, `ds.goods_receipts`, `ds.bank_transactions`, `ds.counterparty_bank`, `ds.ledger`, `ds.efos_69b`, plus `ds.company` (dict from `company.json`). Date columns are `datetime64`, money columns `float`, every ID / RFC / CLABE / folio / po_number / account_code is `str`, and empty cells are `""` (never NaN).
- **Pure function:** no I/O, no LLM, no network, never reads `hidden/`. Output must be deterministic: sort it.
- **Every returned dict is a lead, not an accusation.** It carries at least `entity_id` (the `S*`/`C*`/`E*` it points at) and `evidence` (list of record IDs that triggered it: invoice UUIDs, `TX*`, `CP*`, `GR*`), plus the fields listed below. Dates as ISO strings, money as float, everything `json.dumps`-able.
- **Test:** `tests/test_detect_<name>.py`. Fixtures from `tests/conftest.py`: `ds` (company_42 loaded), `scheme(type)` (that scheme's ground-truth dict), `decoy_ids` (set of the 5 decoy supplier IDs), `truth` (full dict). Only tests may read ground truth. Assert `json.dumps(result)` works.
- Run `python -m pytest -q` before opening the PR. No new dependencies. Small diff: one module + one test file.

### Ground-truth shape (for the test only)
`truth["schemes"]` is a list; `scheme(t)` returns the one with `type == t`. `truth["decoys"]` is a list of `{supplier_id, rfc, name, looks_like, why_honest}` (the law-firm decoy also has `invoice_uuid`). Identify a decoy by the start of `looks_like`: `"New vendor"`, `"Name almost"`, `"Shares address"`, `"Large one-off"`, `"Cash payments"`.

## Test: `tests/test_detect_efos.py`
- `{r["entity_id"]}` == `{e["supplier_id"] for e in scheme("efos_fake_supplier")["entities"]}` (2 suppliers)
- for each result, `situacion == e["efos_status"]`, `set(evidence) ⊇ set(e["invoice_uuids"]) | set(e["bank_txn_ids"])`, `n_invoices == len(e["invoice_uuids"])`
- no `entity_id` in `decoy_ids`
- result is `json.dumps`-able and sorted by `entity_id`

## Definition of done
- [ ] Module + test as above, `python -m pytest -q` green, no other files touched (except adding nothing to `__init__.py`)
- [ ] Finds both planted EFOS suppliers, does not return the name-twin decoy

**Depends on #2** (`ds` fixture and dtypes). If #2 is still open, skip this issue (see `docs/HERMES_BRIEF.md`).

---

## #5 detect_no_receipt(ds)  `hermes-ok`

## Goal
"Materialidad": a purchase with no proof of delivery. This detector lists every purchase invoice without a goods receipt and says whether the supplier's category should have had one. It is a lead generator and context provider for the loop, not an accusation: most hits are honest service suppliers.

Note: the original one-line spec ("goods categories with no receipt") returns **zero rows** on company_42, because every goods invoice there has a receipt by construction. The spec below is broadened so the detector is testable and useful.

## Spec
`agent/detectors/no_receipt.py` → `detect_no_receipt(ds) -> list[dict]`
1. Take `ds.invoices` with `tipo == "recibida"` (441 rows in company_42). Supplier = `counterparty_id`.
2. Left-join `ds.goods_receipts` on `invoice_uuid`; keep invoices with **no** receipt.
3. Join `ds.suppliers.category`. `receipt_required = category in {"materia_prima", "refacciones", "consumibles"}` (goods categories; `servicios`, `logistica`, `renta_util` are services and never have receipts).
4. One dict per invoice, sorted by `(entity_id, fecha, invoice_uuid)`:
   `entity_id` (supplier) · `invoice_uuid` · `fecha` (ISO) · `category` · `receipt_required` (bool) · `total_mxn` · `descripcion` · `approved_by` · `po_number` · `evidence = [invoice_uuid]`

## Data facts (company_42, verified)
- 84 purchase invoices have no receipt: servicios 58, renta_util 15, logistica 11. None of them is `receipt_required` (0 goods invoices lack a receipt).
- Every planted purchase invoice (both EFOS suppliers, the kickback shell, the round-trip supplier) is in that set, and so is the law-firm decoy's single invoice ("Honorarios — litigio mercantil exp. 412/2025"). The other four decoys all have receipts.

### Conventions for every detector
- **Module:** `agent/detectors/<name>.py` with exactly one public function `detect_<name>(ds, **params) -> list[dict]`. The package `agent/detectors/__init__.py` discovers it on import (registry `DETECTORS`, runner `run_all`). Do not edit `__init__.py` or any other detector module.
- **`ds`** is `agent.data.Dataset` (#2): one pandas DataFrame per CSV, named after the file stem: `ds.suppliers`, `ds.customers`, `ds.employees`, `ds.invoices`, `ds.goods_receipts`, `ds.bank_transactions`, `ds.counterparty_bank`, `ds.ledger`, `ds.efos_69b`, plus `ds.company` (dict from `company.json`). Date columns are `datetime64`, money columns `float`, every ID / RFC / CLABE / folio / po_number / account_code is `str`, and empty cells are `""` (never NaN).
- **Pure function:** no I/O, no LLM, no network, never reads `hidden/`. Output must be deterministic: sort it.
- **Every returned dict is a lead, not an accusation.** It carries at least `entity_id` (the `S*`/`C*`/`E*` it points at) and `evidence` (list of record IDs that triggered it: invoice UUIDs, `TX*`, `CP*`, `GR*`), plus the fields listed below. Dates as ISO strings, money as float, everything `json.dumps`-able.
- **Test:** `tests/test_detect_<name>.py`. Fixtures from `tests/conftest.py`: `ds` (company_42 loaded), `scheme(type)` (that scheme's ground-truth dict), `decoy_ids` (set of the 5 decoy supplier IDs), `truth` (full dict). Only tests may read ground truth. Assert `json.dumps(result)` works.
- Run `python -m pytest -q` before opening the PR. No new dependencies. Small diff: one module + one test file.

### Ground-truth shape (for the test only)
`truth["schemes"]` is a list; `scheme(t)` returns the one with `type == t`. `truth["decoys"]` is a list of `{supplier_id, rfc, name, looks_like, why_honest}` (the law-firm decoy also has `invoice_uuid`). Identify a decoy by the start of `looks_like`: `"New vendor"`, `"Name almost"`, `"Shares address"`, `"Large one-off"`, `"Cash payments"`.

## Test: `tests/test_detect_no_receipt.py`
- `all(not r["receipt_required"] for r in result)`
- `len(result) == n_recibida - n_distinct_invoice_uuid_in_goods_receipts` (compute both from `ds`)
- returned UUIDs ⊇ every `invoice_uuids` of `scheme("efos_fake_supplier")["entities"]` and of `scheme("kickback_shell")["entities"][0]`, and every `legs[i]["purchase_invoice"]` of `scheme("round_trip_sales")["entities"][0]`
- the law-firm decoy (`looks_like` starts with `"Large one-off"`) has its `invoice_uuid` in the result, with `category == "servicios"`
- no row whose `entity_id` is the decoy with `looks_like` starting `"New vendor"`, `"Shares address"`, or `"Cash payments"`

## Definition of done
- [ ] Module + test green; docstring states this is a lead list, not an accusation list
- [ ] `python -m pytest -q` green

**Depends on #2.** If #2 is still open, skip this issue.

---

## #6 detect_duplicate_payments(ds)  `hermes-ok`

## Goal
The same invoice paid twice. In this scheme the **supplier is honest**; the accusation targets the payment (a control failure or embezzlement), so the detector reports per invoice, and the docstring must say so.

## Spec
`agent/detectors/duplicate_payments.py` → `detect_duplicate_payments(ds) -> list[dict]`
1. `ds.bank_transactions` with `direction == "out"` **and** `invoice_uuid != ""` (12 payroll rows have an empty `invoice_uuid`; never group on `""`).
2. Group by `invoice_uuid`; keep groups with 2 or more transactions.
3. Join `ds.invoices` (`uuid`) for `counterparty_id` (supplier) and `total`.
4. One dict per invoice, sorted by `invoice_uuid`:
   `entity_id` (supplier) · `invoice_uuid` · `n_payments` · `txn_ids` (ordered by `fecha`, then `txn_id`) · `fechas` (ISO, same order) · `clabes` (same order) · `amounts` (same order) · `invoice_total_mxn` · `overpaid_mxn = sum(amounts) - invoice_total` · `evidence = [invoice_uuid] + txn_ids`

## Data facts (company_42, verified)
- Exactly 3 invoices are paid twice, all from one honest goods supplier. The second payment goes to a CLABE that is not on the supplier master (that is #8's job to flag) 10–40 days after the first, and is booked to expense `6000` instead of AP `2100` (visible in `ds.ledger`, not this detector's job).
- Baseline invoices are paid exactly once; there are no accidental duplicates.

### Conventions for every detector
- **Module:** `agent/detectors/<name>.py` with exactly one public function `detect_<name>(ds, **params) -> list[dict]`. The package `agent/detectors/__init__.py` discovers it on import (registry `DETECTORS`, runner `run_all`). Do not edit `__init__.py` or any other detector module.
- **`ds`** is `agent.data.Dataset` (#2): one pandas DataFrame per CSV, named after the file stem: `ds.suppliers`, `ds.customers`, `ds.employees`, `ds.invoices`, `ds.goods_receipts`, `ds.bank_transactions`, `ds.counterparty_bank`, `ds.ledger`, `ds.efos_69b`, plus `ds.company` (dict from `company.json`). Date columns are `datetime64`, money columns `float`, every ID / RFC / CLABE / folio / po_number / account_code is `str`, and empty cells are `""` (never NaN).
- **Pure function:** no I/O, no LLM, no network, never reads `hidden/`. Output must be deterministic: sort it.
- **Every returned dict is a lead, not an accusation.** It carries at least `entity_id` (the `S*`/`C*`/`E*` it points at) and `evidence` (list of record IDs that triggered it: invoice UUIDs, `TX*`, `CP*`, `GR*`), plus the fields listed below. Dates as ISO strings, money as float, everything `json.dumps`-able.
- **Test:** `tests/test_detect_<name>.py`. Fixtures from `tests/conftest.py`: `ds` (company_42 loaded), `scheme(type)` (that scheme's ground-truth dict), `decoy_ids` (set of the 5 decoy supplier IDs), `truth` (full dict). Only tests may read ground truth. Assert `json.dumps(result)` works.
- Run `python -m pytest -q` before opening the PR. No new dependencies. Small diff: one module + one test file.

### Ground-truth shape (for the test only)
`truth["schemes"]` is a list; `scheme(t)` returns the one with `type == t`. `truth["decoys"]` is a list of `{supplier_id, rfc, name, looks_like, why_honest}` (the law-firm decoy also has `invoice_uuid`). Identify a decoy by the start of `looks_like`: `"New vendor"`, `"Name almost"`, `"Shares address"`, `"Large one-off"`, `"Cash payments"`.

## Test: `tests/test_detect_duplicate_payments.py`
- `ent = scheme("duplicate_invoice_payment")["entities"][0]`; `len(result) == 3 == len(ent["payments"])`
- `{r["invoice_uuid"]}` == `{p["invoice_uuid"] for p in ent["payments"]}`
- for each row, `set(r["txn_ids"]) == {p["original_txn"], p["duplicate_txn"]}` and `r["entity_id"] == ent["supplier_id"]` and `r["n_payments"] == 2` and `abs(r["overpaid_mxn"] - r["invoice_total_mxn"]) < 0.01`
- no other `entity_id` appears; nothing in `decoy_ids`

## Definition of done
- [ ] Module + test green; docstring says the supplier is honest and the lead is about the payment
- [ ] `python -m pytest -q` green

**Depends on #2.** If #2 is still open, skip this issue.

---

## #7 detect_employee_address_match(ds)  `hermes-ok`

## Goal
Undisclosed related party: a supplier registered at an employee's home. Combined with "the same employee approves the supplier", this is the tell for the kickback shell.

## Spec
`agent/detectors/employee_address.py` → `detect_employee_address_match(ds) -> list[dict]`
1. Inner-join `ds.suppliers` `(street, city)` to `ds.employees` `(home_street, home_city)`; exact match after `.str.strip()` on both sides. Do **not** fuzzy-match and do **not** compare supplier addresses to other suppliers' addresses (that is the shared-office decoy).
2. `same_approver = suppliers.approved_by == employees.employee_id` for the matched pair.
3. One dict per (supplier, employee) pair, sorted by `(entity_id, employee_id)`:
   `entity_id` (supplier) · `supplier_name` · `employee_id` · `employee_name` · `employee_role` · `same_approver` (bool) · `street` · `city` · `n_invoices` · `total_mxn` (that supplier's `recibida` invoices) · `evidence` = those invoice UUIDs + the `out` `txn_id`s that reference them

## Data facts (company_42, verified)
- Exactly one hit: the shell `Gestoría y Enlace … S de RL de CV` sits at the home address of the purchasing manager (`Gerente de Compras`), who also approved it (`same_approver == True`). 8 invoices.
- 16 employees. The purchasing manager approves 41 of 42 suppliers, so `same_approver` alone means nothing; only the address match makes it a lead.
- Decoy: two logistics suppliers share one commercial address with each other. Neither address is an employee's home. They must not appear.

### Conventions for every detector
- **Module:** `agent/detectors/<name>.py` with exactly one public function `detect_<name>(ds, **params) -> list[dict]`. The package `agent/detectors/__init__.py` discovers it on import (registry `DETECTORS`, runner `run_all`). Do not edit `__init__.py` or any other detector module.
- **`ds`** is `agent.data.Dataset` (#2): one pandas DataFrame per CSV, named after the file stem: `ds.suppliers`, `ds.customers`, `ds.employees`, `ds.invoices`, `ds.goods_receipts`, `ds.bank_transactions`, `ds.counterparty_bank`, `ds.ledger`, `ds.efos_69b`, plus `ds.company` (dict from `company.json`). Date columns are `datetime64`, money columns `float`, every ID / RFC / CLABE / folio / po_number / account_code is `str`, and empty cells are `""` (never NaN).
- **Pure function:** no I/O, no LLM, no network, never reads `hidden/`. Output must be deterministic: sort it.
- **Every returned dict is a lead, not an accusation.** It carries at least `entity_id` (the `S*`/`C*`/`E*` it points at) and `evidence` (list of record IDs that triggered it: invoice UUIDs, `TX*`, `CP*`, `GR*`), plus the fields listed below. Dates as ISO strings, money as float, everything `json.dumps`-able.
- **Test:** `tests/test_detect_<name>.py`. Fixtures from `tests/conftest.py`: `ds` (company_42 loaded), `scheme(type)` (that scheme's ground-truth dict), `decoy_ids` (set of the 5 decoy supplier IDs), `truth` (full dict). Only tests may read ground truth. Assert `json.dumps(result)` works.
- Run `python -m pytest -q` before opening the PR. No new dependencies. Small diff: one module + one test file.

### Ground-truth shape (for the test only)
`truth["schemes"]` is a list; `scheme(t)` returns the one with `type == t`. `truth["decoys"]` is a list of `{supplier_id, rfc, name, looks_like, why_honest}` (the law-firm decoy also has `invoice_uuid`). Identify a decoy by the start of `looks_like`: `"New vendor"`, `"Name almost"`, `"Shares address"`, `"Large one-off"`, `"Cash payments"`.

## Test: `tests/test_detect_employee_address_match.py`
- `ent = scheme("kickback_shell")["entities"][0]`; `len(result) == 1`
- `result[0]["entity_id"] == ent["supplier_id"]`, `result[0]["employee_id"] == ent["employee_id"]`, `result[0]["same_approver"] is True`
- `set(result[0]["evidence"]) ⊇ set(ent["invoice_uuids"]) | set(ent["bank_txn_ids"])`
- no `entity_id` in `decoy_ids` (in particular not the `"Shares address"` decoy)

## Definition of done
- [ ] Module + test green
- [ ] `python -m pytest -q` green

**Depends on #2.** If #2 is still open, skip this issue.

---

## #8 detect_clabe_not_on_master(ds)  `hermes-ok`

## Goal
Payment diversion: money for a real invoice sent to a bank account that is not the supplier's account of record.

## Spec
`agent/detectors/clabe_mismatch.py` → `detect_clabe_not_on_master(ds) -> list[dict]`
1. `ds.bank_transactions` with `direction == "out"` and `invoice_uuid != ""`.
2. Join `ds.invoices` on `uuid` to get `counterparty_id` (supplier), then `ds.suppliers` on `supplier_id` to get the master `clabe`.
3. Keep rows where `counterparty_clabe != clabe`. Compare as strings: CLABEs are 18 digits and 88% of them start with `0`; if you ever see 17-digit values the loader is wrong, stop and comment on #2.
4. One dict per transaction, sorted by `txn_id`:
   `entity_id` (supplier) · `txn_id` · `invoice_uuid` · `fecha` (ISO) · `amount_mxn` · `paid_clabe` · `master_clabe` · `counterparty_name` · `evidence = [txn_id, invoice_uuid]`

## Data facts (company_42, verified)
- Exactly 3 hits: the second payments of the three duplicate-paid invoices (#6), all to the same alternate CLABE, all for the same honest supplier. The original payments go to the master CLABE and must not appear.
- Payroll rows (`counterparty_clabe == ""`, `invoice_uuid == ""`) must be excluded by step 1.

### Conventions for every detector
- **Module:** `agent/detectors/<name>.py` with exactly one public function `detect_<name>(ds, **params) -> list[dict]`. The package `agent/detectors/__init__.py` discovers it on import (registry `DETECTORS`, runner `run_all`). Do not edit `__init__.py` or any other detector module.
- **`ds`** is `agent.data.Dataset` (#2): one pandas DataFrame per CSV, named after the file stem: `ds.suppliers`, `ds.customers`, `ds.employees`, `ds.invoices`, `ds.goods_receipts`, `ds.bank_transactions`, `ds.counterparty_bank`, `ds.ledger`, `ds.efos_69b`, plus `ds.company` (dict from `company.json`). Date columns are `datetime64`, money columns `float`, every ID / RFC / CLABE / folio / po_number / account_code is `str`, and empty cells are `""` (never NaN).
- **Pure function:** no I/O, no LLM, no network, never reads `hidden/`. Output must be deterministic: sort it.
- **Every returned dict is a lead, not an accusation.** It carries at least `entity_id` (the `S*`/`C*`/`E*` it points at) and `evidence` (list of record IDs that triggered it: invoice UUIDs, `TX*`, `CP*`, `GR*`), plus the fields listed below. Dates as ISO strings, money as float, everything `json.dumps`-able.
- **Test:** `tests/test_detect_<name>.py`. Fixtures from `tests/conftest.py`: `ds` (company_42 loaded), `scheme(type)` (that scheme's ground-truth dict), `decoy_ids` (set of the 5 decoy supplier IDs), `truth` (full dict). Only tests may read ground truth. Assert `json.dumps(result)` works.
- Run `python -m pytest -q` before opening the PR. No new dependencies. Small diff: one module + one test file.

### Ground-truth shape (for the test only)
`truth["schemes"]` is a list; `scheme(t)` returns the one with `type == t`. `truth["decoys"]` is a list of `{supplier_id, rfc, name, looks_like, why_honest}` (the law-firm decoy also has `invoice_uuid`). Identify a decoy by the start of `looks_like`: `"New vendor"`, `"Name almost"`, `"Shares address"`, `"Large one-off"`, `"Cash payments"`.

## Test: `tests/test_detect_clabe_not_on_master.py`
- `ent = scheme("duplicate_invoice_payment")["entities"][0]`; `len(result) == 3`
- `{r["txn_id"]}` == `{p["duplicate_txn"] for p in ent["payments"]}`; no `p["original_txn"]` appears
- every `r["paid_clabe"] == ent["alternate_clabe"]` and `r["entity_id"] == ent["supplier_id"]`
- every `paid_clabe` and `master_clabe` is an 18-character digit string

## Definition of done
- [ ] Module + test green
- [ ] `python -m pytest -q` green

**Depends on #2.** If #2 is still open, skip this issue.

---

## #9 detect_round_trip(ds)  `hermes-ok`

## Goal
Money that leaves as a purchase and comes back as a sale. This is the one scheme no single-row rule can see; it needs the counterparty statement (`counterparty_bank`) to bridge the two legs.

## Spec
`agent/detectors/round_trip.py` → `detect_round_trip(ds, *, forward_min_ratio=0.95, forward_days=5, return_min_ratio=0.80, return_days=10) -> list[dict]`

For every outgoing payment `O` (`ds.bank_transactions`, `direction == "out"`, amount `A`):
1. **Forward leg.** Find `F` in `ds.counterparty_bank` with `entity_clabe == O.counterparty_clabe`, `direction == "out"`, `O.fecha ≤ F.fecha ≤ O.fecha + forward_days`, `F.amount ≥ forward_min_ratio × A`.
2. **Return leg.** For each `F`, find `I` in `ds.bank_transactions` with `direction == "in"`, `I.counterparty_clabe == F.counterparty_clabe`, `F.fecha ≤ I.fecha ≤ F.fecha + return_days`, `I.amount ≥ return_min_ratio × F.amount`.
3. One dict per `(O, F, I)` chain, sorted by `out_txn`:
   `entity_id` (supplier of `O`, via `invoices.counterparty_id` of `O.invoice_uuid`; `""` if none) · `customer_id` (via `invoices.counterparty_id` of `I.invoice_uuid`; `""` if none) · `out_txn` · `forward_record` · `in_txn` · `purchase_invoice` (`O.invoice_uuid`) · `sales_invoice` (`I.invoice_uuid`) · `amount_out` · `amount_forward` · `amount_in` · `days_out_to_forward` · `days_forward_to_in` · `evidence` = `[purchase_invoice, out_txn, forward_record, sales_invoice, in_txn]` without empty strings

**Why `return_min_ratio` is 0.80, not 0.90.** The forward is 98% of the outgoing total, but the "sale" that brings it back is invoiced net of IVA, so the inbound total is ≈ 0.98 / 1.16 ≈ 0.845 of the outbound total and 0.862 of the forwarded amount. On company_42 all three planted legs return exactly 0.862 of the forward; a 0.90 threshold finds **nothing** (verified). 0.80 finds exactly the three planted chains.

## Data facts (company_42, verified)
- `counterparty_bank` has 22 rows for only two entities: the kickback shell and the round-trip supplier. Both receive our payments (`direction == "in"`) and forward them (`direction == "out"`).
- 3 planted chains: forward 1–3 days after our payment, return 5–6 days after the forward. Amounts: out 348,000 → forward 341,040 → in 294,000 (and the same shape for the other two).
- The kickback shell forwards ~40% to an employee's personal CLABE; that CLABE never pays us, so no chain is produced there. Good.

### Conventions for every detector
- **Module:** `agent/detectors/<name>.py` with exactly one public function `detect_<name>(ds, **params) -> list[dict]`. The package `agent/detectors/__init__.py` discovers it on import (registry `DETECTORS`, runner `run_all`). Do not edit `__init__.py` or any other detector module.
- **`ds`** is `agent.data.Dataset` (#2): one pandas DataFrame per CSV, named after the file stem: `ds.suppliers`, `ds.customers`, `ds.employees`, `ds.invoices`, `ds.goods_receipts`, `ds.bank_transactions`, `ds.counterparty_bank`, `ds.ledger`, `ds.efos_69b`, plus `ds.company` (dict from `company.json`). Date columns are `datetime64`, money columns `float`, every ID / RFC / CLABE / folio / po_number / account_code is `str`, and empty cells are `""` (never NaN).
- **Pure function:** no I/O, no LLM, no network, never reads `hidden/`. Output must be deterministic: sort it.
- **Every returned dict is a lead, not an accusation.** It carries at least `entity_id` (the `S*`/`C*`/`E*` it points at) and `evidence` (list of record IDs that triggered it: invoice UUIDs, `TX*`, `CP*`, `GR*`), plus the fields listed below. Dates as ISO strings, money as float, everything `json.dumps`-able.
- **Test:** `tests/test_detect_<name>.py`. Fixtures from `tests/conftest.py`: `ds` (company_42 loaded), `scheme(type)` (that scheme's ground-truth dict), `decoy_ids` (set of the 5 decoy supplier IDs), `truth` (full dict). Only tests may read ground truth. Assert `json.dumps(result)` works.
- Run `python -m pytest -q` before opening the PR. No new dependencies. Small diff: one module + one test file.

### Ground-truth shape (for the test only)
`truth["schemes"]` is a list; `scheme(t)` returns the one with `type == t`. `truth["decoys"]` is a list of `{supplier_id, rfc, name, looks_like, why_honest}` (the law-firm decoy also has `invoice_uuid`). Identify a decoy by the start of `looks_like`: `"New vendor"`, `"Name almost"`, `"Shares address"`, `"Large one-off"`, `"Cash payments"`.

## Test: `tests/test_detect_round_trip.py`
- `ent = scheme("round_trip_sales")["entities"][0]`; `len(result) == len(ent["legs"]) == 3`
- `{(r["out_txn"], r["forward_record"], r["in_txn"])}` == `{(l["out_txn"], l["forward_record"], l["in_txn"]) for l in ent["legs"]}`
- for each row: `purchase_invoice`/`sales_invoice` equal the leg's `purchase_invoice`/`sales_invoice`; `entity_id == ent["supplier_id"]`; `customer_id == ent["customer_id"]`; `0.8 ≤ amount_in / amount_forward ≤ 1.0`; `0 ≤ days_forward_to_in ≤ 10`
- `detect_round_trip(ds, return_min_ratio=0.90) == []` (documents the IVA effect so nobody "fixes" the threshold back)
- nothing in `decoy_ids`

## Definition of done
- [ ] Module + test green; the docstring explains the 0.80 ratio
- [ ] `python -m pytest -q` green

**Depends on #2.** If #2 is still open, skip this issue.

---

## #10 detect_fast_pay_no_deliverable(ds)  `hermes-ok`

## Goal
Service invoices with no deliverable that were paid unusually fast. Honest suppliers get paid on 15–45 day terms; the planted schemes are paid within a week. This detector **will** flag the law-firm decoy. That is expected and correct: it is a lead, the loop clears it (court case number, approved by the director).

## Spec
`agent/detectors/fast_pay.py` → `detect_fast_pay_no_deliverable(ds, *, max_days=10) -> list[dict]`
1. `ds.bank_transactions` with `direction == "out"` and `invoice_uuid != ""`, joined to `ds.invoices` (`uuid`, `tipo == "recibida"`) and `ds.suppliers` (`counterparty_id` → `category`).
2. Keep invoices with **no** `goods_receipts` row **and** `category in {"servicios", "logistica", "renta_util"}` (service categories never have receipts; goods without receipts are #5's business).
3. `days_to_pay = (txn.fecha - invoice.fecha).days`; keep `days_to_pay ≤ max_days`.
4. One dict per (invoice, payment), sorted by `(entity_id, fecha_invoice, invoice_uuid)`:
   `entity_id` (supplier) · `invoice_uuid` · `txn_id` · `category` · `fecha_invoice` · `fecha_paid` (ISO) · `days_to_pay` · `total_mxn` · `descripcion` · `approved_by` · `evidence = [invoice_uuid, txn_id]`

**Why `max_days` is 10, not 7.** Planted payments land 1–7 days after the invoice; honest service invoices are never paid before day 15 (no honest purchase of any kind before day 12 in company_42). Payment dates roll forward to the next business day, so a 7-day term can land on day 9 in other seeds. 10 keeps the margin on both sides; 7, 10 and 12 give identical results on company_42.

## Data facts (company_42, verified)
- 22 hits: 8 for the kickback shell, 5 + 5 for the two EFOS suppliers, 3 for the round-trip supplier, 1 for the law-firm decoy (paid in 4 days, 380,000 subtotal, approved by the director).

### Conventions for every detector
- **Module:** `agent/detectors/<name>.py` with exactly one public function `detect_<name>(ds, **params) -> list[dict]`. The package `agent/detectors/__init__.py` discovers it on import (registry `DETECTORS`, runner `run_all`). Do not edit `__init__.py` or any other detector module.
- **`ds`** is `agent.data.Dataset` (#2): one pandas DataFrame per CSV, named after the file stem: `ds.suppliers`, `ds.customers`, `ds.employees`, `ds.invoices`, `ds.goods_receipts`, `ds.bank_transactions`, `ds.counterparty_bank`, `ds.ledger`, `ds.efos_69b`, plus `ds.company` (dict from `company.json`). Date columns are `datetime64`, money columns `float`, every ID / RFC / CLABE / folio / po_number / account_code is `str`, and empty cells are `""` (never NaN).
- **Pure function:** no I/O, no LLM, no network, never reads `hidden/`. Output must be deterministic: sort it.
- **Every returned dict is a lead, not an accusation.** It carries at least `entity_id` (the `S*`/`C*`/`E*` it points at) and `evidence` (list of record IDs that triggered it: invoice UUIDs, `TX*`, `CP*`, `GR*`), plus the fields listed below. Dates as ISO strings, money as float, everything `json.dumps`-able.
- **Test:** `tests/test_detect_<name>.py`. Fixtures from `tests/conftest.py`: `ds` (company_42 loaded), `scheme(type)` (that scheme's ground-truth dict), `decoy_ids` (set of the 5 decoy supplier IDs), `truth` (full dict). Only tests may read ground truth. Assert `json.dumps(result)` works.
- Run `python -m pytest -q` before opening the PR. No new dependencies. Small diff: one module + one test file.

### Ground-truth shape (for the test only)
`truth["schemes"]` is a list; `scheme(t)` returns the one with `type == t`. `truth["decoys"]` is a list of `{supplier_id, rfc, name, looks_like, why_honest}` (the law-firm decoy also has `invoice_uuid`). Identify a decoy by the start of `looks_like`: `"New vendor"`, `"Name almost"`, `"Shares address"`, `"Large one-off"`, `"Cash payments"`.

## Test: `tests/test_detect_fast_pay_no_deliverable.py`
- `expected = {e["supplier_id"] for e in scheme("efos_fake_supplier")["entities"]} | {scheme("kickback_shell")["entities"][0]["supplier_id"], scheme("round_trip_sales")["entities"][0]["supplier_id"], law_firm["supplier_id"]}` where `law_firm` is the decoy whose `looks_like` starts with `"Large one-off"`; assert `{r["entity_id"]} == expected`
- rows per supplier: `len(e["invoice_uuids"])` for each EFOS entity and the shell, `len(legs)` for the round-trip supplier, 1 for the law firm whose `invoice_uuid` equals `law_firm["invoice_uuid"]`
- every `0 ≤ r["days_to_pay"] ≤ 10`; no other decoy in the result
- `detect_fast_pay_no_deliverable(ds, max_days=0) == []`

## Definition of done
- [ ] Module + test green; docstring says the law firm is an expected lead
- [ ] `python -m pytest -q` green

**Depends on #2.** If #2 is still open, skip this issue.

---

## #11 detect_new_vendor_round_amounts(ds)  `hermes-ok`

## Goal
Classic EFOS smell: a recently onboarded supplier whose invoices are suspiciously round. Flags the new-vendor decoy too, by design: it is a lead, and the loop clears it because every one of its invoices has a warehouse-signed receipt.

## Spec
`agent/detectors/new_vendor_round.py` → `detect_new_vendor_round_amounts(ds, *, since="2024-07-01", min_share=0.6) -> list[dict]`
1. Suppliers with `onboarded >= since` (six months before the fiscal year starts; keep it a parameter) and at least one `recibida` invoice.
2. Per supplier, `round_share` = share of its invoices whose **`subtotal`** is a multiple of 1,000 (`subtotal % 1000 == 0`, compare with a tolerance of 0.005 after rounding to 2 decimals).
3. Keep `round_share >= min_share`.
4. One dict per supplier, sorted by `entity_id`:
   `entity_id` · `name` · `category` · `onboarded` (ISO) · `first_invoice` (ISO) · `n_invoices` · `n_round` · `round_share` · `total_mxn` · `evidence` = that supplier's invoice UUIDs

**Use `subtotal`, not `total`.** Totals carry 16% IVA: a round 85,000 subtotal is a 98,600 total. On `total` the kickback shell's share is 0.0 and this detector misses it (verified); on `subtotal` it is 1.0.

## Data facts (company_42, verified)
- 5 hits, all with `round_share == 1.0`: the new-vendor decoy (onboarded 2025-06-02), both EFOS suppliers (onboarded 2024-10-23 and 2024-12-02), the kickback shell (2025-03-03), the round-trip supplier (2025-04-01).
- Baseline suppliers are onboarded between 2019 and 2024-10 and their subtotals are practically never round thousands. The law firm's single 380,000 invoice is round, but it was onboarded years earlier, so the date filter removes it.

### Conventions for every detector
- **Module:** `agent/detectors/<name>.py` with exactly one public function `detect_<name>(ds, **params) -> list[dict]`. The package `agent/detectors/__init__.py` discovers it on import (registry `DETECTORS`, runner `run_all`). Do not edit `__init__.py` or any other detector module.
- **`ds`** is `agent.data.Dataset` (#2): one pandas DataFrame per CSV, named after the file stem: `ds.suppliers`, `ds.customers`, `ds.employees`, `ds.invoices`, `ds.goods_receipts`, `ds.bank_transactions`, `ds.counterparty_bank`, `ds.ledger`, `ds.efos_69b`, plus `ds.company` (dict from `company.json`). Date columns are `datetime64`, money columns `float`, every ID / RFC / CLABE / folio / po_number / account_code is `str`, and empty cells are `""` (never NaN).
- **Pure function:** no I/O, no LLM, no network, never reads `hidden/`. Output must be deterministic: sort it.
- **Every returned dict is a lead, not an accusation.** It carries at least `entity_id` (the `S*`/`C*`/`E*` it points at) and `evidence` (list of record IDs that triggered it: invoice UUIDs, `TX*`, `CP*`, `GR*`), plus the fields listed below. Dates as ISO strings, money as float, everything `json.dumps`-able.
- **Test:** `tests/test_detect_<name>.py`. Fixtures from `tests/conftest.py`: `ds` (company_42 loaded), `scheme(type)` (that scheme's ground-truth dict), `decoy_ids` (set of the 5 decoy supplier IDs), `truth` (full dict). Only tests may read ground truth. Assert `json.dumps(result)` works.
- Run `python -m pytest -q` before opening the PR. No new dependencies. Small diff: one module + one test file.

### Ground-truth shape (for the test only)
`truth["schemes"]` is a list; `scheme(t)` returns the one with `type == t`. `truth["decoys"]` is a list of `{supplier_id, rfc, name, looks_like, why_honest}` (the law-firm decoy also has `invoice_uuid`). Identify a decoy by the start of `looks_like`: `"New vendor"`, `"Name almost"`, `"Shares address"`, `"Large one-off"`, `"Cash payments"`.

## Test: `tests/test_detect_new_vendor_round_amounts.py`
- `expected = {new_vendor_decoy["supplier_id"]} | {e["supplier_id"] for e in scheme("efos_fake_supplier")["entities"]} | {scheme("kickback_shell")["entities"][0]["supplier_id"], scheme("round_trip_sales")["entities"][0]["supplier_id"]}` where the decoy is the one whose `looks_like` starts with `"New vendor"`; assert `{r["entity_id"]} == expected`
- every row: `round_share >= 0.6`, `onboarded >= "2024-07-01"`, `n_invoices >= 1`, `len(evidence) == n_invoices`
- no other decoy in the result
- `detect_new_vendor_round_amounts(ds, since="2026-01-01") == []`

## Definition of done
- [ ] Module + test green; docstring says the new-vendor decoy is an expected lead
- [ ] `python -m pytest -q` green

**Depends on #2.** If #2 is still open, skip this issue.

---

## #12 Tool layer agent/tools.py  `cc`

## Goal
The only way the LLM touches data. Every tool returns JSON-serialisable dicts whose rows carry record IDs, so anything the model cites can be re-checked by the guard (#14). No tool ever produces a number the model could not point back to a row.

## Spec
```python
# agent/tools.py
class Tools:
    def __init__(self, ds: Dataset): ...
    def get_supplier(self, supplier_id: str) -> dict
    def get_customer(self, customer_id: str) -> dict
    def get_employee(self, employee_id: str) -> dict
    def get_invoices(self, counterparty_id: str, limit: int = 50) -> list[dict]
    def get_bank_txns(self, *, counterparty_clabe: str = "", invoice_uuid: str = "", direction: str = "", limit: int = 100) -> list[dict]
    def get_receipts(self, invoice_uuid: str) -> list[dict]
    def check_69b(self, rfc: str) -> dict
    def trace_flow(self, clabe: str, *, days: int = 10, min_ratio: float = 0.8, depth: int = 2) -> list[dict]
    def query_ledger(self, *, invoice_uuid: str = "", txn_id: str = "", account_code: str = "", limit: int = 100) -> list[dict]

TOOL_SCHEMAS: list[dict]   # OpenAI function-calling schemas, one per method, descriptions written for the model
```
Shapes:
- `get_supplier`: the master row + `efos: {listed, situacion, fecha_publicacion}` + `stats: {n_invoices, total_mxn, first_invoice, last_invoice, n_with_receipt, median_days_to_pay}` + `employee_links: [{employee_id, kind: "address"|"clabe"|"approver", detail}]`.
- `get_invoices`: invoice rows (drop `nombre_*`/`moneda`/`serie` noise) with `has_receipt`, `receipt_ids`, `paid_by` (txn ids), `days_to_pay` (first payment).
- `get_bank_txns`: rows of `bank_transactions` filtered by any combination of the keyword args.
- `check_69b`: `{rfc, listed: bool, situacion, fecha_publicacion, nombre, name_matches: [{rfc, nombre, situacion}]}` where `name_matches` are list entries whose `nombre` equals the supplier's name ignoring the legal suffix (`SA de CV` vs `S de RL de CV`). Exact RFC decides `listed`; `name_matches` exists so the model can *see* the decoy trap and explain why it is not a match.
- `trace_flow`: hops starting from `counterparty_bank` rows with `entity_clabe == clabe`, following `counterparty_clabe` up to `depth`; each hop `{hop, record_id or txn_id, fecha, from_clabe, to_clabe, amount, returns_to_company: bool}` where `returns_to_company` is true when a later `bank_transactions` `in` row from that CLABE exists within `days` and `≥ min_ratio` of the amount.
- `query_ledger`: ledger rows; lets the model see that a duplicate payment was booked to `6000` instead of `2100`.
- Every list is capped at `limit`, sorted deterministically, dates ISO strings, floats plain. Unknown IDs return `{"error": "... not found"}` rather than raising. Never touches `hidden/`.

## Test: `tests/test_tools.py`
- Pick IDs from the `scheme(...)` fixtures. `get_supplier` on an EFOS supplier: `efos.listed is True`, `stats.n_with_receipt == 0`. On the kickback shell: `employee_links` contains an `"address"` and an `"approver"` link to the same employee.
- `check_69b` on the name-twin decoy's RFC: `listed is False`, `name_matches` non-empty.
- `trace_flow` from the round-trip supplier's CLABE: a hop with `returns_to_company is True`.
- `get_bank_txns(invoice_uuid=<duplicate uuid>)` returns 2 rows; `query_ledger(txn_id=<duplicate txn>)` shows account `6000`.
- `json.dumps` succeeds on every tool result; every result is `≤ limit`; unknown ID → `error` key.
- `TOOL_SCHEMAS` names match the methods and each has `parameters.type == "object"`.

## Definition of done
- [ ] `agent/tools.py`, `tests/test_tools.py` green, `python -m pytest -q` green

**Depends on #2.**

---

## #13 Investigation loop agent/investigate.py  `cc`

## Goal
The agent: detectors produce leads, the LLM forms a hypothesis per lead and calls tools to prove or drop it, the guard (#14) keeps invented evidence out, and the result is a case file `data_estate/score.py` can score. The step log is what the demo shows on screen.

## Spec
CLI: `python -m agent.investigate <dataset_dir> [--out case_file.json] [--log runs/<timestamp>.jsonl] [--max-leads 12] [--max-steps 12] [--no-llm]`

Flow:
1. `load` (#2) → `agent.detectors.run_all(ds)` → group leads by `entity_id`; rank by (number of distinct detectors hit, `total_mxn`).
2. For each entity (up to `--max-leads`): build a dossier (all its leads with their fields) and run the LLM loop: system prompt = scheme types, the rule catalog from `agent/rules.py` (#14), the case-file contract, and the instruction that an accusation needs a rule, a peso amount and evidence IDs, or the lead is dropped with a reason. The model gets `TOOL_SCHEMAS` (#12) plus two terminal tools: `record_finding(scheme_type, accused, rule_id, amount_mxn, evidence, narrative)` and `drop_lead(entity_id, reason)`. `temperature=0`, at most `--max-steps` tool calls per lead, then force a decision.
3. Every `record_finding` goes through `guard` (#14); a rejected finding is logged and turned into a `drop_lead` with the guard's reason.
4. Write `findings[]` and `not_pursued[]` per the contract, validate with `agent.contract` (#3), write the file.
5. Step log, one JSON object per line: `{ts, entity_id, step, kind: "lead"|"hypothesis"|"tool_call"|"tool_result"|"decision"|"guard", payload}`. This is the demo's data source; keep it stable.

LLM access: the `openai` package (approved by this issue; add to `requirements.txt`) with `base_url=LLM_BASE_URL`, `api_key=LLM_API_KEY`, `model=LLM_MODEL` read from `.env`. Move the `.env` reader from `scripts/check_llm.py` into `agent/config.py` and use it from both. Nothing with dataset content goes anywhere else (AGENTS.md rule 8).

Speed: cache LLM responses keyed on a hash of (model, messages, tools) under `.cache/` (add to `.gitignore`); target ≤ 90 s for company_42 and print the wall time.

`--no-llm`: deterministic fallback that turns the four known scheme signatures (EFOS match; address match + counterparty outflow to employee; round-trip chain; duplicate payment + CLABE mismatch) into findings via the same guard, and lists everything else as not pursued with the detector's reason. This is the demo's safety net if the cluster is unreachable; it must also pass the DoD scores.

## Tests: `tests/test_investigate.py`
- A fake client (scripted tool calls and a final `record_finding`/`drop_lead`) drives one lead end to end without a network; asserts the log has `lead → hypothesis → tool_call → decision` and the case file validates.
- `--no-llm` on company_42: `score()` from `data_estate.score` gives `results_recall >= 0.75`, `judgment_penalty == 0`, `evidence_validity >= 0.9`, and `not_pursued` contains all five decoy IDs.
- `@pytest.mark.llm` end-to-end with the real endpoint, auto-skipped when `.env` is missing (CI has no `.env`).

## Definition of done
- [ ] `python -m agent.investigate data_estate/out/company_42 --out case_file.json` then `python -m data_estate.score data_estate/out/company_42 case_file.json`: `results_recall >= 0.75`, `judgment_penalty == 0`
- [ ] Same with `--no-llm`
- [ ] Every decoy appears in `not_pursued` with a reason a non-engineer can read
- [ ] `python -m pytest -q` green without `.env`

**Depends on #12 and #14**, and on detectors #4–#11 as they land (the loop must run with whatever subset is merged).

---

## #14 Evidence guard agent/guard.py + rule catalog agent/rules.py  `cc`

## Goal
"The LLM proposes, deterministic code proves." Nothing enters the case file unless every cited ID exists, the rule is one we recognise, and the peso amount is consistent with the records. This is the answer to "how do you know it did not hallucinate?".

## Spec
```python
# agent/rules.py
@dataclass(frozen=True)
class Rule:
    id: str                      # "R1".."R5"
    scheme_types: frozenset[str] # which scheme_type values it may be used with
    legal: str                   # citation text that goes into the case file's "rule" field
    evidence_kinds: frozenset[str]   # {"invoice","txn","cp","receipt"} that must be present
    amount: Callable[[Finding, Dataset], float]   # recompute the amount from the accused entities' records
RULES: dict[str, Rule]
```
Initial catalog (legal text must equal the strings in `data_estate/out/example_case_file_for_seed42.json` so that file passes):
- R1 EFOS deduction: `scheme_types={efos_fake_supplier}`, legal `"CFF Art. 69-B (operaciones inexistentes); CFF Art. 29-A; LISR Art. 27 (deducción improcedente)"`, evidence needs invoice + txn, amount = sum of `total` of the accused suppliers' `recibida` invoices.
- R2 kickback / related party: `{kickback_shell}`, legal = the kickback string from the example file, evidence needs invoice + txn + cp, amount = sum of the accused supplier's invoice totals.
- R3 round trip: `{round_trip_sales}`, legal `"Simulación de operaciones (CFF Art. 69-B / 113 Bis); revenue recognition — fictitious sales"`, evidence needs invoice + txn + cp, amount = sum of `total` of `emitida` invoices to the accused customer.
- R4 duplicate payment: `{duplicate_invoice_payment}`, legal `"Control failure / possible embezzlement; LISR Art. 27 (deducción duplicada)"`, evidence needs invoice + txn, amount = sum of the second-and-later payments per invoice for the accused supplier.
- R5 other: `{other}`, no amount recomputation, but evidence must exist and be non-empty.

```python
# agent/guard.py
def guard(finding: dict, ds: Dataset) -> tuple[dict | None, list[str]]:
    """Return (clean_finding, []) or (None, reasons). Never raises."""
```
Checks, in order, all reasons collected:
1. `agent.contract` (#3) checks on this single finding (IDs exist, no duplicates, amount > 0, scheme type known).
2. `rule` is a catalog id or exactly a catalog `legal` string; the finding's `scheme_type` is allowed for it. Output finding always carries the `legal` text in `rule`.
3. Every cited evidence ID belongs to an accused entity's records (its invoices, payments of those invoices, counterparty rows of its CLABE, receipts of its invoices). Evidence about someone else is a reason to reject.
4. Evidence kinds required by the rule are present.
5. `amount_mxn` within 25% of the rule's recomputation (the scorer's tolerance). On mismatch, reject with both numbers in the reason.
6. Strip unknown fields, dedupe `accused` and `evidence`, round `amount_mxn` to 2 decimals.

## Test: `tests/test_guard.py`
- Each of the four findings in the example case file passes unchanged (apart from rounding).
- Fabricated evidence `"TX99999"` → rejected, reason names it. Evidence from another supplier → rejected. `rule: "made up"` → rejected. `amount_mxn` ×3 → rejected with both numbers. Rule/scheme mismatch (R1 with `kickback_shell`) → rejected. `rule: "R1"` → accepted and rewritten to the legal text.

## Definition of done
- [ ] `agent/rules.py`, `agent/guard.py`, `tests/test_guard.py` green; `python -m pytest -q` green

**Depends on #2 and #3.**

---

## #15 requirements.txt + Makefile  `hermes-ok`

## Goal
One-command setup and the three commands everyone runs all day. CI already does `pip install -r requirements.txt` when the file exists.

## Spec
`requirements.txt`:
```
pandas>=2.2
pytest>=8
```
`Makefile` (tabs, `.PHONY` for every target, `PY ?= python` so it works inside or outside the venv):
- `venv`: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- `test`: `$(PY) -m pytest -q`
- `validate`: `$(PY) -m data_estate.validate data_estate/out/company_42`
- `gen`: `SEED ?= 7`; refuses `SEED=42` (`company_42` is frozen; exit 1 with a message) then `$(PY) -m data_estate.generate --seed $(SEED) --out data_estate/out/company_$(SEED)`
- `score`: `DATASET ?= data_estate/out/company_42`, `CASE ?= data_estate/out/example_case_file_for_seed42.json`; `$(PY) -m data_estate.score $(DATASET) $(CASE)`
- `check-llm`: `$(PY) scripts/check_llm.py`
- `help` (default target): one line per target

Also add a "Setup" line to `README.md` pointing at `make venv`, and mention the targets in `AGENTS.md` "How to run things". Do not touch anything else.

## Test: `tests/test_makefile.py`
- `subprocess.run(["make", "gen", "SEED=42"], cwd=repo_root)` returns non-zero and `tests/test_frozen_dataset.py`'s digest is unchanged afterwards (import and call `digest`).
- `make -n score` output contains `data_estate.score` and the example case-file path; `make -n test` contains `pytest`.
- `make gen SEED=<random 1000–9999>` with `cwd=tmp` is not needed; instead run `make -n gen SEED=7` and assert it contains `company_7`.
- Skip the whole file with `pytest.skip` when `make` is not on PATH.

## Definition of done
- [ ] `make test` green; `make gen SEED=7` then `python -m data_estate.validate data_estate/out/company_7` passes (do not commit `company_7`; it is gitignored)
- [ ] `make score` prints `"results_recall": 1.0` for the example file
- [ ] CI green with `requirements.txt` present

---

## #16 ruff config + fix lint in data_estate/  `hermes-ok`

## Goal
Lint without behaviour change. `data_estate/` is the generator of every dataset we will ever score; a "cleanup" that changes one random call would silently change every seed.

## Spec
- Add to `pyproject.toml`:
  ```toml
  [tool.ruff]
  line-length = 120
  target-version = "py312"
  [tool.ruff.lint]
  select = ["E", "F", "I", "B", "UP"]
  ```
- Run `ruff check data_estate --fix` and fix what remains by hand, **in `data_estate/` only**. Do not touch `agent/`, `tests/`, `scripts/`, or `data_estate/out/`.
- ruff is a dev tool approved by this issue: install it in your venv, do **not** add it to `requirements.txt` or to CI.
- Determinism check, mandatory before the PR:
  ```
  python -m data_estate.generate --seed 42 --out /tmp/c42 && diff -r /tmp/c42 data_estate/out/company_42 && echo SAME
  ```
  must print `SAME`. If it does not, revert the change that broke it; do not "fix" the frozen dataset.

## Test
No new test file. Existing `tests/test_frozen_dataset.py`, `tests/test_estate.py` and `python -m data_estate.validate data_estate/out/company_42` must stay green.

## Definition of done
- [ ] `ruff check data_estate` clean
- [ ] `python -m pytest -q` green, validate green, regeneration diff empty (`SAME`)
- [ ] PR body shows the `SAME` line from the determinism check

---

## #17 --n flag for generate.py (batch of seeds)  `hermes-ok`

## Goal
Batch evaluation over many seeds ("mean recall ≥ 0.8, penalty 0 on every seed" in `docs/PLAN.md`) needs many datasets in one command.

## Spec
- `python -m data_estate.generate --seed 100 --n 5 --out data_estate/out/batch_100` writes `batch_100/company_100/ … batch_100/company_104/`, one summary line each (same format as today).
- `--n 1` (default) keeps today's behaviour exactly: writes to `--out` itself, not nested.
- Change **only** `main()` in `data_estate/generate.py`: loop over `range(seed, seed + n)`, call `Generator(s).build(schemes)` and `write_estate(...)`. Do not touch `Generator`, `renumber`, or any constant. Seed 42 must remain byte-identical (`python -m data_estate.generate --seed 42 --out /tmp/c42 && diff -r /tmp/c42 data_estate/out/company_42`).
- Update the usage block at the top of `generate.py` and the command table in `data_estate/README.md`.

## Test: `tests/test_generate_batch_flag.py`
- Run `python -m data_estate.generate --seed 500 --n 2 --out <tmp>/b` via `subprocess` (cwd = repo root): `<tmp>/b/company_500` and `<tmp>/b/company_501` exist and `data_estate.validate.check` returns `[]` for both.
- `--seed 7 --n 1 --out <tmp>/single`: `<tmp>/single/invoices.csv` exists (not nested).
- `--n 0` or negative exits non-zero.

## Definition of done
- [ ] Flag works as specified, test green, `python -m pytest -q` green, determinism diff empty

---

## #18 tests/test_generate_batch.py: 5 seeds validate  `hermes-ok`

## Goal
Catch generator bugs that only appear on some seeds before a judge does. `tests/test_estate.py` covers seeds 1–3; this covers five new seeds every day.

## Spec: `tests/test_generate_batch.py`
- Choose seeds reproducibly per day: `rng = random.Random(os.environ.get("BATCH_SEED", date.today().isoformat()))`, `seeds = rng.sample(range(1_000, 100_000), 5)`. Same seeds all day for everyone (a failure is reproducible), new seeds tomorrow.
- For each seed: `Generator(seed).build(schemes)` with `schemes` cycling through `["efos","kickback","roundtrip","duplicate"]`, `[]` (clean books) and a random non-empty subset, then `write_estate(...)` into `tmp_path / f"c{seed}"` and `assert check(path) == [], f"seed {seed} schemes {schemes}: {errs[:5]}"`.
- Also assert `len(truth["schemes"]) == len(schemes)` and `len(truth["decoys"]) == 5` by reading the written `hidden/ground_truth.json` (allowed in tests).
- Keep it under ~3 s (generation is ~0.1 s per seed). Use `Generator`/`write_estate`/`check` directly; no subprocess.
- If a seed fails, do **not** hide it: comment on this issue with the seed and the first errors, and leave the test red in the PR so a human sees it.

## Definition of done
- [ ] Test present and green today; `python -m pytest -q` green
- [ ] `BATCH_SEED=anything python -m pytest -q tests/test_generate_batch.py` also green
