# Case File — Required Structure

The case file is the artifact a judge reads. It is scored on whether a **non-technical** reader can follow it unaided, start to finish, without narration from your team.

This document specifies the required sections. The content is yours.

---

## Required sections, in this order

### 1. Header
Company name, audit period, estate seed, and the run's cost figures: LLM call count, MXN cost, wall-clock seconds. State whether the run is deterministic.

### 2. Executive summary
What was found, in plain language, in a few sentences. Include a summary table:

| | |
|---|---|
| Findings | *count, with confidence levels* |
| Total exposure | *pesos* |
| Leads investigated and closed | *count* |

A judge who reads only this section should understand the result.

### 3. One section per finding

Each finding section contains, in order:

| Element | Requirement |
|---|---|
| **Heading** | Entity name and id, scheme type |
| **Rule broken** | The specific rule or article. Not a description of a statistical pattern. |
| **Amount and confidence** | Pesos, and `proven` or `probable` |
| **What happened** | Plain-language narrative, under 150 words |
| **Money trail** | **A rendered diagram, not prose.** Prose-only caps Clarity at 3. Every step cites an exhibit id. |
| **Exhibits table** | Exhibit id, source table, record id, and one sentence on what each proves |
| **Reconciliation** | The arithmetic showing the claimed amount equals the sum of cited exhibits |

If your system runs an adversarial review, include what it argued and why the finding survived. A finding that no one tried to break is weaker than one that was attacked and held.

### 4. Leads not pursued

**This belongs in the body of the case file, not an appendix.** One entry per lead that was investigated and closed without an accusation:

- The entity, named
- Which detector or check pointed you there
- The specific reason it was closed, referencing the evidence examined
- Which tools were called — this distinguishes an investigated lead from a skipped one
- What closed it: the investigator, the adversarial reviewer, or the validator

A judge will pick an entity from this section and ask why you did not flag it. The answer must be readable directly from the page.

### 5. Method and limits

- The architecture, in a few sentences
- What was **out of scope** for this run
- What your system **cannot** detect
- Reproducibility: what a reader must do to regenerate this file

Stating limits plainly scores better than implying completeness you cannot defend.

---

## Format

Any format a judge can open and read without your laptop: rendered HTML, PDF, or Markdown. The money trail must render as a diagram in whatever format you choose.

Your system must be able to produce the case file **without a network call** — judges may ask you to demonstrate this with connectivity disabled.
