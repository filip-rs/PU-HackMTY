# `api/` — the HTTP surface the frontend drives (#68)

Standard library only (`http.server.ThreadingHTTPServer`, `json`, `threading`); no FastAPI, no uvicorn
(AGENTS.md rule 4). It sits **outside** `agent/` because `GET /runs/{id}/score` imports `data_estate.score`,
which reads `hidden/ground_truth.json`; nothing from `hidden/` reaches any other response.

```bash
python -m api.server --host 127.0.0.1 --port 8765 --runs runs --out-root data_estate/out/live
```

Every response carries `Access-Control-Allow-Origin: *`, `Access-Control-Allow-Headers: Content-Type` and
`Access-Control-Allow-Methods: GET, POST, OPTIONS`; any `OPTIONS` returns 204 with those headers. Errors are
JSON `{"error": "<message>"}` with 400/404/409/500. All JSON is UTF-8, `ensure_ascii=False`.

| Method & path | Body / query | Returns |
|---|---|---|
| `GET /health` | | `{"ok": true, "llm_configured": bool, "model": "<LLM_MODEL or ''>"}` — never the key or the URL |
| `GET /datasets` | | `{"name", "path", "has_truth", "n_suppliers", "n_customers", "n_invoices", "n_bank_txns"}` for every dataset directory under `data_estate/out/` and `--out-root`, sorted by name |
| `POST /datasets` | `{"seed": int, "schemes": "all" \| "clean" \| "efos,kickback,roundtrip,duplicate"}` | 201 with that dataset's entry. Seed 42 → 409 (`company_42` is frozen). An existing directory is regenerated (deterministic). 500 with the errors when `data_estate.validate.check` rejects the result |
| `GET /datasets/{name}/entities` | | `{"S00004": {"name", "kind": "supplier", "category"}, "C00005": {…}, "E00002": {"name", "kind": "employee", "role"}, "COMPANY": {"name", "clabe"}}` |
| `POST /runs` | `{"dataset": "company_42" \| "<path>", "no_llm": false, "max_leads": 12, "max_steps": 12}` | 202 `{"run_id", "dataset", "log", "case", "report"}`. Runs in a background thread. One run at a time: while one is `running`, 409 `{"error": "a run is in progress", "run_id": "<that id>"}` |
| `GET /runs` | | newest-first `{"run_id", "dataset", "status": "running"\|"done"\|"failed", "started", "finished", "n_findings", "error"}`, including runs left in `--runs` by an earlier server process |
| `GET /runs/{id}` | | one entry as above, 404 if unknown |
| `GET /runs/{id}/events` | `?after=<step>`, or the `Last-Event-ID` header | `text/event-stream`: `id: <step>` / `event: <kind>` / `data: <the step-log line>` for every step after `after`. Tails a live run (250 ms poll, `: ping` every 15 s of silence) and closes with `event: end` + `{"status": …}` |
| `GET /runs/{id}/log` | | JSON array of every step-log entry so far |
| `GET /runs/{id}/case` | | the case file (404 until `done`) |
| `GET /runs/{id}/report` | | the markdown as `text/markdown; charset=utf-8` (404 until `done`) |
| `GET /runs/{id}/score` | | `data_estate.score.score(dataset, case)` (404 when the dataset has no hidden truth or the run is not `done`). **For the team and for judges who ask — the frontend must not show it by default.** |

`run_id` is `<UTC %Y%m%dT%H%M%SZ>-<4 hex>`. Artifacts land in `--runs`: `<run_id>.jsonl` (step log),
`<run_id>_case.json`, `<run_id>_case.md`.

The event line format is the step-log contract, `docs/STEP_LOG.md` (`agent/steplog.py` validates it);
`demo/sample_trace.jsonl` is a real run to build a frontend against without a backend.

Smoke test by hand:

```bash
python -m api.server &
curl -s -X POST localhost:8765/runs -H 'Content-Type: application/json' \
     -d '{"dataset":"company_42","no_llm":true}'
curl -N localhost:8765/runs/<id>/events        # ends with `event: end`
```
