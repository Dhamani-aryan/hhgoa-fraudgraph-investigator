# Project Progress

## Current gate

**Gate 1 — TigerGraph graph and vector foundation: complete, awaiting review.**

Gate 2 (GSQL, graph algorithms, MCP, GraphRAG evidence) has not been started.

## Gate 1 checklist

- [x] Configure Savanna and document setup without committing credentials.
- [x] Finalize the graph schema only after Gate 0 audit results.
- [x] Prepare normalized, idempotent vertex/edge loading files and versioned
      loading jobs.
- [x] Load transactions, identities, customers/cards, shared entities, closed
      cases, and case-memory text.
- [x] Create the TigerGraph vector index/attributes for closed-case and
      policy/typology retrieval.
- [x] Reconcile expected versus loaded counts and run sampled path/vector
      searches.

**Gate 1 exit:** met. One card traverses to its transactions, cardholder,
device, region and history; one semantic query returns relevant prior cases and
policy chunks from TigerGraph vector search; rerunning the loader does not
duplicate data.

### What is live

Workspace runs TigerGraph 4.2.5, which matters because vector attributes
require 4.2+.

Loaded and reconciled against the Gate 0 audit, every figure exact:

| Vertex | Count | Edge | Count |
|---|---:|---|---:|
| Cardholder | 13,553 | OWNS | 14,317 |
| PaymentCard | 14,317 | MADE | 590,742 |
| Transaction | 590,742 | NEXT | 576,425 |
| DeviceProfile | 9,706 | BILLED_IN | 525,003 |
| EmailDomain | 60 | PURCHASER_EMAIL | 496,262 |
| BillingRegion | 332 | RECIPIENT_EMAIL | 137,453 |
| ClosedCase | 5,565 | FROM_DEVICE | 120,833 |
| PolicyChunk | 27 | CASE_INVOLVES | 14,955 |

2,481,647 edges in total. Vector attributes hold 5,565 closed-case embeddings
and 27 policy embeddings at 1536 dimensions, COSINE, HNSW.

### Two names had to change

The workspace ships with a starter kit owning global `Customer` and `Card`
vertex types, and TigerGraph refuses both a global and a graph-local type with
those names. Rather than drop objects belonging to the workspace, the two
colliding types are renamed `Cardholder` and `PaymentCard`. The rename is
presentational: `customer_id` and `card_id` keep the dataset's own values, so
nothing in an answer file changes. Dropping the starter-kit globals would free
the original names if that is ever preferred.

### TigerGraph behaviours that fail silently

Each of these looked like success and is now recorded in the code that hit it:

1. `CREATE VERTEX` is always global, so `DROP GRAPH` leaves the types behind
   and the next run clashes with itself.
2. A multi-statement GSQL file submitted in one call is accepted and does
   nothing: no error, no types.
3. `gsql` returns a transcript with a success status even when a statement
   inside it failed.
4. `getVertexTypes()` returns an empty list for a graph whose types
   demonstrably exist.
5. A vector attribute cannot appear in `CREATE VERTEX`; the schema-change job's
   definition and its `RUN` are two statements, and the job outlives the graph.
6. `LS` does not print vector attributes at all; only `getSchema()` shows them.
7. `HEADER="true"` does not stop a vertex being created whose primary id is the
   column name, which inflated every count by exactly one.
8. The `graphname` argument does not carry the graph context into a multi-line
   statement.
9. A load result's counts live at `statistics.parsingStatistics.objectLevel`,
   not at `statistics`.
10. `getVertexCount()` without `realtime=True` lags a load badly enough to
    report a half-loaded graph as finished.
11. `vectorSearch` is rejected inside an `INTERPRET QUERY`, so the vector path
    must be an installed query.
12. `TO VECTOR ATTRIBUTE` in a loading job installs but fails at run time
    through the REST file endpoint on any file size; embeddings go through the
    REST upsert path instead.

### Gate 1 review corrections

