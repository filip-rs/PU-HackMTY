"""tests/test_api_server.py (#68): the stdlib HTTP + SSE API the frontend drives.

Every request goes through a real socket with ``urllib.request`` -- no ``requests``,
no test client -- so what the frontend will see is what is asserted here. The server
is bound on port 0 and served in a thread per test, with ``runs/`` and the generator
out-root inside ``tmp_path``.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from api import server as api_server

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def api(tmp_path):
    """A served API on a free port; returns a small client bound to its base URL."""
    httpd = api_server.serve("127.0.0.1", 0, tmp_path / "runs", tmp_path / "out")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address[:2]
    client = _Client(f"http://{host}:{port}", tmp_path)
    try:
        yield client
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


class _Client:
    def __init__(self, base: str, tmp_path: Path) -> None:
        self.base = base
        self.tmp_path = tmp_path

    def request(self, path: str, *, method: str = "GET", body: dict | None = None,
                headers: dict | None = None, timeout: float = 30.0):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers=headers or {})
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8"), dict(resp.headers)
        except urllib.error.HTTPError as err:
            return err.code, err.read().decode("utf-8"), dict(err.headers)

    def json(self, path: str, **kw):
        status, text, headers = self.request(path, **kw)
        return status, (json.loads(text) if text else None), headers

    def stream(self, path: str, *, headers: dict | None = None, timeout: float = 10.0) -> str:
        req = urllib.request.Request(self.base + path, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.fp.raw._sock.settimeout(timeout)  # noqa: SLF001 - bound the SSE read
            return resp.read().decode("utf-8")


def _finished_run(api: _Client, dataset: str = "company_42", timeout: float = 120.0) -> str:
    """Start a no-LLM run and poll until it is done; returns the run id."""
    status, body, _ = api.json("/runs", method="POST", body={"dataset": dataset, "no_llm": True})
    assert status == 202, body
    run_id = body["run_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, entry, _ = api.json(f"/runs/{run_id}")
        if entry["status"] in ("done", "failed"):
            assert entry["status"] == "done", entry
            return run_id
        time.sleep(0.2)
    raise AssertionError(f"run {run_id} did not finish in {timeout}s")


# ------------------------------------------------------------------------ health
def test_health_reports_llm_configuration_without_leaking_credentials(api):
    status, body, headers = api.json("/health")
    assert status == 200
    assert body["ok"] is True
    assert "llm_configured" in body
    assert "model" in body
    assert "api_key" not in body and "base_url" not in body
    assert json.dumps(body).lower().find("llm_api_key") == -1
    assert headers["Access-Control-Allow-Origin"] == "*"


def test_options_preflight_is_204_with_cors(api):
    status, _, headers = api.request("/runs", method="OPTIONS")
    assert status == 204
    assert headers["Access-Control-Allow-Origin"] == "*"
    assert "POST" in headers["Access-Control-Allow-Methods"]


# ---------------------------------------------------------------------- datasets
def test_datasets_lists_company_42_without_naming_the_answer_key(api):
    status, body, _ = api.json("/datasets")
    assert status == 200
    by_name = {d["name"]: d for d in body}
    assert "company_42" in by_name
    entry = by_name["company_42"]
    assert entry["has_truth"] is True
    assert entry["n_invoices"] > 0
    assert entry["n_suppliers"] > 0
    assert entry["n_bank_txns"] > 0
    assert "ground_truth" not in json.dumps(body)
    assert body == sorted(body, key=lambda d: d["name"])


def test_entities_maps_ids_to_kinds(api):
    status, body, _ = api.json("/datasets/company_42/entities")
    assert status == 200
    assert body["S00030"]["kind"] == "supplier"
    assert body["S00030"]["name"]
    assert body["E00002"]["kind"] == "employee"
    assert "COMPANY" in body


def test_post_datasets_refuses_the_frozen_seed(api):
    status, body, _ = api.json("/datasets", method="POST", body={"seed": 42})
    assert status == 409
    assert "frozen" in body["error"]


def test_post_datasets_generates_a_clean_estate(api):
    status, body, _ = api.json(
        "/datasets", method="POST", body={"seed": 9001, "schemes": "clean"}, timeout=120
    )
    assert status == 201, body
    assert body["name"] == "company_9001"
    assert (api.tmp_path / "out" / "company_9001" / "company.json").exists()
    assert body["has_truth"] is True

    status, entities, _ = api.json("/datasets/company_9001/entities")
    assert status == 200
    assert "COMPANY" in entities


def test_post_datasets_rejects_an_unknown_scheme(api):
    status, body, _ = api.json("/datasets", method="POST", body={"seed": 9002, "schemes": "nope"})
    assert status == 400
    assert "nope" in body["error"]


# -------------------------------------------------------------------------- runs
def test_unknown_run_is_a_404_json_body(api):
    status, body, _ = api.json("/runs/nope")
    assert status == 404
    assert "error" in body


def test_full_run_produces_case_report_score_log_and_events(api):
    run_id = _finished_run(api)

    status, entry, _ = api.json(f"/runs/{run_id}")
    assert entry["status"] == "done"
    assert entry["dataset"] == "company_42"
    assert entry["n_findings"] == 4

    status, case, _ = api.json(f"/runs/{run_id}/case")
    assert status == 200
    assert len(case["findings"]) == 4

    status, result, _ = api.json(f"/runs/{run_id}/score")
    assert status == 200
    assert result["results_recall"] == 1.0
    assert result["judgment_penalty"] == 0

    status, text, headers = api.request(f"/runs/{run_id}/report")
    assert status == 200
    assert headers["Content-Type"].startswith("text/markdown")
    assert text.startswith("#")

    status, entries, _ = api.json(f"/runs/{run_id}/log")
    assert status == 200
    assert entries[0]["kind"] == "run_start"
    assert entries[-1]["kind"] == "run_end"

    body = api.stream(f"/runs/{run_id}/events?after=0")
    assert body.count("data: ") >= 34
    assert body.rstrip().endswith('event: end\ndata: {"status": "done"}')

    later = api.stream(f"/runs/{run_id}/events", headers={"Last-Event-ID": "30"})
    steps = [int(line.split(": ", 1)[1]) for line in later.splitlines() if line.startswith("id: ")]
    assert steps and min(steps) > 30

    _, listing, _ = api.json("/runs")
    assert [e["run_id"] for e in listing] == [run_id]


def test_a_second_run_while_one_is_in_progress_is_409(api, monkeypatch):
    real = api_server.run_investigation

    def slow(*args, **kwargs):
        time.sleep(1.0)
        return real(*args, **kwargs)

    monkeypatch.setattr(api_server, "run_investigation", slow)

    status, first, _ = api.json("/runs", method="POST", body={"dataset": "company_42", "no_llm": True})
    assert status == 202
    status, second, _ = api.json("/runs", method="POST", body={"dataset": "company_42", "no_llm": True})
    assert status == 409
    assert second["run_id"] == first["run_id"]
    assert "in progress" in second["error"]


def test_run_on_an_unknown_dataset_is_404(api):
    status, body, _ = api.json("/runs", method="POST", body={"dataset": "company_does_not_exist"})
    assert status == 404
    assert "error" in body


def test_artifacts_are_404_until_the_run_is_done(api, monkeypatch):
    def slow(*args, **kwargs):
        time.sleep(2.0)
        raise RuntimeError("stopped on purpose")

    monkeypatch.setattr(api_server, "run_investigation", slow)
    _, body, _ = api.json("/runs", method="POST", body={"dataset": "company_42", "no_llm": True})
    run_id = body["run_id"]
    assert api.json(f"/runs/{run_id}/case")[0] == 404
    assert api.json(f"/runs/{run_id}/report")[0] == 404
    assert api.json(f"/runs/{run_id}/score")[0] == 404


def test_a_failed_run_is_reported_as_failed(api, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(api_server, "run_investigation", boom)
    _, body, _ = api.json("/runs", method="POST", body={"dataset": "company_42", "no_llm": True})
    run_id = body["run_id"]
    deadline = time.time() + 10
    while time.time() < deadline:
        _, entry, _ = api.json(f"/runs/{run_id}")
        if entry["status"] == "failed":
            assert "detector exploded" in entry["error"]
            return
        time.sleep(0.1)
    raise AssertionError("run never reached the failed state")


def test_runs_from_an_earlier_process_are_discovered_on_disk(api):
    runs_dir = api.tmp_path / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "20250101T000000Z-abcd.jsonl").write_text(
        json.dumps({"ts": "2025-01-01T00:00:00+00:00", "entity_id": "", "step": 1,
                    "kind": "run_start",
                    "payload": {"dataset": "company_42", "n_leads": 1, "mode": "no-llm", "model": ""}})
        + "\n",
        encoding="utf-8",
    )
    _, listing, _ = api.json("/runs")
    found = {e["run_id"]: e for e in listing}
    assert "20250101T000000Z-abcd" in found
    assert found["20250101T000000Z-abcd"]["status"] == "failed"
    assert found["20250101T000000Z-abcd"]["dataset"] == "company_42"


def test_events_stream_tails_a_run_that_is_still_going(api):
    """Connect while the run is live: events arrive, then a terminating end event."""
    _, body, _ = api.json("/runs", method="POST", body={"dataset": "company_42", "no_llm": True})
    run_id = body["run_id"]
    stream = api.stream(f"/runs/{run_id}/events?after=0", timeout=120)
    assert "event: run_start" in stream
    assert "event: run_end" in stream
    # The end event states the run's outcome, not the state it was in when run_end
    # was logged: the thread still has the case file and the report to write.
    assert stream.rstrip().endswith('event: end\ndata: {"status": "done"}')
    assert socket.getdefaulttimeout() is None
