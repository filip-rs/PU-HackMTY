"""Our code is held to the judges' pack itself, not to copies of it typed into Python (#122).

The pack under ``scripts/judges/`` is vendored verbatim. Each test here parses one of those
files and checks the constant, enum or structure our code carries against it. When the
judges re-issue the pack, drop the new files in and this file names what moved.

Tests may read ``hidden/``; nothing under ``agent/`` may.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "scripts" / "judges"
ESTATE_42 = ROOT / "data_estate" / "out" / "estate_42"
COMPANY_42 = ROOT / "data_estate" / "out" / "company_42"
# The original pack, present only on a dev machine that has it next to the repo.
ORIGINAL = ROOT.parent / "student-materials" / "student-materials"


def _tables_from_sql(text: str) -> dict[str, list[str]]:
    """``{table: [columns in order]}`` from CREATE TABLE statements, ignoring comments."""
    tables: dict[str, list[str]] = {}
    for match in re.finditer(r"CREATE TABLE (\w+)\s*\((.*?)\);", text, re.S):
        columns = []
        for line in match.group(2).splitlines():
            line = line.split("--")[0].strip().rstrip(",")
            if line:
                columns.append(line.split()[0])
        tables[match.group(1)] = columns
    return tables


@pytest.fixture(scope="module")
def submission_schema() -> dict:
    return json.loads((PACK / "submission_schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def truth_schema() -> dict:
    return json.loads((PACK / "ground_truth_schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def estate_42_submission(tmp_path_factory) -> dict:
    """A real submission built for the frozen judges' estate, deterministic path."""
    from agent.data import load
    from agent.investigate import run
    from agent.submit import build_submission

    out = tmp_path_factory.mktemp("sub")
    case = run(ESTATE_42 / "estate.db", out=str(out / "case.json"), log=str(out / "log.jsonl"), no_llm=True)
    return build_submission(case, load(ESTATE_42 / "estate.db"), [], {"seed": 42})


# --- estate_schema.sql -------------------------------------------------------

def test_export_schema_matches_the_judges_sql_column_for_column():
    from data_estate.export_judges import SCHEMA

    theirs = _tables_from_sql((PACK / "estate_schema.sql").read_text(encoding="utf-8"))
    assert set(theirs) == set(SCHEMA), f"tables differ: {set(theirs) ^ set(SCHEMA)}"
    for table, columns in theirs.items():
        assert SCHEMA[table] == columns, f"{table}: ours {SCHEMA[table]} vs theirs {columns}"


def test_export_ddl_string_matches_the_judges_sql():
    """The DDL we execute into estate.db is the judges' DDL, table for table."""
    from data_estate.export_judges import DDL

    theirs = _tables_from_sql((PACK / "estate_schema.sql").read_text(encoding="utf-8"))
    ours = _tables_from_sql(DDL)
    assert ours == theirs


def test_the_reader_loads_every_table_the_sql_declares():
    from agent.data import load

    theirs = _tables_from_sql((PACK / "estate_schema.sql").read_text(encoding="utf-8"))
    ds = load(ESTATE_42 / "estate.db")
    # Every judges' table lands somewhere in the Dataset; record_table must know all of
    # the id-bearing ones the validator can cite.
    cited = {"invoices", "bank_txns", "purchase_orders", "contracts", "ledger", "vendors", "employees", "efos_list"}
    assert cited == set(theirs)
    known = set(ds.record_table.values())
    assert {"invoices", "bank_txns", "purchase_orders", "contracts"} <= known, known


# --- submission_schema.json --------------------------------------------------

def test_scheme_enum_is_exactly_what_we_can_emit(submission_schema):
    from agent.submit import CONTROL_ONLY, SCHEME_MAP

    enum = set(submission_schema["_required_enums"]["scheme_type"])
    assert set(SCHEME_MAP.values()) == enum, "SCHEME_MAP must cover the enum, and nothing outside it"
    for internal in CONTROL_ONLY:
        assert internal not in SCHEME_MAP, f"{internal} is control-only and must never map to a scheme type"


def test_source_table_enum_is_the_schema_tables(submission_schema):
    from data_estate.export_judges import SCHEMA

    enum = set(submission_schema["_required_enums"]["source_table"])
    assert enum == set(SCHEMA), "exhibits may cite exactly the tables the estate has"


def test_amount_bearing_tables_are_the_ones_the_validator_sums(submission_schema):
    """Our reconciliation must sum the same tables the judges' validator sums."""
    from importlib import util

    from agent.reconcile import AMOUNT_COLUMN

    spec = util.spec_from_file_location("judges_validator", PACK / "validate_format.py")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert AMOUNT_COLUMN == module.AMOUNT_COLUMN
    assert module.PESO_TOLERANCE == __import__("agent.reconcile", fromlist=["PESO_TOLERANCE"]).PESO_TOLERANCE


def test_confidence_and_closed_by_enums(submission_schema, estate_42_submission):
    enums = submission_schema["_required_enums"]
    assert set(enums["confidence"]) == {"proven", "probable"}
    for finding in estate_42_submission["findings"]:
        assert finding["confidence"] in enums["confidence"]
    for lead in estate_42_submission["leads_not_pursued"]:
        if "closed_by" in lead:
            assert lead["closed_by"] in enums["closed_by"], lead["closed_by"]


