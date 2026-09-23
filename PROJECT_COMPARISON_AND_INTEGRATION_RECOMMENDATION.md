# FraudGraph Investigator: Repository Comparison and Integration Recommendation

**Assessment date:** 23 September 2026  
**Prepared for:** Aryan and Naman  
**Purpose:** Select the strongest technical path to a submission-quality TigerGraph fraud-investigation agent without favoring either author or repository.

## Repositories and exact snapshots reviewed

| Project | Repository / branch | Snapshot |
|---|---|---|
| Aryan's implementation | [`Dhamani-aryan/hhgoa-fraudgraph-investigator`](https://github.com/Dhamani-aryan/hhgoa-fraudgraph-investigator), `main` | `69e217d` |
| Naman's specification | [`Namans12/tigergraph`](https://github.com/Namans12/tigergraph), `master` | `17cdd35` |
| Naman's implementation | [`Namans12/tigergraph`](https://github.com/Namans12/tigergraph/tree/tigergraph-fraud-agent), `tigergraph-fraud-agent` | `e81cbf9` |

This assessment is based on checked-out source code, tests, repository history, and the projects' own progress documents. Claims in either progress ledger were treated as supporting context, not as substitutes for code or tests.

## Executive conclusion

Neither implementation should replace the other wholesale.

The strongest and lowest-risk path is:

> **Use Aryan's repository as the canonical integration base, then adapt Naman's agent orchestration, deterministic policy logic, evidence-request loop, and SAR-generation work onto Aryan's graph/evidence/validation interfaces.**

As a responsibility-weighted approximation, the recommended final system is:

- **70% Aryan's current platform:** ingestion, identifiers, TigerGraph schema, installed queries, temporal controls, restricted MCP boundary, evidence packages, retrieval, answer contract, validation, and verified case persistence.
- **30% Naman's current agent layer:** LangGraph workflow, structured LLM interaction, evidence-request/reassessment loop, policy-engine starting point, and SAR-writer starting point.

The percentage is not a statement about ownership, effort, or code authorship. It describes which implementation should supply each technical responsibility. A literal line-by-line merge would be counterproductive because the repositories implement overlapping schemas, loaders, graph clients, queries, and answer models in incompatible ways.

## Current project state

### Aryan's repository

Completed and demonstrated:

- Gate 0: input audit, identifier proof, and executable answer contract.
- Gate 1: TigerGraph schema, idempotent loading, graph verification, and vector foundation.
- Gate 2 implementation and exit fixture: bounded GSQL query surface, temporal leakage controls, graph algorithms, restricted TigerGraph MCP, 68-feature assembly, hybrid prior-case retrieval, policy retrieval, cited evidence packages, and evidence-ledger validation. The project ledger still marks the formal Gate 2 review as pending.
- A live Gate 2 fixture for `HHG-019` runs through MCP without using the direct-client fallback.
- Graph case writes have an independent read-back receipt instead of trusting a write response.
- The current suite completed with **623 passing tests**, including live TigerGraph integration tests. Ruff and `git diff --check` also passed.

Not yet completed:

- Gate 3 deterministic pattern detection, probability/confidence scoring, and final policy decisions.
- Gate 4 one complete submission-quality investigation.
- Gate 5 generation and validation of all 20 answer files.
- Dashboard/demo and final release packaging.

Therefore, this project has a strong verified investigation substrate but is not yet an end-to-end submission.

### Naman's repository

Completed or substantially implemented:

- A persistent TigerGraph MCP client and graph schema/loading implementation.
- Derived graph entities and connected-components support.
- Deterministic graph evidence queries and vector retrieval.
- A LangGraph investigation flow with evidence gathering, optional follow-up tools, assessment, simulated evidence requests, reassessment, and policy evaluation.
- Structured Groq/Ollama LLM wrappers.
- A deterministic policy engine and SAR narrative generator.
- A single-case runner and an end-to-end test centered on `HHG-017`.
- A detailed SDD trail containing task briefs, implementation reports, reviews, re-reviews, and a progress ledger.

Verification observations:

- The branch collects **74 tests**.
- In a clean isolated environment, **51 tests passed** without external services.
- The remaining **23 tests failed because the checkout did not include Naman's private TigerGraph configuration or Groq key**. Those failures are not, by themselves, evidence of faulty code. His progress ledger records previous live execution against his configured services.
- The branch does not contain a production batch runner that writes and validates all 20 official answer files.

Therefore, this project is further ahead on agent behavior and demonstration flow, but its final-answer assembly and operational boundary need strengthening before submission.

## Comparison by judging-critical capability

