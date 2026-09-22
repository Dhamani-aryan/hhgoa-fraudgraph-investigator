# The answer contract

**Source:** the Answer Format section of the supplied dataset `README.md`.
That file is authority #1. This document records the contract locally and maps
each requirement to the code that enforces it, so no requirement is held only
in prose.

One JSON file per case at `cases/<case_id>.json`, twenty files, named for the
twenty `case_id` values in `case_pack.csv`. Missing fields score zero for that
part.

## Where each rule lives

| Layer | File | What it enforces |
|---|---|---|
| Vocabularies | `domain/enums.py` | the fourteen actions, three routes, seven patterns, four statuses, three verdicts, four evidence sources, three request types, and the action-to-route mapping |
| Shape and self-consistency | `domain/answer_models.py` | field names, types, ranges, sentence counts, and the agreements an answer can check about itself |
| Dataset agreement | `validation/cross_field_rules.py` (dataset rules) | identifier existence, exposure recomputation, route recomputation, prior-case temporal admissibility |
| Trace agreement | `validation/cross_field_rules.py` (run rules) | retrieval provenance, graph read-back, ledger references, cutoff, independence, shared-origin bar, R10, memory epoch |
| Batch gate | `scripts/validate_all_cases.py` | exactly twenty files, filenames matching case IDs, machine and human reports, non-zero exit on any failure |

## Top level

| Field | Type | Notes |
|---|---|---|
| `case_id` | string | from `case_pack.csv` |
| `case` | object | part 1 |
| `evidence_requests` | list | `type`, `asked_after_step`, `assumed_response`; empty if nothing was asked |
| `next_best_actions` | object | part 3 |
| `sar` | object | part 2 |
| `stop_reason` | string | why the investigation ended here |
| `tool_calls` | int | graph and retrieval calls for this case |
| `tokens` | int | LLM tokens for this case |
| `latency_s` | number | wall-clock seconds for this case |

## Part 1: `case`

`status` (`open` / `closed_fraud` / `closed_legitimate` / `escalated`),
`verdict` (`fraud` / `legitimate` / `uncertain`), `fraud_probability` (0–1),
`pattern`, `pattern_description`, `affected_txn_ids`,
`first_suspicious_txn_id`, `connected_card_ids`, `connected_device_profiles`,
`exposure_usd`, `evidence`, `similar_prior_cases`, `summary`,
`written_to_graph`, `graph_case_id`.

Each evidence object: `claim`, `source` (`graph` / `document` / `customer` /
`external`), `ref`, `entity_ids`.

## Part 2: `sar`

`file`, `reason`, `narrative`, `subjects`, `total_amount_usd`,
`activity_dates`.

When `file` is false: `narrative` is `""`, `subjects` is `[]`,
`total_amount_usd` is 0, `activity_dates` is `[]`.

## Part 3: `next_best_actions`

`initial` (before any requested evidence came back), `final` (after the assumed
responses), `what_changed`. Each action object: `action`, `route`, `reason`
citing the policy rule. If nothing was requested, `final` equals `initial` and
`what_changed` is exactly `"nothing"`.

## The constraints the README states in prose

These are the ones easy to lose; each is a test.

1. IDs must be the ones in the dataset. Made-up IDs score zero. — rule R02
2. A `legitimate` verdict has empty `affected_txn_ids`, `exposure_usd` of 0,
   and `sar.file` false. — rule R04 and the `CaseRecord` model
3. `pattern_description` is required for `undocumented` and empty otherwise.
   — rule R05-06
4. `sar.file` must agree with whether `FILE_REPORT` appears in the final
   actions. — rule R11-12
5. `summary` is two to six sentences; a filed narrative is six to twelve.
   — rules R18 and R19
6. `uncertain` is a valid verdict and earns full credit on ambiguous cases,
   provided the actions follow R1 and R8.
7. `fraud_probability` reflects what the investigation found and may be far
   from the supplied `risk_score`.
8. Customer and analyst replies are simulated; the assumption is stated in
   `evidence_requests` and `final` reflects it.

## Worked example

The README carries a complete worked example for `HHG-017`. Its identifiers are
illustrative (`T0412877`, `C00377-K1`) and do **not** appear in the supplied
data; the real `case_pack.csv` uses numeric transaction IDs such as `3450629`.
The example is a shape reference only.

`tests/fixtures/valid_answer.json` is the local contract fixture. It uses real
identifiers so it can exercise the dataset rules, and its conclusions are
illustrative rather than an investigation result. See
`tests/fixtures/README.md`.
