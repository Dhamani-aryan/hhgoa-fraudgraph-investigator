# Project Progress

## Current gate

**Gate 0 — Repository, brief, and data contract: complete. Review findings
corrected; awaiting re-review.**

Gate 1 (TigerGraph graph and vector foundation) has not been started and will
not be started until Gate 0 is approved.

## Gate 0 checklist

- [x] Read the complete build plan, the official brief, and the dataset README
      before writing implementation code.
- [x] Create `PROGRESS.md`, `.env.example`, dependency metadata, and the agreed
      directory skeleton.
- [x] Record dataset file hashes, sizes, row counts, headers, time ranges, and
      the exact answer schema.
- [x] Prove the card/customer/transaction identifier mapping for all twenty
      benchmark cases.
- [x] Create Pydantic models and validators for the exact supplied answer
      format.
- [x] Run schema/validator tests on valid and invalid fixtures.

**Gate 0 exit:** the data contract is proven, all twenty triggers resolve, and
the answer schema is executable. No graph design assumption remains unverified.

## What was established

### The card identifier, which the plan marks as a hard stop

`transactions.csv` has no `card_id` column. `case_pack.csv` and
`closed_cases_history.csv` both reference cards as `<customer_id>-K<n>`.

The rule was derived from the data, not assumed:

1. `customer_id` is one-to-one with `card1` (13,553 each, zero customers with
   more than one `card1`).
2. Within a customer, `card6` (card type) is the only column that separates the
   labelled cards of every multi-card customer.
3. Cards are ordered by `card6` ascending with the missing value first and
   numbered from 1.

Proven against 14,975 labelled links — 14,955 closed-case transaction links
plus the 20 benchmark flagged transactions — with 14,975 exact matches, zero
mismatches and zero unresolved transactions.

### Data facts that constrain the design

- 590,742 transactions over 397 columns, no duplicate `TransactionID`.
- 144,432 identity rows, none attached to an `in_person` transaction. 151,072
  online transactions exist, so 6,640 online transactions carry no identity
  record and cannot yield a device profile.
- 5,565 closed cases: 4,665 confirmed fraud, 900 cleared. Patterns are heavily
  imbalanced — only 16 `card_testing` and 9 `undocumented`.
- `ts` is exactly linear in `TransactionDT` with a single offset
  (1467417600 = 2016-07-02 UTC), so it is derived event time with no timezone
  field. Treat it as naive local time.
- The history and the exam period do not overlap: every closed case closes by
  2016-11-06, and the benchmark opens from 2016-11-12.
- Email domains and billing regions are supernodes (`gmail.com` touches 9,332
  cards; `addr1=299.0` touches 2,075), while a strong device signature has a
  median of 1–2 cards. Shared-origin evidence must require time-local
  coordination, never raw degree.

### Gate 0 review corrections

Six findings from the Gate 0 review were fixed before any Gate 1 work.

1. **Submission readiness could pass without a graph write.** `R17` only asks
   whether `written_to_graph` matches reality, so an agent that skipped the
   write and honestly reported `written_to_graph=false` passed it and looked
   ready. New rule `R26` asks the question the challenge requires -- is the case
   really in the graph? -- and blocks when the flag is false, when no receipt
   was supplied, when the read-back failed, or when a confirmed write has no
   `graph_case_id`. `blocked` is a new outcome that does not make the answer
   invalid, matching the build plan's rule 26: a failed write leaves the answer
   valid but fails the submission gate until retried. Adversarial tests assert
   that the honest-but-unwritten answer has `R17 == PASSED` and `valid is True`
   while `R26 == BLOCKED` and `ready_for_submission is False`.
2. **The documented editable install could not succeed.** `pyproject.toml` had
   no `[build-system]`, and setuptools cannot auto-discover this flat
   multi-package layout. Added the build backend, listed the twelve packages
   explicitly, declared the GSQL as package data, and added the missing
   `app/components/__init__.py`.
