# The judges' pack, vendored verbatim

Copied on 2026-09-12 from `student-materials/student-materials/` (the pack handed to teams on
2026-09-12), track folder `forensic-auditor/`. **Do not edit these files.** They are the
contract we are scored against; our code is tested *against them*, not against copies of
their contents typed into Python.

| File | What it fixes | Where our code is held to it |
|---|---|---|
| `estate_schema.sql` | the eight input tables, columns and order | `data_estate/export_judges.SCHEMA` and its `DDL`, `agent/data.py` (reader) |
| `submission_schema.json` | the output we are machine-checked on: scheme enum, exhibit tables, confidence, declined-lead fields, run metadata | `agent/submit.py`, `agent/guard.py`, `agent/reconcile.py` |
| `ground_truth_schema.json` | the answer-key shape our harness and the judges' must agree on | `data_estate/export_judges.py`, `data_estate/score.py` |
| `case_file_structure.md` | the five required sections of the case file, in order | `agent/report.py` |
| `results_table_template.csv` | the Results slide columns | `scripts/eval_batch.RESULTS_TABLE_COLUMNS` |
| `validate_format.py` | their format checker; `--estate` also checks record ids resolve and pesos reconcile within 2% | run in CI by `tests/test_submission_format.py`; first line is our one vendoring comment, the rest is byte-identical |
| `TRACK_README.md`, `PACK_README.md` | the rules judges score against, in their words | `docs/SPEC_GAP.md`, `demo/` |

`tests/test_judges_spec_conformance.py` parses these files and fails if the code drifts from
them. When the pack is re-issued, drop the new files here, run that test, and fix what it
names. On a machine that has the original `student-materials/` next to the repo, the same
test also checks every vendored file is still byte-identical to the original.
