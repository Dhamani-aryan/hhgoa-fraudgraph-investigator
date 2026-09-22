# Project Progress

## Current gate

**Gate 0 — Repository, brief, and data contract: complete, awaiting review.**

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

### The answer contract is executable

The Pydantic models and the cross-field validator run today. Rules needing a
run trace report `skipped`, never `passed`, so an answer cannot look fully
validated without one.

## Current blocker

**TigerGraph credentials are not yet supplied.** Gate 1 needs a Savanna
workspace (or Community Edition) and the `TG_*` values in `.env`.

`python scripts/bootstrap.py` reports the missing variables by name without
printing any value.

No blocker remains inside Gate 0.

## Next action

Await Gate 0 review. On approval, begin Gate 1 with the first sub-step:
configure the TigerGraph workspace with auto-stop and auto-start, record the
setup without committing credentials, and confirm connectivity — then finalise
the graph schema against the audit results above.

First command for Gate 1:

```bash
cp .env.example .env   # then fill the TG_* values locally
python scripts/bootstrap.py
```

## Verification commands

```bash
python scripts/bootstrap.py           # environment and dataset presence
python scripts/prove_card_mapping.py  # card identifier proof, exit 0
python scripts/run_data_audit.py      # full data audit, exit 0
python scripts/validate_all_cases.py  # submission gate; exit 1 until cases exist
python -m pytest tests/ -q            # 119 passed
python -m ruff check .                # All checks passed
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
- `pytest tests/ -q` reports 119 passed, including 32 invalid answer fixtures
  each rejected for its intended rule.
- `scripts/validate_all_cases.py` exits 1 against the empty `cases/` directory
  and names all twenty missing cases, which is the correct state before the
  agent exists.

## Time spent

Block A (core setup, budget 2–3 hours): Gate 0 completed within budget.
