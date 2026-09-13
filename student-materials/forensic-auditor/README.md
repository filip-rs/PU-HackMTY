# Forensic Auditor — Data Formats and Judging Rules

This folder specifies the **formats** your project must produce and consume, and the rules judges score against. It contains no dataset.

**You build your own data estate.** Write a generator, or adapt a dataset supplied with the problem statement. The schema below is the contract; the contents are yours.

## Files

| File | What it specifies |
|---|---|
| `estate_schema.sql` | The data estate schema — tables, columns, and CFDI 4.0 field names. Illustrative rows show field shape only. |
| `submission_schema.json` | The output format: findings, declined leads, run metadata |
| `ground_truth_schema.json` | The format of an evaluation answer key, so your harness and the judges' agree |
| `case_file_structure.md` | Required sections of the case file artifact |
| `submission_example.json` | Field shape only — placeholder values, not a worked solution |
| `validate_format.py` | Checks your output conforms. Structure only; no answer key, no scoring. |
| `results_table_template.csv` | The Results table shape |

## Using the validator

```bash
python3 validate_format.py --submission my_findings.json

# also confirm cited exhibits resolve against your own estate
python3 validate_format.py --submission my_findings.json --estate my_estate.db
```

Exits non-zero on a format error. Wire it into your build.

It checks format only. It cannot tell you whether your findings are correct — that needs ground truth for your estate, which you generate.

## What judges will run

Judges evaluate your system against **estates you have never seen**, generated to `estate_schema.sql` and containing a mix of planted schemes and decoys. Scheme counts and decoy counts vary by scenario, up to all five scheme types with ten decoys in one estate. Schemes may be **entangled** — two schemes sharing an entity, so a money trail crosses scheme boundaries.

The five scheme types your `scheme_type` field must use are fixed by the enum in `submission_schema.json`:

`phantom_vendor` · `kickback` · `round_tripping` · `threshold_splitting` · `revenue_inflation`

Your system must accept an estate at a path given at run time. Hardcoded paths fail.

## Rules that decide your score

**Recall is half the measure.** False accusations against decoys are weighted at least as heavily. A system that accuses every vendor reaches perfect recall and scores badly. Report both, as a table, across at least five held-out seeds.

**Report on seeds you did not tune on.** Name both sets in the pitch. They must be disjoint.

**Ground truth must be unreachable from the agent.** It may be referenced only from your evaluation harness — never from the agent, its tools, or anything they import. Judges may run:

```bash
grep -r 'ground_truth' your_project/src/ --include='*.py'
```

If ground truth appears to have leaked into the agent's reasoning — for instance, it names a scheme type before investigating — **Results caps at 2** regardless of the numbers.

**An accusation must validate before it is printed.** Every cited `record_id` must exist in the estate, and `peso_amount` must reconcile to the sum of cited exhibit amounts within 2%. Amounts reconcile **per table**: an invoice and the bank transfer that settled it are the same pesos seen twice, so citing a complete money trail is not penalised.

**Declined leads belong in the body of the case file.** Each with a specific reason naming the evidence examined. Judges will pick one and ask why you did not flag it; the answer must be readable from the page in under ten seconds without re-running anything.

**Have three numbers ready:** LLM call count, MXN cost, wall-clock seconds. "We don't know" scores low on Feasibility.

**Determinism.** The same seed must produce the same case file. Judges may run your seed twice.

**Replay without a network.** Your system must be able to reproduce a completed run with connectivity disabled.

## Questions judges ask

- "What happens if I change this input?"
- "Why should I trust this number?"
- "What does it do when it's wrong, or when there's nothing to find?"
- "Could a real audit team run this tomorrow?"
- "What did you cut, and why?"
- "Why didn't you flag vendor X?"
- "How confident are you in finding 2?"
- "What if the employee just happens to bank at the same institution?"

Answering from a log in under ten seconds is itself scored. Re-running your system to find out is the wrong answer even when the answer is right.
