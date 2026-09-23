# Project Progress

## Current gate

**Gate 2 — GSQL, graph algorithms, MCP and GraphRAG evidence: in progress.**

Gate 1 is complete and its six review findings are fixed.

### Gate 2 checklist

- [x] Gate 2A query corrections: effective cutoff, region admissibility, and
      bounding that actually bounds.
- [x] All nine required bounded GSQL queries, plus three supporting ones —
      twelve installed and verified from the catalog:
      `get_case_context_v1`, `get_card_baseline_v1`,
      `get_transaction_window_v1`, `find_shared_origin_activity_v1`,
      `find_region_anomalies_v1`, `find_similar_closed_cases_v1`,
      `extract_temporal_graph_features_v1`, `calculate_case_exposure_v1`,
      `write_investigation_case_v1`, plus `read_investigation_case_v1`,
      `find_policy_chunks_v1` and `wcc_shared_origin_v1`.
- [x] Time-bounded WCC as a graph algorithm (`wcc_shared_origin_v1`).
- [x] Path and algorithm provenance: every WCC member carries the devices that
      joined it and the hop it was reached at, and the query returns exact
      predecessor-device-member path segments, capped lowest hops first.
- [x] Case write-back with an independent read-back receipt; `ok` requires the
      read-back to match, and every cited prior case must carry a real
      similarity and reason. Idempotent on rerun.
- [ ] TigerGraph MCP with a restricted tool surface, and a served-tool inventory
- [ ] `GraphToolPort`: MCP primary, normalized direct-query fallback
- [ ] GraphRAG evidence-package builder and citation tests
- [ ] Gate 2 exit: a fixture case producing an evidence package through MCP

### Gate 2B findings

6. **The query installer reported a failed install as success.** Its check
   accepted any transcript containing "install", and TigerGraph's failure
   message is "Query installation failed!".
   `write_investigation_case_v1` sat in DRAFT with a semantic error, was
   reported installed, and returned 404 at runtime because a draft query has no
   REST endpoint. Installation status is now read from the catalog, which
   states it outright. An audit of the whole bundle found only that one query
   affected.
7. **The WCC component cap did not cap.** It is tested after each hop, so a
   single hop overshot it — 668 cards against a stop value of 200. Renamed
   `stop_expanding_above` and documented as a stop condition; the real per-hop
   bound is the device threshold.
8. **Case write edges are additive.** Re-writing with fewer identifiers leaves
   the earlier edges, because an upsert cannot know what was withdrawn.
   Documented and pinned by a test rather than described as full idempotence.
9. **WCC eligibility counted transactions, not distinct cards.** The parameter
   is `max_device_cards` but the accumulator incremented per transaction, so
   one card making fifty purchases on its own laptop looked like fifty cards
   and was excluded as a supernode. It now accumulates a set of card ids.
10. **WCC costed every device in the graph.** Eligibility scanned all 9,706
    DeviceProfiles and their full history on every call. It is now evaluated
    per hop for the devices the frontier actually reaches, and cached: 87
    devices considered instead of 9,706, in 0.59s. Members also record the
    predecessor cards they were reached from, so a multi-hop path is
    reconstructible rather than merely asserted.
11. **`INV_SIMILAR_TO` stored 0.0 and an empty string.** The edge exists to say
    why a case was cited, and placeholders made it unable to answer that.
    Real similarity and reasons are stored and read back, applied by
    `graph/case_writer.py` because GSQL rejects a MAP accessor inside `ACCUM`.
12. **Unmatched device, policy and on-card identifiers were dropped silently.**
    All five collections plus the on-card id are now reported, and a partial
    write is a failure rather than a receipt: `WriteReceipt.ok` is true only
    when the graph holds everything the answer claims.
13. **The feature vector was incomplete with no note saying so.** Email and
    region degrees, cleared-neighbour recency and burst count were added, and
    the features that deliberately live in other queries are now named rather
    than left ambiguous.

### Gate 2C corrections