Four findings from the Gate 1 review, fixed before any Gate 2 work.

1. **`--recreate` could have dropped a populated graph.** `total_vertices()`
   swallowed count failures and summed them as zero, so an unreadable count
   read as an empty graph. The live workspace had already produced a 60-second
   count timeout. A failed or non-numeric count now raises and recreation
   refuses: not knowing whether the graph is empty is not the same as knowing
   that it is. Verified by refusing on the loaded graph at 634,302 vertices.
2. **Savanna cold starts failed the run.** `connect()` attempted once. It now
   retries with bounded backoff, up to 8 attempts from 5 to 60 seconds, but
   only for failures that look transient. A wrong secret still fails on the
   first attempt, so a batch run cannot hang behind a real configuration error.
3. **Traversal verification did not require what the gate requires.** Devices
   and prior cases were recorded but not asserted, so a graph with no
   `FROM_DEVICE` or `CASE_ON_CARD` edges would have passed. Both are now
   required.
4. **The installer could report success on an incomplete schema.** It checked
   vertices only. It now validates all 16 forward edges, all 16 reverse edges
   (the traversal walks `OWNED_BY` and `CARD_HAS_CASE`, so a missing reverse
   edge breaks the gate while every forward edge looks present) and all three
   vector attributes, on both the install path and the no-op path.
   `runs/schema_install.json` records `missing_edge_types` and
   `missing_reverse_edge_types`. Commit `8937e40` carries this change alongside
   finding 1; its message describes only finding 1.

5. **Recreation could still bypass the guard through the catalog.** Discovery
   made two independent `LS` reads: the first established that the graph
   exists, the second failed into empty sets, and `total_vertices()` over an
   empty type set returned zero, permitting the drop. The vertex-count guard
   never fired, because with no types there is nothing to count. Discovery now
   reads the catalog once and refuses on either a failed read or an unparseable
   membership line — "present but unreadable" is never represented as "present
   and empty". Catalog errors are redacted. A genuinely empty graph, parsed as
   `Graph HHGOAFraud()`, is still droppable, and a test pins that so the fix
   cannot degrade into refusing to recreate at all.

### Retrieval quality, measured

The query "three small online authorizations within an hour followed by a
larger purchase from a device new to the account" returns CC-1242 and CC-0370
(confirmed `card_testing`), CC-0609 and CC-3112 (`card_not_present_new_device`)
and CC-3107 (`cleared`) — contrastive rather than all-fraud, which is what the
plan asks for. Policy search returns `pattern:card_testing`,
`pattern:card_not_present_fraud` and `policy:R5`, the card-testing rule.

A unit test caught a real retrieval failure: "the customer denied the
transaction" ranked policy R3 (customer confirms) above R2 (customer denies),
the opposite rule, because "denied" and "denies" hashed to different buckets.
Light stemming fixed it and the test now guards it.

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

None.

**Auto Resume is enabled and Auto Suspend is set to 60 minutes**, confirmed in
the Savanna console by the primary engineer. The brief requires both.

Auto Suspend is why `graph/client.py` retries: the first call after an idle
period lands on Savanna's "Starting workspace" page rather than the database,
and a single attempt turns a routine cold start into a failed run. A live
verification failed exactly that way before the retry was added.

## Next action

Await Gate 1 review. On approval, begin Gate 2: the remaining bounded GSQL
query family with `as_of_ts`, time-bounded WCC as a TigerGraph graph algorithm,
TigerGraph MCP with a restricted tool surface, and the GraphRAG context builder.

## Reproducing the graph from scratch

```bash
.venv/Scripts/python scripts/install_schema.py --recreate
```

```bash
.venv/Scripts/python scripts/prepare_graph_files.py
```

```bash
.venv/Scripts/python scripts/load_graph.py
```

```bash
.venv/Scripts/python scripts/install_queries.py
```

```bash
.venv/Scripts/python scripts/verify_graph.py --reload-check
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