| Capability | Aryan's implementation | Naman's implementation | Recommended source |
|---|---|---|---|
| Dataset audit and ID integrity | Dataset-backed audit and validation; benchmark IDs are checked | Card-ID mapping is implemented and tested | Aryan |
| TigerGraph schema/loading | Static GSQL assets, idempotence checks, verification artifacts | Python-generated schema and loading jobs, live-tested per ledger | Aryan, with useful lessons from Naman's live setup |
| Query correctness | Installed, bounded queries with regression tests for leakage and query-surface exits | Deterministic queries exist and were iteratively reviewed | Aryan |
| Temporal cutoff/no future evidence | Explicit cutoff propagation and integration tests | Some reference-time handling exists, but coverage is narrower | Aryan |
| Graph algorithms | Time-bounded shared-origin WCC with path provenance | Connected-components implementation and ring membership | Aryan's implementation; compare results against Naman's |
| MCP safety | Server tool surface is restricted; installed-query names and parameters are allowlisted | Client can issue raw GSQL, install queries, and add nodes | Aryan |
| Evidence representation | Typed feature vector, availability states, citations, hash-chained ledger | Evidence is gathered into agent state and prompt summaries | Aryan |
| Prior-case and policy retrieval | Hybrid deterministic/vector retrieval with admissibility checks | Vector retrieval and closed-case lookup are implemented | Aryan |
| Answer validation | Strict models plus cross-field and dataset-backed rules | Basic Pydantic models; fewer semantic constraints | Aryan |
| Case-memory write | Fail-closed write and independent read-back | Broad exception catch returns `written_to_graph = false` | Aryan |
| Agent orchestration | Not yet implemented | LangGraph flow is implemented | Naman, adapted to Aryan's interfaces |
| Evidence-request loop | Contract exists; runtime flow not yet implemented | Request, simulated response, and reassessment are implemented | Naman, then strengthen tests |
| Policy engine | Gate 3 work remains | Deterministic rule engine is implemented | Naman as the starting point; validate against Aryan's contract |
| SAR generation | Contract/knowledge exists; generator not implemented | Structured narrative generator is implemented | Naman as the starting point; ground it in Aryan's evidence IDs |
| All-20 batch runner | Not implemented | Not implemented | Build jointly in canonical repository |
| Dashboard/demo | Not implemented | No production UI found | Build after the frozen 20-case batch |

## Material strengths and risks

### Why Aryan's repository should be the base

1. **It protects the evaluation boundary.** Evidence is time-bounded, provenance-bearing, and checked for leakage. This is harder to retrofit after an agent has already been built around loosely structured evidence.
2. **It treats graph access as a security and reproducibility boundary.** The agent cannot send arbitrary GSQL or install/replace queries during an investigation.
3. **It validates the actual submission contract.** Cross-field rules and dataset-backed ID validation catch plausible-looking but invalid answers.
4. **It verifies persistence.** A successful API response is not considered proof that case memory exists; the record is read back independently.
5. **It now produces a compact, cited evidence package suitable for either deterministic detectors or an LLM.** This creates a clean handoff point for Naman's strongest work.

The principal risk is schedule: the project has deliberately completed the substrate before the agent, so it still lacks the visible end-to-end result.

There is also an operational hardening item: the live TigerGraph test run emits `InsecureRequestWarning` because certificate verification is disabled for the current connection. That does not invalidate the functional test results, but TLS verification should be corrected before treating the client as production-ready.

### Why Naman's agent work should be reused

1. **It already models the investigation as a stateful workflow.** The gather → follow-up → assess → request evidence → reassess → policy sequence matches the problem well.
2. **It has practical LLM integration.** Structured output, bounded tool calling, Groq support, and an Ollama fallback are useful implementation work.
3. **It has deterministic policy logic.** Policy decisions should not be left entirely to a language model.
4. **It has already confronted real TigerGraph and model-provider integration issues.** The review trail contains useful operational knowledge.

The principal risk is answer quality. In the current single-case runner:

- `affected_txn_ids` is reduced to the flagged transaction whenever the verdict is not legitimate.
- `first_suspicious_txn_id` is set to the flagged transaction.
- `connected_card_ids` and `connected_device_profiles` are emitted as empty lists.
- Exposure is derived from the flagged amount rather than the full supported episode.
- SAR dates are derived from the case-opened date rather than the investigated activity range.
- Any graph-write exception is swallowed and converted into `written_to_graph = false`, with no independent read-back.

These are final-answer assembly defects, not a rejection of the underlying agent workflow. They are exactly why the workflow should emit decisions over Aryan's typed evidence package and use Aryan's validator/writer.

## Recommended integration boundary

The evidence package should be the boundary between the two implementations:

```text
Aryan: data + TigerGraph + installed queries + restricted GraphToolPort
    ↓
Aryan: FeatureVector + cited EvidencePackage + retrieved cases/policy
    ↓
Naman-derived: detectors + LangGraph investigation/reassessment workflow
    ↓
Naman-derived: deterministic policy engine + SAR drafting
    ↓
Aryan: strict CaseAnswer + dataset validator + verified graph write/read-back
    ↓
Joint: all-20 batch runner, evaluation report, and dashboard
```

This boundary avoids merging duplicate graph clients, schemas, loading jobs, and query implementations.

## Code to adapt, not copy blindly

From Naman's branch, use these as starting points:

