"""The on-stage command, exercised without a reachable model."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def cli(*args):
    return subprocess.run(
        [sys.executable, "scripts/demo_run.py", *map(str, args)], cwd=ROOT,
        env={**os.environ, "LLM_BASE_URL": "http://127.0.0.1:9"},
        capture_output=True, text=True, timeout=60,
    )


def test_generated_run_writes_all_artifacts_outside_repo_runs(tmp_path):
    before = set((ROOT / "runs").glob("**/*"))
    result = cli("--seed", 101, "--schemes", "all", "--no-llm", "--runs", tmp_path)
    assert result.returncode == 0, result.stderr
    case_path, = tmp_path.glob("*_case.json")
    case = json.loads(case_path.read_text())
    log_path = case_path.with_name(case_path.name.replace("_case.json", ".jsonl"))
    assert log_path.read_bytes() == (tmp_path / "latest.jsonl").read_bytes()
    assert case_path.with_suffix(".md").is_file()
    assert (tmp_path / "submission.json").is_file()
    assert (tmp_path / "report.html").is_file()
    assert case["run_metadata"]["llm_calls"] == 0
    assert '"results_recall"' in result.stdout
    assert "Company:" in result.stdout
    for stage in ("generate", "validate", "judge sheet", "investigate", "report", "score"):
        assert f"TIME {stage}:" in result.stdout
    assert "LLM calls: 0" in result.stdout
    assert "MXN cost: 0" in result.stdout
    assert "wall-clock seconds:" in result.stdout
    sheet = result.stdout.split("Company:", 1)[1].split("TIME judge sheet:", 1)[0]
    assert "planted" not in sheet and "schemes" not in sheet
    truth = json.loads((ROOT / "data_estate/out/live/company_101/hidden/ground_truth.json").read_text())
    assert truth["meta"]["schemes"] == ["efos", "kickback", "roundtrip", "duplicate", "threshold", "revenue"]
    assert set((ROOT / "runs").glob("**/*")) == before


def test_frozen_seed_refused_before_generation(monkeypatch, capsys):
    from scripts import demo_run

    def forbidden(*args, **kwargs):
        raise AssertionError("attempted generation of frozen seed")

    monkeypatch.setattr(demo_run, "Generator", forbidden)
    with pytest.raises(SystemExit) as error:
        demo_run.main(["--seed", "42"])
    assert error.value.code == 2
    assert "data_estate/out/company_42" in capsys.readouterr().err


@pytest.mark.parametrize("schemes,expected", [("clean", []), (" EFOS, revenue,threshold ", ["efos", "revenue", "threshold"])])
def test_scheme_selection(schemes, expected, tmp_path):
    result = cli("--seed", 102, "--schemes", schemes, "--no-llm", "--runs", tmp_path)
    assert result.returncode == 0, result.stderr
    truth = json.loads((ROOT / "data_estate/out/live/company_102/hidden/ground_truth.json").read_text())
    assert truth["meta"]["schemes"] == expected


def test_unknown_scheme_is_usage_error(tmp_path):
    result = cli("--schemes", "typo", "--no-llm", "--runs", tmp_path)
    assert result.returncode == 2
    assert "unknown scheme" in result.stderr


@pytest.mark.parametrize("source", ["data_estate/out/company_42", "tests/fixtures/judges_mini", "data_estate/out/estate_42/estate.db"])
def test_existing_input_never_generated_or_truth_checked_for_estate(source, tmp_path, monkeypatch, capsys):
    from scripts import demo_run

    def forbidden(*a, **kw):
        raise AssertionError("existing input generated, validated, or estate truth checked")

    monkeypatch.setattr(demo_run, "Generator", forbidden)
    monkeypatch.setattr(demo_run, "check", forbidden)
    flag = "--dataset" if "company_42" in source else "--estate"
    if flag == "--estate":
        monkeypatch.setattr(demo_run, "dataset_entry", forbidden)
    args = [flag, str(ROOT / source), "--no-llm", "--runs", str(tmp_path)]
    if flag == "--dataset":
        args += ["--seed", "42"]
    assert demo_run.main(args) == 0
    output = capsys.readouterr().out
    assert len(list(tmp_path.glob("*_case.json"))) == 1
    if flag == "--estate":
        assert "SCORE" not in output
    if source.endswith(".db"):
        assert "PASS" in output
        assert json.loads((tmp_path / "submission.json").read_text())["seed"] == 42


def test_hand_edited_legacy_without_hidden_has_no_score(tmp_path):
    import shutil

    dataset = tmp_path / "edited"
    shutil.copytree(ROOT / "data_estate/out/company_42", dataset, ignore=shutil.ignore_patterns("hidden"))
    result = cli("--dataset", dataset, "--no-llm", "--runs", tmp_path / "output")
    assert result.returncode == 0, result.stderr
    assert "SCORE" not in result.stdout


def test_replay_log_flushes_every_source_line(tmp_path):
    import threading

    from scripts import demo_run

    assert hasattr(demo_run, "replay_log"), "missing paced replay helper"
    source = ROOT / "demo/sample_trace.jsonl"
    target = tmp_path / "replay.jsonl"
    worker = threading.Thread(target=demo_run.replay_log, args=(source, target, 0.01))
    worker.start()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert target.read_bytes() == source.read_bytes()


@pytest.mark.parametrize("replaying", [False, True])
def test_serve_registers_live_run_and_exposes_artifacts(tmp_path, replaying):
    import re
    import signal
    import time
    from urllib.request import urlopen

    stdout = tmp_path / "stdout.txt"
    options = (["--replay-from", "demo/sample_trace.jsonl"] if replaying else
               ["--dataset", "data_estate/out/company_42", "--no-llm", "--serve"])
    with stdout.open("w") as output:
        proc = subprocess.Popen(
            [sys.executable, "scripts/demo_run.py", *options,
             "--port", "0", "--runs", str(tmp_path / "runs")],
            cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
            env={**os.environ, "LLM_BASE_URL": "http://127.0.0.1:9"},
        )
        try:
            deadline = time.monotonic() + 35
            seen_running = False
            done = None
            while time.monotonic() < deadline:
                text = stdout.read_text()
                match = re.search(r"http://127.0.0.1:(\d+)", text)
                assert proc.poll() is None, text
                if match:
                    base = match.group(0)
                    with urlopen(base + "/runs", timeout=2) as response:
                        entries = json.load(response)
                    real = [entry for entry in entries if entry["run_id"] != "latest"]
                    seen_running |= any(entry["status"] == "running" for entry in real)
                    done = next((entry for entry in real if entry["status"] == "done"), None)
                    if done:
                        break
                time.sleep(0.05)
            assert seen_running and done, stdout.read_text()
            with urlopen(base + "/runs", timeout=2) as response:
                assert [entry["run_id"] for entry in json.load(response)] == [done["run_id"]]
            prefix = base + "/runs/" + done["run_id"]
            for suffix in ("/case", "/report", "/submission", "/report.html"):
                with urlopen(prefix + suffix, timeout=5) as response:
                    assert response.status == 200 and response.read()
            with urlopen(prefix + "/events", timeout=5) as response:
                assert b"event: end" in response.read()
            if replaying:
                assert done["run_id"].startswith("replay_")
                log = tmp_path / "runs" / (done["run_id"] + ".jsonl")
                assert log.read_bytes() == (ROOT / "demo/sample_trace.jsonl").read_bytes()
                assert "SCORE" not in stdout.read_text()
                case = json.loads((tmp_path / "runs" / (done["run_id"] + "_case.json")).read_text())
                assert case["run_metadata"]["replayed_from"]
                assert case["findings"]
                assert (tmp_path / "runs/submission.json").is_file()
                assert (tmp_path / "runs/report.html").is_file()
            proc.send_signal(signal.SIGINT)
            assert proc.wait(timeout=10) == 0, stdout.read_text()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def test_contract_failure_returns_one_and_marks_run_failed(tmp_path, monkeypatch, capsys):
    from scripts import demo_run

    registry = demo_run.RunRegistry(tmp_path)
    monkeypatch.setattr(demo_run, "RunRegistry", lambda _: registry)

    def fail(*a, **kw):
        raise RuntimeError("case file failed the contract: missing evidence")

    monkeypatch.setattr(demo_run, "run", fail)
    result = demo_run.main(["--estate", str(ROOT / "tests/fixtures/judges_mini"),
                            "--no-llm", "--runs", str(tmp_path)])
    assert result == 1
    assert "missing evidence" in capsys.readouterr().err
    entry, = registry.all()
    assert entry["status"] == "failed"
    assert "missing evidence" in entry["error"]
    assert not (tmp_path / "latest.jsonl").exists()


def test_bad_replay_reports_missing_start(tmp_path):
    source = tmp_path / "empty.jsonl"
    source.write_text("")
    result = cli("--replay-from", source, "--port", 0, "--runs", tmp_path / "runs")
    assert result.returncode == 1
    assert "no run_start" in result.stderr
    assert "Traceback" not in result.stderr


def test_make_demo_passes_seed_and_schemes_without_shell_expansion():
    result = subprocess.run(
        ["make", "--no-print-directory", "demo", "SEED=7", "SCHEMES=efos,revenue", "PYTHON=/bin/echo"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "scripts/demo_run.py --seed 7 --schemes efos,revenue --serve"


def test_injection_guide_covers_both_schemas_and_offline_fallbacks():
    guide = ROOT / "docs/INJECT.md"
    assert guide.is_file(), "missing judges' injection guide"
    text = guide.read_text()
    for required in ("--estate", "--dataset", "--replay-from", "--no-llm", "hidden/",
                     "threshold", "revenue", "efos_list", "bank_txns", "purchase_orders",
                     "employees", "counterparty_bank.csv", "Definitivo", "definitivo",
                     "personal_clabe", "home_street", "home_city", "five scheme types"):
        assert required in text


def test_generated_validation_failure_stops_before_investigation(tmp_path, monkeypatch, capsys):
    from scripts import demo_run

    monkeypatch.setattr(demo_run, "LIVE", tmp_path / "datasets")
    monkeypatch.setattr(demo_run, "check", lambda _: ["ledger unbalanced"])

    def forbidden(*args, **kwargs):
        raise AssertionError("investigation ran after validation failure")

    monkeypatch.setattr(demo_run, "run", forbidden)
    assert demo_run.main(["--seed", "103", "--no-llm", "--runs", str(tmp_path / "runs")]) == 1
    assert "ledger unbalanced" in capsys.readouterr().err
    assert not (tmp_path / "runs").exists()


def test_judges_validator_failure_preserves_successful_aliases(tmp_path, monkeypatch, capsys):
    from scripts import demo_run

    args = ["--estate", str(ROOT / "data_estate/out/estate_42/estate.db"),
            "--no-llm", "--runs", str(tmp_path)]
    assert demo_run.main(args) == 0
    assert "PASS" in capsys.readouterr().out
    aliases = {name: (tmp_path / name).read_bytes()
               for name in ("submission.json", "report.html", "latest.jsonl")}
    original = demo_run.run

    def invalid_submission(*args, **kwargs):
        case = original(*args, **kwargs)
        Path(kwargs["submission"]).write_text("{}")
        return case

    monkeypatch.setattr(demo_run, "run", invalid_submission)
    assert demo_run.main(args) == 1
    assert "FAIL" in capsys.readouterr().out
    assert {name: (tmp_path / name).read_bytes() for name in aliases} == aliases


def test_judges_validator_failure_returns_one(tmp_path, monkeypatch, capsys):
    from scripts import demo_run

    original = demo_run.run

    def invalid_submission(*args, **kwargs):
        case = original(*args, **kwargs)
        Path(kwargs["submission"]).write_text("{}")
        return case

    monkeypatch.setattr(demo_run, "run", invalid_submission)
    assert demo_run.main(["--estate", str(ROOT / "data_estate/out/estate_42/estate.db"),
                          "--no-llm", "--runs", str(tmp_path)]) == 1
    assert "FAIL" in capsys.readouterr().out