14. **The write receipt never read the case back.** `graph/case_writer.py`
    trusted the write query's own report of what it matched, so a stale edge
    left by an earlier write, a changed attribute or a lost similarity could
    not be seen. `write_case` now calls `read_investigation_case_v1`
    independently after the write and compares all 24 payload attributes
    (floats by tolerance, datetimes by value), requested versus stored ids for
    all five relationship sets plus the on-card edge in both directions, every
    read-back edge count, and each cited case's similarity and reasons. The
    receipt carries `read_back_verified` and the named mismatches, and
    `WriteReceipt.ok` now requires `complete`, no errors and
    `read_back_verified`. `written_to_graph` and `graph_case_id` are exposed on
    the receipt and are true/non-empty only when `ok`. Measured live: rewriting
    the fixture with one transaction instead of three reports
    `complete=True` from the write query and fails the read-back with
    "stored but not requested", which the write query alone cannot detect.
15. **A cited prior case could be stored with placeholder provenance.** A
    caller that omitted a similarity or reason got an `INV_SIMILAR_TO` edge at
    `0.0` / `""` and a successful receipt. Every cited case now needs a finite
    similarity above 0 and a non-empty reason; a citation missing either, or
    provenance supplied for a case that is not cited, is refused before the
    graph is touched (`write_attempted=False`, receipt `REFUSED`), so no
    placeholder edge is ever created. Independently, the read-back fails any
    stored citation whose similarity is not above 0 or whose reason is empty.
    Live tests cover the refusal (nothing found on read-back afterwards), a
    placeholder edge created by the raw write query failing the read-back, and
    the fully attributed case verifying.
16. **`extract_temporal_graph_features_v1` budgeted only the device.** The
    region and purchaser-email sections had no precheck: on HHG-017 at the
    default `max_scan_rows=20000` they traversed 31,813 and 28,793
    transactions. Both are now gated by the same O(1) lifetime-volume precheck
    as the device and are skipped whole when over budget, returning
    `<entity>_precheck_lifetime_transactions`, `<entity>_scan_skipped`,
    `<entity>_rows_scanned` (0 when skipped) and a withheld reason, and none
    of that section's degrees. Measured on the installed query for HHG-017:
    region 204.0 has a lifetime volume of 42,035 and anonymous.com 57,572, so
    at the default budget both are skipped with 0 rows scanned; at 50,000 the
    region is admitted (31,813 rows) and the email still skipped; at 100,000
    both are admitted. Every run returned in 0.32–0.36s. The email lifetime
    figure sums purchaser and recipient rows, so it is a conservative bound on
    the purchaser scan. Lifetime figures are resource controls only:
    `graph.result_normalizers.evidence_values` drops every field ending
    `precheck_lifetime_transactions`, which all four lifetime prints in the
    query bundle do. The card's own history remains ungated by
    `max_scan_rows`; it is bounded by the data (largest card 14,891 rows).
17. **The feature-vector contract overstated what the query returns.** Its
    header said nothing in the plan's list was missing. Reassessed: the query
    returns the device/region/email degrees, in-window reach, device neighbour
    outcomes and recency, burst count and novelty flags. It does **not**
    return amount MAD or percentiles (`get_card_baseline_v1` amounts, computed
    in Python), WCC size, two-hop reachability or paths
    (`wcc_shared_origin_v1`), home-region overlap
    (`find_region_anomalies_v1`), a rarity score (decided in
    `find_shared_origin_activity_v1`) or any fraud-enrichment ratio (not
    computed anywhere yet), and withholds region/email degrees for an entity
    over budget. Those are to be composed by the GraphRAG / feature assembler,
    which is not built yet; until then no standalone output of this query is
    the plan's full vector.