- `src/agent/graph_flow.py`
- `src/agent/llm.py`
- `src/agent/state.py`
- `src/policy/engine.py`
- `src/policy/models.py`
- `src/agent/sar_writer.py`

Required adaptations:

- Replace direct graph/MCP calls with the existing `GraphToolPort` and prebuilt `EvidencePackage`.
- Replace Naman's answer models with the canonical `domain.answer_models.CaseAnswer`.
- Make assessment output include the supported fraud episode, affected transactions, connected entities, exposure, uncertainty, and citations.
- Preserve unavailable/withheld/refused distinctions instead of converting missing evidence to zero or false.
- Make policy actions cite exact rule and evidence IDs.
- Make graph persistence fail closed and require the existing read-back receipt.
- Mock provider calls in unit tests; keep live provider tests as explicit integration tests.

Do not merge these overlapping layers from Naman's branch unless a specific missing behavior is identified:

- `src/tg_client.py`
- `src/schema/*`
- `src/graph/queries.py`
- `src/graph/vector_search.py`
- `src/agent/schemas.py`
- the current `_write_case_to_graph` implementation

## Proposed ownership for the next phase

This is a technical split, not a statement about seniority.

### Aryan

- Keep `main` and the release process stable.
- Finish deterministic feature-to-signal detectors and probability calibration.
- Own the answer contract, graph safety, evidence provenance, persistence, and validation gates.
- Review changes that cross the graph/evidence boundary.

### Naman

- Port the LangGraph workflow onto `EvidencePackage` in a feature branch of the canonical repository.
- Adapt the policy engine and SAR writer to the canonical models and evidence citations.
- Implement bounded evidence-request simulation and reassessment.
- Add provider-independent unit tests and one explicit live-model integration test.

### Joint work

- Make one case genuinely submission-quality before batch execution.
- Review that case by hand against the task's answer format and policy.
- Implement the all-20 frozen-memory runner.
- Inspect fraud/legitimate balance, uncertainty, affected transaction scope, exposure, and action routing across all outputs.
- Freeze, validate, and tag the exact submission commit before dashboard work changes behavior.

## Merge sequence

1. **Freeze the integration contracts:** `EvidencePackage`, `FeatureVector`, `CaseAnswer`, `GraphToolPort`, and case-writer receipt.
2. **Implement deterministic detectors:** card testing, card-not-present, new-device CNP, out-of-region, account takeover, and undocumented-pattern support.
3. **Port the agent flow:** make the LangGraph state consume the evidence package rather than independently querying TigerGraph.
4. **Port and reconcile policy:** test every rule boundary and approval route against the canonical enums and validator.
5. **Port SAR generation:** require evidence IDs, real activity dates, subjects, and exposure from the supported episode.
6. **Perfect one case:** run collection, assessment, evidence request, reassessment, actions, SAR, validation, graph write, and read-back.
7. **Run all 20 cases:** write one answer file per case, validate all files, verify every graph receipt, and produce a batch summary.
8. **Only then build the demonstration UI and release package.**

## Rejected alternatives

### Use 100% of Aryan's repository without Naman's work

Not recommended. It would discard a working orchestration design and repeat policy/SAR integration work while the schedule is limited.

### Use 100% of Naman's repository

Not recommended. It would discard stronger temporal controls, evidence provenance, validation, restricted graph access, and verified persistence, and would leave material final-answer defects to fix under deadline pressure.

### Merge both repositories approximately 50/50 by files

Not recommended. Both repositories independently implement graph clients, schemas, loaders, queries, models, and retrieval. Combining those layers would create two sources of truth and increase integration risk without improving the judged outputs.

## Definition of “ready to submit”

The combined project is ready only when all of the following are true:

- All 20 official case files exist and pass schema, cross-field, and dataset-ID validation.
- Every evidence claim is traceable to a graph result, retrieved document, customer response, or explicit assumption.
- No case uses evidence later than its permitted cutoff.
- Affected transactions, first suspicious transaction, connected entities, and exposure come from the supported episode rather than the trigger alone.
- Initial and final actions follow the deterministic policy and approval routes.
- Any requested evidence visibly changes—or explicitly does not change—the assessment and actions.
- SARs are filed only when policy requires them and contain grounded subjects, amounts, dates, and narrative.
- Every case-memory write has an independent read-back receipt.
- The 20-case run uses a documented memory policy and produces a reproducible batch report.
- The final deliverables correspond to one tagged commit.

## Final recommendation

Proceed with **Aryan's repository as the single canonical repository**, using a **70/30 platform-to-agent composition** as described above. Naman should continue leading the agent workflow, policy, and SAR portions—but inside the canonical repository and against the existing evidence and validation contracts. Aryan should continue leading graph correctness, evidence integrity, validation, and release safety.

This recommendation is based on the complementarity visible in the code: Aryan's project is stronger below the decision boundary; Naman's project is stronger above it. The combined design is materially better than either implementation alone and avoids paying the cost of maintaining two end-to-end stacks.
