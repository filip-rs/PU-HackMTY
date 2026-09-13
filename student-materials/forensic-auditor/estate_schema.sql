-- ============================================================================
-- Forensic Auditor - DATA ESTATE SCHEMA
--
-- This is a FORMAT SPEC, not a dataset. You build the data yourself: write a
-- generator, or adapt a dataset supplied with the problem statement.
--
-- Field names follow CFDI 4.0 and Mexican accounting conventions (uso_cfdi,
-- forma_pago, metodo_pago, RFC, UUID, CLABE). Keep them. Judges read these
-- column names directly when inspecting your estate, and every Finding
-- exhibit cites a `source_table` value from this schema by name.
--
-- The commented rows below show FIELD SHAPE ONLY. The values are placeholders.
-- ============================================================================

CREATE TABLE vendors (
    rfc             TEXT PRIMARY KEY,   -- 12-13 char Mexican tax id
    legal_name      TEXT,
    registered_date TEXT,               -- ISO 8601
    address         TEXT,
    bank_clabe      TEXT,               -- 18-digit Mexican interbank account
    category        TEXT,
    contact_email   TEXT
);
-- AAAA010101AA1 | Proveedor Ejemplo Uno SA de CV | 2025-01-15 | Calle Ejemplo 100, Monterrey | 000000000000000001 | Consultoria   | uno@example.mx
-- BBBB020202BB2 | Proveedor Ejemplo Dos SC       | 2024-06-30 | Av. Ejemplo 200, Monterrey   | 000000000000000002 | Mantenimiento | dos@example.mx

CREATE TABLE invoices (
    uuid          TEXT PRIMARY KEY,     -- CFDI UUID; your own id scheme is acceptable
    issuer_rfc    TEXT,
    receiver_rfc  TEXT,
    issue_date    TEXT,
    subtotal      REAL,
    iva           REAL,                 -- 16% VAT
    total         REAL,                 -- cited for peso reconciliation
    concepto_text TEXT,                 -- free-text line description
    uso_cfdi      TEXT,                 -- SAT catalog code, e.g. G03
    forma_pago    TEXT,                 -- SAT catalog code, e.g. 03
    metodo_pago   TEXT,                 -- PUE | PPD
    status        TEXT                  -- vigente | cancelado
);
-- INV-00001 | AAAA010101AA1 | EMP920101AB1 | 2026-02-15 | 80000.00 | 12800.00 | 92800.00 | Servicios de ejemplo     | G03 | 03 | PUE | vigente
-- INV-00002 | BBBB020202BB2 | EMP920101AB1 | 2026-02-27 | 40000.00 |  6400.00 | 46400.00 | Mantenimiento de ejemplo | G03 | 03 | PUE | vigente

CREATE TABLE ledger (
    entry_id     INTEGER PRIMARY KEY,
    date         TEXT,
    account_code TEXT,
    account_name TEXT,
    debit        REAL,
    credit       REAL,
    description  TEXT,
    invoice_uuid TEXT,                  -- nullable; links a GL entry to an invoice
    cost_center  TEXT,
    approver     TEXT                   -- who signed off, or evidence that nobody did
);
-- 1 | 2026-02-15 | 5000 | Gastos operativos | 92800.00 |     0.00 | Registro factura | INV-00001 | CC-100 Produccion | A. Ejemplo
-- 2 | 2026-02-15 | 2100 | Cuentas por pagar |     0.00 | 92800.00 | Registro factura | INV-00001 | CC-100 Produccion | B. Ejemplo

CREATE TABLE bank_txns (
    txn_id     TEXT PRIMARY KEY,
    date       TEXT,
    from_clabe TEXT,
    to_clabe   TEXT,
    amount     REAL,                    -- cited for peso reconciliation
    reference  TEXT,
    channel    TEXT                     -- SPEI | cheque | efectivo
);
-- BNK-00001 | 2026-03-29 | 000000000000000099 | 000000000000000001 | 92800.00 | Pago factura INV-00001 | SPEI
-- BNK-00002 | 2026-03-16 | 000000000000000099 | 000000000000000002 | 46400.00 | Pago factura INV-00002 | SPEI

CREATE TABLE purchase_orders (
    po_id       TEXT PRIMARY KEY,
    vendor_rfc  TEXT,
    date        TEXT,
    amount      REAL,
    requester   TEXT,
    approver    TEXT,                   -- the approval-limit trail lives here
    description TEXT
);
-- PO-00001 | BBBB020202BB2 | 2026-02-20 | 46400.00 | C. Ejemplo | D. Ejemplo | Mantenimiento mensual de ejemplo

CREATE TABLE contracts (
    contract_id TEXT PRIMARY KEY,
    vendor_rfc  TEXT,
    start_date  TEXT,
    value       REAL,
    scope_text  TEXT
);
-- CTR-00001 | BBBB020202BB2 | 2024-07-01 | 556800.00 | Contrato marco, cuota mensual fija

CREATE TABLE employees (
    emp_id     TEXT PRIMARY KEY,        -- cited in Finding entities as "EMP:0001"
    name       TEXT,
    role       TEXT,
    bank_clabe TEXT,                    -- required for any employee-linkage scheme
    hire_date  TEXT
);
-- EMP:0001 | Persona Ejemplo Uno | Gerente de Compras | 000000000000000501 | 2021-03-01

CREATE TABLE efos_list (
    rfc              TEXT PRIMARY KEY,
    legal_name       TEXT,
    status           TEXT,              -- definitivo | presunto
    publication_date TEXT
);
-- The SAT Articulo 69-B list is published by the Mexican tax authority as a
-- downloadable CSV. XAXX010101000 is the well-known generic placeholder RFC.
-- AAAA010101AA1 | Proveedor Ejemplo Uno SA de CV | definitivo | 2025-12-11