18. **WCC provenance lost which predecessor used which device.** Separate
    `via_from_cards` and `via_devices` sets cannot say, for a member reached
    from A and B over d1 and d2, whether A shared d1 or d2. The query now also
    returns `path_segments`, each an exact `(from_card, device_id, to_card,
    hop)` edge of the bounded expansion, deduplicated and capped by
    `max_path_segments` (default 500) in hop-first order, with
    `path_segment_count`, `path_segments_returned` and
    `path_segments_truncated`. Hop-first ordering means a returned segment
    always comes with all lower-hop segments, so a truncated output still
    reconstructs every path it contains. Measured on the installed query for
    seed C12897-K1 with 3 hops, a device threshold of 2 and a 336h window:
    87 cards, 97 segments over 97 devices, members to hop 3, 5 members reached
    by more than one predecessor. A live test validates all 97 segments against
    the graph independently of the WCC query — both cards must hold a
    transaction on that device inside the window and at or before the cutoff,
    read through `get_transaction_window_v1` and the device's `DEVICE_USED_IN`
    edges — then rebuilds a complete path to the seed for every member. A
    fabricated segment (real cards, another member's device) fails that check.
    Segments are identical at three later review cutoffs.

### Gate 2D query-surface exit audit

An audit of all eleven read queries against the plan's Phase 3 exit
conditions found these gaps, now closed and verified on the installed queries
(`tests/integration/test_query_surface_exit.py`, 37 live tests):

19. **Unknown entities returned silent empties.** `get_card_baseline_v1` and
    `get_transaction_window_v1` for an unknown card, `wcc_shared_origin_v1` for
    an unknown seed and `find_shared_origin_activity_v1` for an unknown entity
    id or kind all returned zero-valued results that read as findings ("no
    history", "isolated", "rare"). Each now prints `refused` and a
    `refusal_reason`. `find_region_anomalies_v1` reported a missing
    transaction as a card mismatch; it now has `refused_flagged_not_found`.
20. **Row caps were silent.** `get_transaction_window_v1` now reports the exact
    `transactions_in_window` and `window_truncated`;
    `find_shared_origin_activity_v1` reports `shared_transactions_returned` and
    `shared_transactions_truncated`.
21. **Shared-origin fraud enrichment was computed from the capped sample.**
    Cards were taken from the `LIMIT`ed transaction set, so the cap could
    understate enrichment. It now covers every in-window card; with the sample
    capped at 1 row the enriched-card count is unchanged.
22. **Vector retrieval exposed no score and was not contrastive.**
    `find_similar_closed_cases_v1` now builds the structural candidate pools in
    GSQL (causal admissibility, self-exclusion, confirmed-fraud and cleared
    pools searched separately, an optional exposure band that relaxes with a
    flag, and a shared-origin pool of cases on related cards), searches each
    with `vectorSearch(..., {candidate_set, distance_map})`, and returns
    TigerGraph's `vector_cosine_distance` per case. Measured: the distance
    equals 1 − cosine of the stored embeddings to within 1e-4 (six decimals in
    the probe). `k` is per pool and capped at 20. `find_policy_chunks_v1`
    returns the same distance and caps `k` at 10. `related_card_ids` must
    always be passed; an omitted `SET` parameter is NULL at runtime
    (GSQL-1001).
23. **Query vectors over GET.** The MCP `run_installed_query` tool sends
    parameters as a GET query string. A full-precision 1536-float vector
    returned HTTP 414; rounded to six decimals it succeeds. The tool port
    rounds every query vector to six decimals on both paths.

Retrieval is over `ClosedCase` only. `InvestigationCase` vertices, which hold
the active benchmark memory epoch, are a separate vertex type that no retrieval
query reads, and a live test asserts every returned id is a `CC-` case closed
by the cutoff.

### Gate 2E TigerGraph MCP and GraphToolPort

- `graph/mcp_client.py` starts the official server (`tigergraph-mcp` 1.0.3,
  MCP SDK 2.2.0) over stdio with one session held for the run:
  `tigergraph-mcp --allowed-tools <six tools> --log-tool-calls`, credentials
  passed only in the subprocess environment, caller identity not logged.
- Served surface, verified live: `list_graphs`, `get_graph_schema`,
  `is_query_installed`, `run_installed_query`, `list_vector_attributes`,
  `get_vector_index_status`. Startup fails closed if the server serves any
  other tool, or any tool whose name marks it as mutating or free-form; a live
  test starts a server with `gsql` added and asserts it refuses.
  `search_top_k_similarity` is excluded because it creates, installs and drops
  a temporary query on every call and applies no cutoff.
- `run_installed_query` is the one tool the server marks non-read-only. The
  read-query allowlist (eleven installed read queries) is enforced in
  `graph/tool_port.py` before any call is sent; `write_investigation_case_v1`
  is refused by name.
- `GraphToolPort`: `MCPGraphToolPort` (primary), `DirectGraphToolPort`
  (fallback, same queries by GET), `FallbackGraphToolPort`. Every call is
  validated (required, unknown and over-cap parameters, timestamp format,
  1536-float finite vectors rounded to six decimals), consumes a shared
  12-call budget including failures and fallback retries, runs under a
  timeout, and leaves a sanitized record (trace id, tool, redacted parameters,
  vector as dimension + SHA-256, duration, outcome, result size). Only
  transport, timeout and availability failures fall back.
- Live: MCP session start 1.9–3.1s; six fixture queries return canonically
  identical results through MCP and direct; a 1 ms timeout is classified
  unavailable and the session keeps serving. 50 unit tests with fake
  transports, 17 live MCP tests.

### Gate 2F complete feature vector

`evidence/collector.py` runs a case's nine structural queries through any
GraphToolPort in a fixed order; `evidence/feature_assembler.py` composes them
into one vector of 68 named features, each with a state (`available`,
`withheld`, `refused`, `not_applicable`, `unavailable`), its source query and a
reason. Withheld, refused and missing values are `None`, never 0 or False.
Robust amount statistics (`scoring/robust_baselines.py`): median, MAD,
0.6745-scaled robust deviation, mid-rank empirical percentile, with a zero MAD
reported as `zero_mad` and no deviation. Two-hop reach is derived only from
returned WCC segments. The candidate episode (flagged transaction plus
same-card, same-channel transactions in the 48 h before it) is costed by
`calculate_case_exposure_v1` and checked against the local sum of the window
rows. Every source timestamp is checked against the anchor.

Fixture choice, measured: of the twenty benchmark triggers, HHG-017's WCC
component is isolated (its device reaches 70 cards in the window, above the
5-card threshold) and its device is refused as a supernode (164 cards to the
cutoff). HHG-019 joins a six-card component through device 617deda1f7ea4b99,
with every other member carrying confirmed fraud and five path segments, so
HHG-019 is the Gate 2 exit fixture and HHG-017 the withheld/isolated fixture.
Live through MCP: HHG-019 costs nine structural calls, passes the leakage
check with `data_max_time` equal to the anchor, and a review at 2016-12-31
returns identical features. HHG-017's episode is 3450436, 3450503, 3450629 for
$300.14, agreeing with the local sum. 29 unit and 11 live tests.

### Gate 2G hybrid prior-case and policy retrieval

- `retrieval/case_retriever.py`: stage 1 in GSQL (causal, self-excluding,
  ClosedCase-only pools split by outcome, an exposure band of a factor of four
  around the candidate episode, and a shared-origin pool of cases on the card,
  its WCC component and its shared-device fraud cards), TigerGraph
  `vectorSearch` over each pool, then a deterministic Python rerank. The
  composite retrieval score is a named weighted sum (vector cosine similarity
  0.30, pattern compatibility 0.25, shared origin 0.20, episode-size
  similarity 0.15, recency 0.10) and is never presented as a cosine; TigerGraph's
  own cosine distance and pool rank are carried beside it. At most two
  confirmed-fraud, two cleared and two boundary cases, each with a reason
  vector. A defensive filter rejects and names any non-`CC-`, self or
  post-anchor row. A vector failure falls back to local lexical cosine only
  when local memory is supplied, marked `local_fallback_not_tigergraph`.
- `retrieval/policy_retriever.py`: TigerGraph vector search over PolicyChunk
  (k=10), then deterministic selection of at most four chunks that an observed
  signal makes relevant, one per signal first. Relevant anchors the search did
  not return are reported, never injected.
- Live, HHG-019: six cases through MCP (CC-5111, CC-3466 fraud; CC-4973,
  CC-3107 cleared; CC-2172, CC-0510 boundary), shared-origin pool of 88 cases,
  identical at a later review; policy R6, `pattern:card_not_present_new_device`,
  R1 and `pattern:shared-origin-caution`. A card-testing signal set retrieves
  R5 and `pattern:card_testing` live. HHG-017 retrieves no shared-origin rule.
  A full HHG-019 investigation costs 11 of the 12 calls. 21 unit and 12 live
  tests.
- A card-testing sequence is a feature of its own:
  `small_online_authorizations_1h_before` (online, under $5, in the hour before
  the flagged transaction), not the lifetime burst count.

### Gate 2 leakage findings, fixed

Four review findings, all the same class — a query that looks bounded while
handing the investigator information from after the alert:

1. `get_case_context_v1` returned stored aggregates computed over the whole
   dataset, so a 2016-11-11 case reported `last_seen` 2016-12-25 and 59
   transactions against the 53 that existed. Counts are now recomputed by
   traversal to the cutoff, and the query refuses a flagged transaction that
   postdates `as_of_ts`.
2. `calculate_case_exposure_v1` had no cutoff, so a future transaction could
   inflate exposure past the $1,000 report threshold or the $2,500
   `BLOCK_CARD` boundary. `as_of_ts` is now required and later identifiers are
   excluded and reported.
3. `find_region_anomalies_v1` bounded history by `as_of_ts` instead of the
   flagged transaction's own timestamp, so a later review grew the history from
   52 entries to 58 and could make a region look familiar on visits made after
   the alert.
4. `find_shared_origin_activity_v1` used the stored lifetime `n_cards` as its
   rarity measure. Rarity is now counted to the cutoff, the scan is bounded,
   and a truncated scan refuses rather than guessing permissively. The default
   supernode threshold drops from 250 to 100, since the audit put the 99th
   percentile of cards-per-device at 137.

The stored `n_cards`, `n_transactions`, `first_seen` and `last_seen` attributes
remain in the schema as dataset-level descriptions, but no query may return or
decide on them at runtime.

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

6. **Blank and error catalog responses still read as "graph absent".**
   `read_catalog()` rejected exceptions but accepted an empty string or a
   textual GSQL failure, and gsql reports many failures as ordinary text with a
   success status. Discovery then returned `present=False` and `--recreate`
   reached the global `DROP EDGE` / `DROP VERTEX` loop, which is gated on the
   flag rather than on the graph being present. The earlier test missed it
   because it spied on `run_gsql` while that loop calls `gsql()` directly.
   `read_catalog()` now requires a positive catalog marker and refuses blank,
   error-text and unrecognised responses; the global drop loop counts the
   leftover types first, since a global type outlives the graph and keeps its
   data. The test now records every statement at the connection and asserts no
   `DROP`, `CREATE`, `ALTER` or `RUN` after any discovery failure — verified to
   fail without the fix.

### Gate 2A query corrections

Three further review findings, fixed and verified against the installed
queries:

1. **Shared-origin evidence tracked `as_of_ts` rather than the anchor.** A case
   reviewed later surfaced transactions, connected cards and confirmed-fraud
   outcomes that did not exist when the alert fired. Everything is now bounded
   by `effective_cutoff = min(anchor_ts, as_of_ts)`, applied identically to the
   rarity count, the shared transactions and the fraud enrichment. Three review
   cutoffs now return identical evidence: 26 cards, 29 transactions, 10
   fraud-enriched cards.
2. **Region analysis answered inadmissible requests.** It now refuses a flagged
   transaction that postdates `as_of_ts`, and refuses a flagged transaction
   that does not belong to the supplied card. Refusing withholds every data
   key, not just the verdict.
3. **The advertised scan budgets bounded nothing.** GSQL runs `ACCUM` over
   every matched vertex and applies `LIMIT` only to the returned set. Measured:
   with the budget set to 5, the gmail.com scan still walked 45,521 rows. Work
   is now bounded before any traversal by an O(1) precheck against the stored
   lifetime transaction count, and gmail.com scans zero rows.

The precheck reads a lifetime aggregate, which is permitted only as a resource
gate. It is reported as `precheck_lifetime_transactions`, decides solely
whether a scan is affordable, and is never case evidence; the rarity driving
the supernode decision is a separate count bounded by the effective cutoff.

### Gate 2A follow-up corrections

Two adjacent issues in queries the first pass did not revisit:

4. **`get_case_context_v1` bounded five traversals by `as_of_ts`.** A later
   review widened the card history, cardholder history, device history,
   adjacent transactions and prior closed cases. All five now use
   `effective_cutoff = min(flagged transaction ts, as_of_ts)`, so evidence is a
   property of the case rather than of when someone looked. Three review
   cutoffs now return identical evidence.
5. **`get_card_baseline_v1` had the same false `LIMIT` cap.** Asking for 5
   amounts returned all 53. It is now gated by a pre-traversal precheck, and it
   skips rather than truncating: a partial amount list would give a median and
   MAD for a half-read card, which is worse than no baseline because nothing
   downstream would know to distrust it. The bound is measured — the largest
   card in this dataset holds 14,891 transactions against a 20,000 default, and
   a test asserts that maximum from the prepared files so the documented
   contract cannot drift from the data.

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

Await review of the Gate 2C correction batch (findings 14–18). On approval,
continue Gate 2 with TigerGraph MCP on a restricted tool surface, then
`GraphToolPort`, then the GraphRAG evidence package and its end-to-end exit
fixture. None of those has been started.

Suite at the end of the batch: 390 passed against live TigerGraph, Ruff and
compileall clean.

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