3. **No dependency lock.** Added `requirements.lock.txt` with 114 pinned
   versions, verified by installing it into a clean virtual environment and
   running the suite there.
4. **README mixed the virtual environment with a bare `python`.** Every command
   now calls `.venv/Scripts/python` explicitly, both install routes are
   documented, and `bootstrap.py` names its own interpreter rather than
   printing a bare `python`.
5. **`vector` was missing from `TG_MCP_ALLOWED_TOOLS`.** The restricted MCP
   surface excluded the tool the challenge requires for case and policy memory.
   Added, with the reason recorded in the template.
6. **Polars `empty_as_null` was left implicit.** Both `explode` call sites now
   set it explicitly, pinning behaviour Polars 2.0 will change. Checked first
   that no closed case has an empty list, so the counts are unchanged.

### The answer contract is executable

The Pydantic models and the cross-field validator run today. Rules needing a
run trace report `skipped`, never `passed`, and a case with no confirmed graph
receipt is `blocked`, so an answer cannot look submission ready without both a
trace and a real write.

## Current blocker

**TigerGraph credentials are not yet supplied.** Gate 1 needs a Savanna
workspace (or Community Edition) and the `TG_*` values in `.env`.

`.venv/Scripts/python scripts/bootstrap.py` reports the missing variables by
name without printing any value.

No blocker remains inside Gate 0.

## Next action

Await Gate 0 review. On approval, begin Gate 1 with the first sub-step:
configure the TigerGraph workspace with auto-stop and auto-start, record the
setup without committing credentials, and confirm connectivity — then finalise
the graph schema against the audit results above.

First command for Gate 1:

```bash
cp .env.example .env
```

Fill the `TG_*` values locally, then:

```bash
.venv/Scripts/python scripts/bootstrap.py
```

## Verification commands

All commands use the virtual environment's interpreter explicitly.

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```

```bash
.venv/Scripts/python scripts/bootstrap.py
```

```bash
.venv/Scripts/python scripts/prove_card_mapping.py
```

```bash
.venv/Scripts/python scripts/run_data_audit.py
```

```bash
.venv/Scripts/python scripts/validate_all_cases.py
```

```bash
.venv/Scripts/python -m pytest tests/ -q
```

```bash
.venv/Scripts/python -m ruff check .
```

To reproduce the recorded results exactly, install from the pinned lock
instead:

```bash
.venv/Scripts/python -m pip install -r requirements.lock.txt
```

## Verification performed

- The six-page official brief was rendered and read in full; it agrees with the
  build plan's required components, deliverables and judging weights.
- The dataset README was downloaded and read in full. It is authority #1 and
  confirms the plan's answer contract, the fourteen actions, the three approval
  routes, and the R1–R10 policy.
- `scripts/prove_card_mapping.py` exits 0 with 14,975 of 14,975 labelled links
  matching.
- `scripts/run_data_audit.py` exits 0 with all six blocking checks passing, and
  reconciles with every count the dataset README states.
- `pytest tests/ -q` reports 124 passed, including 32 invalid answer fixtures
  each rejected for its intended rule and 5 adversarial graph-receipt tests.
- `scripts/validate_all_cases.py` exits 1 against the empty `cases/` directory
  and names all twenty missing cases, which is the correct state before the
  agent exists.
- `pip install -e ".[dev]"` succeeds and installs 78 packages including
  pyTigerGraph 2.0.4, tigergraph-mcp 1.0.3, langgraph 1.2.12 and
  streamlit 1.64.0. Every project package imports from outside the repository
  root, so the install does not rely on the working directory.
- `requirements.lock.txt` was installed into a clean virtual environment, where
  the suite reported 124 passed.
- Both data scripts were rerun with `-W error::DeprecationWarning` and exit 0,
  with the counts unchanged at 14,955 closed-case links and 14,975 of 14,975
  labelled links matching.

## Time spent

Block A (core setup, budget 2–3 hours): Gate 0 completed within budget, plus
one shorter pass to correct the six review findings.