def test_submission_carries_every_required_key(submission_schema, estate_42_submission):
    schema = submission_schema["submission"]
    assert set(schema["required"]) <= set(estate_42_submission)
    props = schema["properties"]
    for finding in estate_42_submission["findings"]:
        assert set(props["findings"]["items"]["required"]) <= set(finding), finding.keys()
        for exhibit in finding["exhibits"]:
            assert set(props["findings"]["items"]["properties"]["exhibits"]["items"]["required"]) <= set(exhibit)
        assert len(finding["exhibits"]) >= props["findings"]["items"]["properties"]["exhibits"]["minItems"]
    for lead in estate_42_submission["leads_not_pursued"]:
        assert set(props["leads_not_pursued"]["items"]["required"]) <= set(lead), lead.keys()
    assert set(props["run_metadata"]["required"]) <= set(estate_42_submission["run_metadata"])


def test_entity_ids_use_the_judges_prefixes(submission_schema, estate_42_submission):
    for finding in estate_42_submission["findings"]:
        for entity in finding["entities"]:
            assert entity.startswith(("RFC:", "EMP:")), entity


# --- ground_truth_schema.json ------------------------------------------------

def test_exported_ground_truth_matches_the_answer_key_schema(truth_schema):
    schema = truth_schema["ground_truth"]
    truth = json.loads((ESTATE_42 / "hidden" / "ground_truth.json").read_text(encoding="utf-8"))
    assert set(schema["required"]) <= set(truth)

    scheme_schema = schema["properties"]["schemes"]["items"]
    type_enum = set(scheme_schema["properties"]["type"]["enum"])
    difficulty_enum = set(scheme_schema["properties"]["difficulty"]["enum"])
    assert truth["schemes"], "estate_42 plants schemes"
    for scheme in truth["schemes"]:
        assert set(scheme_schema["required"]) <= set(scheme), scheme.keys()
        assert scheme["type"] in type_enum
        assert scheme["difficulty"] in difficulty_enum

    decoy_schema = schema["properties"]["decoys"]["items"]
    for decoy in truth["decoys"]:
        assert set(decoy_schema["required"]) <= set(decoy), decoy.keys()


def test_export_scheme_map_targets_the_answer_key_enum(truth_schema):
    from data_estate.export_judges import SCHEME_MAP

    enum = set(truth_schema["ground_truth"]["properties"]["schemes"]["items"]["properties"]["type"]["enum"])
    assert {judges for judges, _difficulty in SCHEME_MAP.values()} <= enum


# --- results_table_template.csv ----------------------------------------------

def test_results_table_columns_are_the_template_header():
    from scripts.eval_batch import RESULTS_TABLE_COLUMNS, RESULTS_TABLE_HEADER

    with (PACK / "results_table_template.csv").open(encoding="utf-8") as fh:
        rows = [r for r in csv.reader(fh) if r and not r[0].startswith("#")]
    assert rows[0] == RESULTS_TABLE_COLUMNS
    assert RESULTS_TABLE_HEADER == ",".join(rows[0])


# --- case_file_structure.md --------------------------------------------------

# The pack numbers five sections; our report names them as headings. Section 3 in the
# pack is "One section per finding", which the report renders under a "Findings" heading
# with one subsection per finding.
_SECTION_TO_HEADING = {
    "Header": "## Header",
    "Executive summary": "## Executive summary",
    "One section per finding": "## Findings",
    "Leads not pursued": "## Leads not pursued",
    "Method and limits": "## Method and limits",
}


def test_report_has_the_five_required_sections_in_order(tmp_path):
    from agent.data import load
    from agent.investigate import run
    from agent.report import render

    required = re.findall(r"^### \d+\. (.+)$", (PACK / "case_file_structure.md").read_text(encoding="utf-8"), re.M)
    assert len(required) == 5, required
    case = run(COMPANY_42, out=str(tmp_path / "case.json"), log=str(tmp_path / "log.jsonl"), no_llm=True)
    markdown = render(case, load(COMPANY_42))
    positions = []
    for section in required:
        heading = _SECTION_TO_HEADING[section]
        assert heading in markdown, f"missing section {section!r} ({heading})"
        positions.append(markdown.index(heading))
    assert positions == sorted(positions), "sections are out of the pack's order"


# --- the vendored copies themselves ------------------------------------------

def test_vendored_validator_is_the_original_plus_one_comment_line():
    """Nobody may 'fix' the judges' validator. Only our first vendoring comment differs."""
    lines = (PACK / "validate_format.py").read_text(encoding="utf-8").splitlines(keepends=True)
    assert lines[0].startswith("# Vendored verbatim"), lines[0]
    body = "".join(lines[1:])
    assert body.startswith('"""Validate that a submission conforms to the required output format.')
    # The functions a judge runs are present and unchanged in name.
    for name in ("validate_structure", "validate_against_estate", "ID_COLUMN", "AMOUNT_COLUMN", "PESO_TOLERANCE"):
        assert name in body


@pytest.mark.skipif(not ORIGINAL.is_dir(), reason="the original pack is not next to this repo")
@pytest.mark.parametrize("name", [
    "estate_schema.sql", "submission_schema.json", "ground_truth_schema.json",
    "case_file_structure.md", "results_table_template.csv",
])
def test_vendored_file_is_byte_identical_to_the_original(name):
    ours = (PACK / name).read_bytes()
    theirs = (ORIGINAL / "forensic-auditor" / name).read_bytes()
    assert ours == theirs, f"scripts/judges/{name} drifted from the pack"


@pytest.mark.skipif(not ORIGINAL.is_dir(), reason="the original pack is not next to this repo")
def test_vendored_validator_body_is_byte_identical_to_the_original():
    ours = (PACK / "validate_format.py").read_text(encoding="utf-8").split("\n", 1)[1]
    theirs = (ORIGINAL / "forensic-auditor" / "validate_format.py").read_text(encoding="utf-8")
    assert ours == theirs
