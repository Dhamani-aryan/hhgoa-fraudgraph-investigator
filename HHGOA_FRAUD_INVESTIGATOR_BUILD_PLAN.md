# HHGOA TigerGraph Fraud Investigator Build Plan v2

## Document purpose

This file is the complete implementation contract for the Hacker House Goa TigerGraph Agentic Fraud Investigation project. It is written so that a capable coding agent can begin work in this directory without needing the prior conversation, GitHub repositories, or external planning documents.

This revision incorporates a broad review of current TigerGraph tooling, graph-fraud reference implementations, agent workflow patterns, temporal fraud-evaluation research, probability calibration, and explainability. The design choices below are deliberately narrower than the full research space because the submission deadline is close. Every innovation must either improve the judged answer quality, reduce failure risk, or make the investigation visibly more defensible.

The implementation agent must read this entire file before creating code. It must work through the phases in order, preserve the acceptance criteria, and update the progress checklist as work is completed.

## Deadline and delivery priority

- Submission deadline: **24 September 2026 at 11:59 PM IST**.
- One submission is allowed, by the team lead, with no resubmissions.
- Current planning date: **22 September 2026**.
- The project must optimize for a complete, testable submission rather than production-scale infrastructure.
- The two most important judging categories are investigation accuracy and next-best-action quality. Together they account for 50% of the score.
- A working batch runner that generates twenty valid case files is more important than an elaborate interface.
- The interface must demonstrate the investigation clearly, but it must not delay the core pipeline.

## Authority order and challenge compliance

When requirements conflict, use this authority order:

1. The official challenge brief, dataset README, supplied policy, supplied answer schema, and twenty-case instructions.
2. The actual contents and identifiers in the supplied dataset.
3. This implementation plan.
4. External articles, repositories, examples, and framework conventions.

External research may improve implementation but may never override the supplied policy, invent a field, import public IEEE-CIS fraud labels, change the answer format, or replace a required TigerGraph component.

### Required challenge components and proof

| Official requirement | Mandatory implementation | Proof required before submission |
|---|---|---|
| TigerGraph Savanna or Community Edition for graph and vector storage/retrieval | Use TigerGraph Savanna as the authoritative graph **and vector** store. Enable auto-stop and auto-start. Store graph entities, case memory, policy/typology chunks or case embeddings, and retrieve from TigerGraph at runtime. | Configuration screenshot, schema/vector-index artifact, successful load verification, and a demo trace showing graph traversal plus TigerGraph vector retrieval |
| GSQL and TigerGraph graph algorithms | Implement versioned installed GSQL queries and use at least one TigerGraph graph algorithm in an investigation. The minimum algorithm is time-bounded WCC on a suspicious shared-origin subgraph; add cycle detection only if the data supports it. | Versioned GSQL files, integration tests, and one demo case explaining what the algorithm revealed |
| TigerGraph MCP | Connect the investigation workflow to the official TigerGraph MCP server with a restricted tool surface. MCP is the primary agent-facing graph path. | MCP startup/configuration, served-tool inventory, logged successful call, and end-to-end trace |
| GraphRAG | Retrieve connected graph evidence plus relevant case/policy text or vectors, build a compact cited context package, and give that package—not raw bulk data—to the LLM. | Saved context package, retrieval reasons, graph/vector references, and final claims resolving to evidence IDs |
| User interface | Build an analyst-facing interface showing trigger, graph evidence, case progression, uncertainty, initial action, evidence request, final action, approvals, SAR, and case-memory write. | Working Streamlit view and 3–5 minute recorded demonstration |
| Supplied HHGOA IEEE dataset | Read its README first; use the four supplied files, first-four-month closed cases as historical memory, and twenty final-two-month cases as the benchmark. | Dataset audit, manifest hashes/counts, identifier validation, and exactly twenty answer files |
| Required case outputs | Produce the internal case record, evidence/findings/decisions/actions, graph write-back, conditional SAR, and next-best actions/routes both before and after added evidence. | Validator exits zero for all twenty; write/read-back receipts exist |

The local TF-IDF retriever and direct installed-query adapter are development/emergency fallbacks only. They cannot be the path shown as the final hackathon implementation. The final demonstration and final twenty-case run must show TigerGraph graph retrieval, TigerGraph vector retrieval, GSQL/algorithm use, and TigerGraph MCP unless a documented platform outage is confirmed by organizers.

### Judging alignment matrix

| Criterion | Weight | What earns the score | Acceptance evidence |
|---|---:|---|---|
| Investigation accuracy | 25% | Causal transaction windows, robust per-card baselines, shared-entity paths, graph algorithm output, known/undocumented pattern detection, and explicit contradictory evidence | Historical replay/ablation report, golden cases, evidence-ledger trace, and human review of every low-confidence/high-exposure case |
| Next best action | 25% | Deterministic policy, permissions/routes, initial versus final actions, decision-impact evidence requests, uncertainty-aware stopping, and action changes grounded in the response | R1–R10 tests, branch traces, route validator, three demo scenarios, and twenty valid outputs |
| Case summary and explainability | 10% | Progressive case record, claim-level provenance, concise summary, uncertainty, supporting/contradicting evidence, SAR when required | Evidence ledger, JSON validation, readable dashboard, and SAR/action consistency tests |
| Agentic design and engineering | 15% | Typed resumable workflow, bounded MCP tools, checkpoints, case memory, idempotent writes, approvals, budgets, and deterministic fallbacks | Architecture diagram, resume/failure tests, tool logs, write/read-back, and versioned traces |
| Innovation | 15% | Contrastive case memory, temporal/leakage-safe graph evidence, decision-impact evidence gathering, memory-epoch isolation, and evidence independence | Working implementation visible in the demo—not slides or unimplemented design |
| Demo quality and completeness | 10% | Clear end-to-end story showing graph, uncertainty, evidence gathering, action change, approval, SAR decision, and memory update | Rehearsed 3–5 minute recording using real project output and no manual result editing |

The implementation order must protect the two 25% categories first. UI polish, embeddings, and extra integrations never take priority over investigation accuracy or next-best-action correctness.

## What the project owner needs to learn

You do not need to become a graph engineer before implementation. Spend at most 45 minutes learning the following vocabulary so you can review Opus and explain the demo:

1. **Graph basics, 10 minutes:** a vertex is a thing such as a card, transaction, device, or case; an edge is a relationship; a path connects things; a connected component is a group linked through edges.
2. **TigerGraph basics, 15 minutes:** the schema defines vertices/edges; a loading job imports CSVs; an installed GSQL query performs a safe repeatable traversal; a graph algorithm such as WCC finds connected groups; a vector index finds semantically similar cases/policy text.
3. **Agent basics, 10 minutes:** the agent follows a state machine, calls bounded tools through MCP, records evidence, applies policy, may request more evidence, and stops when the decision is defensible.
4. **Fraud-output basics, 10 minutes:** risk score is only a trigger; exposure is the verified suspicious amount; initial and final actions may differ; routes determine approval; a SAR is created only when policy requires it.

Your job during development is not to review every line of GSQL. At each gate, verify five questions:

- Does the output use real supplied IDs and only data available at that time?
- Can every important claim point to graph, vector, policy, or simulated-response evidence?
- Does policy code—not the LLM—control actions, routes, stopping, and SAR filing?
- Did the tests and validation command actually run successfully?
- Can the feature be shown clearly in the final demo?

If any answer is “no,” do not approve that gate.

## Master execution checklist and review gates

Opus or any coding agent must execute these gates in order. It may continue within a gate autonomously, but it must stop after each gate and provide the review packet described below. The user will ask the primary engineer to inspect that checkpoint before continuing.

### Gate 0 Repository, brief, and data contract

- [ ] Read this complete plan, the official brief, and the dataset README before writing implementation code.
- [ ] Create `PROGRESS.md`, `.env.example`, dependency metadata, and the agreed directory skeleton.
- [ ] Record dataset file hashes, sizes, row counts, headers, time ranges, and the exact answer schema.
- [ ] Prove the card/customer/transaction identifier mapping for all twenty benchmark cases.
- [ ] Create Pydantic models and validators for the exact supplied answer format.
- [ ] Run schema/validator tests on valid and invalid fixtures.

**Gate 0 exit:** the data contract is proven, all twenty triggers resolve, and the answer schema is executable. No graph design assumption remains unverified.

### Gate 1 TigerGraph graph and vector foundation

- [ ] Configure Savanna with auto-stop/auto-start and document setup without committing credentials.
- [ ] Finalize the graph schema only after Gate 0 audit results.
- [ ] Prepare normalized, idempotent vertex/edge loading files and versioned loading jobs.
- [ ] Load transactions, identities, customers/cards, shared entities, closed cases, and case-memory text.
- [ ] Create the TigerGraph vector index/attributes for closed-case and policy/typology retrieval.
- [ ] Reconcile expected versus loaded counts and run sampled path/vector searches.

**Gate 1 exit:** one card traverses to its transactions/customer/device/region/history; one semantic query returns relevant prior-case or policy chunks from TigerGraph; rerunning the loader does not duplicate data.

### Gate 2 GSQL, graph algorithms, MCP, and GraphRAG evidence

- [ ] Implement and install all bounded, versioned GSQL queries in this plan with `as_of_ts` support.
- [ ] Implement time-bounded WCC on suspicious shared-origin activity using a TigerGraph graph algorithm.
- [ ] Add path/algorithm provenance, result caps, timeouts, and supernode controls.
- [ ] Start TigerGraph MCP with only the required discovery/query/vector tools and log calls.
- [ ] Implement `GraphToolPort` with MCP primary and normalized direct-query emergency fallback.
- [ ] Implement hybrid GraphRAG: structural candidates plus TigerGraph vector reranking plus policy context.
- [ ] Test every query, one MCP invocation, algorithm output, vector retrieval, and context-package citations.

**Gate 2 exit:** a fixture case produces a compact evidence package through MCP containing structural graph evidence, graph-algorithm output, vector-retrieved memory/policy, negative evidence, and traceable IDs.

### Gate 3 Deterministic investigation intelligence

- [ ] Implement robust card baselines, temporal windows, pattern detectors, exposure, and graph features.
- [ ] Implement the probability/calibration path and its documented conservative fallback.
- [ ] Implement R1–R10, action permissions/routes, case/SAR rules, and stopping logic as deterministic code.
- [ ] Implement evidence independence and decision-impact request selection.
- [ ] Implement reproducible simulated customer/analyst/step-up responses.
- [ ] Complete unit tests and temporal historical replay/ablation evaluation.

**Gate 3 exit:** fraud, legitimate, and uncertain fixtures yield defensible probabilities/confidence, correct initial/final actions, correct approval routes, and no future evidence.

### Gate 4 One perfect end-to-end case

- [ ] Implement the typed LangGraph workflow, local durable checkpointing, budgets, retries, and idempotency.
- [ ] Run one real benchmark-format case from trigger through GraphRAG evidence, assessment, evidence request if useful, final action, SAR decision, validation, graph write, and read-back.
- [ ] Verify every summary/SAR assertion resolves to the evidence ledger.
- [ ] Interrupt and resume the run to prove it does not duplicate calls, evidence, or writes.
- [ ] Save the complete trace and promote the case structure—not its conclusions—to a golden fixture.

**Gate 4 exit:** one case is genuinely submission-quality and reproducible end to end. Do not start the twenty-case batch before this gate passes review.

### Gate 5 Frozen-memory twenty-case batch

- [ ] Freeze the historical memory manifest and process the twenty cases without cross-case visibility.
- [ ] Validate all provisional answers, then freeze the answer/configuration manifest.
- [ ] Commit all twenty cases to TigerGraph, read them back, and export final answer files.
- [ ] Run the full validator and manual-review table; resolve every SAR, undocumented pattern, high exposure, low confidence, and missing analogue flag.
- [ ] Rerun in opposite case order and prove substantive invariance.
- [ ] Produce exactly twenty accepted JSON files and the machine/human validation reports.

**Gate 5 exit:** the validator exits zero, every case has a graph receipt, and the outputs are frozen. From this point, output-changing code requires rerunning the complete validation gate.

### Gate 6 Dashboard and judged demonstration

- [ ] Build the Streamlit dashboard around frozen real traces, not handcrafted demo data.
- [ ] Show case progression, graph paths/WCC, TigerGraph vector memory, evidence for/against, probability history, policy/routing, action change, SAR, and write-back.
- [ ] Curate three cases: clear graph fraud, legitimate false positive, and uncertain evidence-changing case.
- [ ] Add failure-friendly table/text fallbacks when visualization is unavailable.
- [ ] Rehearse and record a 3–5 minute end-to-end demo mapped to all six judging criteria.

**Gate 6 exit:** a new viewer can understand trigger → evidence → uncertainty → request → action → explanation → memory update within five minutes.

### Gate 7 Submission package and release

- [ ] Confirm the working agent and public/accessible GitHub repository are ready.
- [ ] Complete README, architecture diagram, setup/run commands, and limitations.
- [ ] Finish the technical blog covering exactly: what was built, architecture, how TigerGraph is used, agentic capabilities, lessons learned, and what would be improved with more time.
- [ ] Prepare the social post with blog/demo link and `@TigerGraphDB` tag.
- [ ] Verify repository visibility, licenses/attributions, secrets scan, data exclusions, links, video permissions, and clean-clone reproduction.
- [ ] Perform a final twenty-case rerun or checksum verification as appropriate and archive the release commit/tag.
- [ ] Have the team lead verify every submission-form field before the one permitted submission.

**Gate 7 exit:** every official deliverable exists, opens without private permissions, and corresponds to the same frozen release commit.

### Official submission inventory

- [ ] Working agent.
- [ ] Accessible GitHub repository.
- [ ] Twenty answer files, each containing the internal case, evidence, findings, decisions/actions, conditional SAR, initial next-best action/approval route, final next-best action/approval route, and successful graph write-back.
- [ ] Three-to-five-minute end-to-end demo video.
- [ ] Technical blog with all six required topics.
- [ ] X or LinkedIn post linking to the blog or demo and tagging `@TigerGraphDB`.
- [ ] Team lead has checked the form and links before the single irreversible submission.

### Required review packet after every gate

The coding agent must stop and report:

- Gate and checklist items completed.
- Commit hashes in chronological order.
- Files added/changed and why.
- Commands/tests executed with their actual results.
- Screenshots or trace paths proving UI/TigerGraph behaviour when applicable.
- Known limitations, assumptions, and blockers.
- Exact next gate and first intended sub-step.

No “done” claim is accepted without executed verification evidence.

### Mandatory Git discipline for Opus and every coding agent

Git history is part of the engineering evidence. Agents must preserve it as follows:

1. Start every work session with `git status`, `git log --oneline -10`, and a read of `PROGRESS.md`.
2. Make one atomic commit after every meaningful sub-step, not merely after a whole gate. Examples include schema creation, one loading job, one installed query family, one policy-rule set, one validator group, one workflow node group, or one dashboard view.
3. A commit must contain only one coherent change and its directly related tests/documentation. Do not mix refactors, generated case outputs, UI work, and graph logic in one commit.
4. Run the smallest relevant verification before committing. Never commit known-broken code unless the commit subject begins with `wip:` and the agent stops immediately for review; avoid WIP commits whenever possible.
5. Use descriptive conventional subjects such as:
   - `chore: scaffold local project and configuration`
   - `test: lock exact answer contract`
   - `feat(graph): add transaction and identity schema`
   - `feat(gsql): add temporal card baseline query`
   - `feat(retrieval): add TigerGraph vector case memory`
   - `feat(policy): implement R1 through R5`
   - `feat(agent): add evidence decision branch`
   - `fix(validation): reject benchmark memory leakage`
6. Include test evidence in the commit body when the change is non-trivial: command run and concise result.
7. Update `PROGRESS.md` in the same commit that completes a checklist sub-step; do not create progress-only noise commits unless correcting the record.
8. Push after every completed, passing gate and at least every few atomic commits during long gates so work is recoverable.
9. Never commit `.env`, tokens, raw source data, large prepared data, local databases, private customer details, or temporary render/run artifacts.
10. Never use `git commit --amend`, interactive rebase, squash, reset, force-push, or history rewriting after a commit has been shared unless the user explicitly authorizes it. Fix mistakes with a new commit so the review trail remains intact.
11. Do not stage unrelated user changes. Before each commit, inspect `git diff --staged` and list the files being committed.
12. Tag the final frozen submission commit as `hhgoa-submission-v1` only after Gate 7 passes.

Suggested commit granularity is 3–8 focused commits per gate. The goal is a reviewable engineering trail, not one commit per keystroke or a single giant gate commit.

## Executive decision

Build one focused application named **FraudGraph Investigator**.

FraudGraph Investigator accepts a benchmark case, investigates it using TigerGraph and prior cases, measures uncertainty, requests simulated evidence when policy requires it, applies deterministic policy rules, generates the final case and suspicious activity report, writes the case back to TigerGraph, and exports the required JSON answer.

Do not build a generic chatbot, a swarm of agents, a browser automation product, a durable cloud agent platform, or a real-time banking system. Those are outside the critical path.

The winning architecture is a **bounded evidence-to-decision pipeline**, not an autonomous fraud oracle:

```text
temporal graph evidence
  + contrastive prior-case memory
  + robust behavioural features
  -> calibrated evidence score
  -> deterministic policy/action engine
  -> constrained LLM explanation and SAR draft
  -> schema/policy/provenance validation
  -> immutable case export and graph write-back
```

The LLM is the investigator's planner and narrator. Installed queries, deterministic analytics, and policy code remain the authority for facts, money, probabilities, approval routes, and filing decisions.

## Research-driven improvements over the original plan

The following decisions are mandatory because they materially improve correctness or delivery reliability:

| Research finding | Decision for this project | Why it matters now |
|---|---|---|
| Graph-enhanced IEEE-CIS systems gain value from shared cards/devices/emails/addresses and simple topology features | Add time-bounded degree, connected-card count, prior-fraud-neighbour count, component size, and shared-origin rarity features | Stronger and more explainable than asking an LLM to infer structure from raw rows |
| Fraud graphs drift over time and graph features can leak future information | Every runtime feature and offline evaluation feature must use only information available at the case anchor time | Prevents falsely impressive evaluation and impossible evidence |
| GraphRAG works best as curated structural queries plus bounded hybrid retrieval | Use installed GSQL queries for facts; use vector similarity only to rerank a filtered closed-case pool | Faster, safer, and easier to debug than full free-form text-to-GSQL or a large GraphRAG deployment |
| Similar confirmed cases alone create confirmation bias | Retrieve a contrastive set: fraud analogues, cleared analogues, and if possible one boundary/ambiguous case | Makes false-positive handling visibly stronger |
| Raw anomaly scores are not probabilities | Calibrate on temporally held-out closed cases and report Brier score/calibration error; otherwise label the number an evidence confidence, not a calibrated probability | Avoids unjustified precision and unstable policy thresholds |
| Agent frameworks are reliable when state, tools, and write permissions are bounded | Use one typed LangGraph workflow, checkpoint after expensive nodes, expose a small read-only MCP tool surface, and allow one validated write path | Prevents looping, accidental mutation, and deadline-ending reruns |
| More evidence is useful only when it can change a decision | Rank evidence requests by expected decision impact and ask only when plausible responses can change verdict, action, approval route, or SAR decision | Produces better next-best actions rather than ritual verification |
| Batch case memory can create order dependence | Investigate all twenty cases against a frozen historical-memory snapshot; write benchmark cases only after outputs are frozen, or exclude the current benchmark epoch from retrieval | Guarantees the same answer regardless of processing order |
| Explainability is strongest when every assertion has provenance | Maintain an internal evidence ledger with query version, case-time cutoff, entities, values, independence group, and content hash | Enables claim-level audit and a compelling demo |

## Delivery tiers and scope lock

### Tier 0: submission-critical

- Audit and normalize the four supplied files.
- Load the core graph, historical cases, and a minimal TigerGraph vector index.
- Install bounded GSQL queries and time-bounded WCC.
- Connect the agent through TigerGraph MCP and assemble GraphRAG context from graph, vector, and policy evidence.
- Investigate and validate all twenty benchmark cases.
- Apply R1-R10 and routes deterministically.
- Produce initial/final actions, simulated evidence when justified, SAR decisions, graph write receipts, and twenty valid JSON files.

### Tier 1: score multipliers

- Temporal graph features and robust per-card baselines.
- Contrastive prior-case retrieval.
- Calibrated probability or clearly labeled fallback confidence.
- Evidence ledger and case-time provenance.
- Decision-impact evidence selection.
- Clear dashboard for three curated cases.

### Tier 2: stretch only after all twenty files validate

- FastRP structural embeddings.
- Community detection beyond a bounded suspicious subgraph.
- Rich graph animation, streaming ingestion, or general natural-language graph chat.

If a Tier 2 item threatens Tier 0 or Tier 1, delete it from the build without further discussion.

## Non-negotiable product behaviour

The completed system must:

1. Load and investigate all twenty benchmark cases.
2. Use TigerGraph for relational investigation and case memory.
3. Use installed GSQL queries for core calculations and traversals.
4. Connect the agent to TigerGraph through the official TigerGraph MCP server.
5. Retrieve relevant prior cases and policy context before making a decision.
6. Treat the supplied risk score only as an investigation trigger, never as a verdict.
7. Distinguish fraud, legitimate activity, and genuine uncertainty.
8. Ask for additional evidence when the policy or uncertainty requires it.
9. Record recommendations both before and after additional evidence.
10. Apply policy and approval routes deterministically in application code.
11. Generate a SAR only when the policy requires one.
12. Write every completed investigation back into TigerGraph as case memory.
13. Produce exactly one valid JSON file for each benchmark case.
14. Track graph/tool calls, token usage, and latency for each case.
15. Provide a dashboard that explains the investigation rather than merely displaying the final verdict.

## Explicit non-goals

Do not spend time on the following unless every Definition of Done item is already satisfied:

- Multiple cooperating LLM agents.
- Kubernetes, Kafka, Cloudflare Durable Objects, or a custom execution daemon.
- Real card blocking, customer messaging, refunding, CRM updates, or regulatory submission.
- A custom general-purpose MCP framework.
- Authentication, multi-tenancy, billing, or production infrastructure.
- Training a graph neural network.
- Loading every anonymous Vesta feature as a first-class graph relationship.
- Elaborate 3D graph rendering.
- Continuous live transaction ingestion.
- Mobile applications.

## Chosen implementation stack

Use the following stack unless a hard technical blocker is demonstrated:

- Python 3.11 or newer.
- TigerGraph Savanna for the graph database.
- Official `tigergraph-mcp` package for MCP access.
- `pyTigerGraph` for ingestion and direct administrative operations.
- LangGraph for the investigation state machine.
- Pydantic v2 for all internal and final schemas.
- Polars for processing the large transaction CSV without loading it all into memory.
- DuckDB and Parquet for optional local analytical staging and reproducible preprocessing.
- Streamlit for the analyst dashboard.
- Plotly and/or PyVis for lightweight charts and graph views.
- An OpenAI-compatible or Gemini model selected through environment variables.
- `pytest` for tests.
- `ruff` for formatting and linting.

Use TigerGraph MCP as the primary agent-facing graph interface. Also implement a narrow `GraphToolPort` abstraction with a direct installed-query client as a tested fallback. Both adapters must return the same normalized evidence schema. This is resilience, not permission for the model to bypass MCP or generate arbitrary GSQL.

Do **not** deploy the complete TigerGraph GraphRAG stack unless it is already running and verified. Reuse its strongest architectural idea—pre-approved structural queries plus bounded hybrid retrieval—inside this smaller application. A local deterministic lexical/feature similarity fallback is required so case retrieval still works if vector search is unavailable.

Do not introduce another framework when the selected stack already covers the requirement.

## Local-first repository rule

Everything required to understand, configure, run, test, and submit the project must live under this directory.

External packages may be installed normally. Do not make the implementation depend on another personal GitHub repository being present. Reuse ideas and patterns locally, but copy or reimplement only the small pieces actually required.

The final repository must contain:

- Source code.
- Graph schema and queries.
- Data preparation scripts.
- Configuration examples.
- Policy rules.
- Output schemas.
- Tests.
- Generated case files.
- Architecture documentation.
- Demo instructions.
- A reproducible command for regenerating all twenty answers.

Secrets and the large source CSV files must not be committed.

## Required local repository structure

Create this structure as implementation begins:

```text
G:/HH GOA/
├── HHGOA_FRAUD_INVESTIGATOR_BUILD_PLAN.md
├── README.md
├── .env.example
├── .gitignore
├── pyproject.toml
├── Makefile                         # optional on Windows; scripts must also work directly
├── app/
│   ├── __init__.py
│   ├── dashboard.py                # Streamlit entry point
│   ├── components/
│   └── view_models.py
├── agent/
│   ├── __init__.py
│   ├── graph.py                    # LangGraph workflow construction
│   ├── nodes.py                    # workflow node implementations
│   ├── state.py                    # InvestigationState
│   ├── prompts.py
│   ├── model_client.py
│   └── runner.py
├── domain/
│   ├── __init__.py
│   ├── answer_models.py            # exact answer contract
│   ├── evidence_models.py
│   ├── investigation_models.py
│   └── enums.py
├── policy/
│   ├── __init__.py
│   ├── engine.py                   # deterministic R1-R10 implementation
│   ├── rules.py
│   ├── routing.py
│   └── stopping.py
├── graph/
│   ├── schema.gsql
│   ├── loading_jobs.gsql
│   ├── install_queries.gsql
│   ├── queries/
│   │   ├── get_case_context.gsql
│   │   ├── get_card_baseline.gsql
│   │   ├── get_transaction_window.gsql
│   │   ├── find_shared_origin_activity.gsql
│   │   ├── find_region_anomalies.gsql
│   │   ├── find_similar_closed_cases.gsql
│   │   ├── extract_temporal_graph_features.gsql
│   │   ├── calculate_case_exposure.gsql
│   │   └── write_investigation_case.gsql
│   ├── client.py
│   ├── mcp_client.py
│   ├── tool_port.py                 # identical contract for MCP primary/direct fallback
│   └── result_normalizers.py
├── retrieval/
│   ├── __init__.py
│   ├── policy_retriever.py
│   ├── prior_case_retriever.py
│   ├── contrastive_ranker.py
│   └── context_builder.py
├── scoring/
│   ├── __init__.py
│   ├── pattern_detectors.py
│   ├── probability.py
│   ├── calibration.py
│   ├── robust_baselines.py
│   └── decision_impact.py
├── evidence/
│   ├── __init__.py
│   ├── ledger.py                    # append-only claim/provenance records
│   ├── independence.py
│   └── hashing.py
├── evaluation/
│   ├── __init__.py
│   ├── temporal_split.py
│   ├── replay_closed_cases.py
│   ├── retrieval_metrics.py
│   └── report.py
├── ingestion/
│   ├── __init__.py
│   ├── audit_inputs.py
│   ├── derive_entities.py
│   ├── prepare_graph_files.py
│   ├── load_graph.py
│   └── verify_graph.py
├── validation/
│   ├── __init__.py
│   ├── answer_validator.py
│   ├── dataset_ids.py
│   └── cross_field_rules.py
├── scripts/
│   ├── bootstrap.py
│   ├── run_case.py
│   ├── run_all_cases.py
│   ├── validate_all_cases.py
│   ├── evaluate_closed_cases.py
│   └── export_demo_bundle.py
├── config/
│   ├── settings.yaml
│   ├── pattern_thresholds.yaml
│   └── model.yaml
├── knowledge/
│   ├── fraud_policy.md
│   ├── fraud_patterns.md
│   ├── answer_contract.md
│   └── regulatory_sources.md
├── data/
│   ├── raw/                        # ignored by git
│   ├── prepared/                   # ignored by git
│   ├── cache/                      # ignored by git
│   └── README.md
├── cases/                          # final twenty JSON answers
├── runs/                           # ignored run logs and intermediate traces
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── golden/
├── docs/
│   ├── architecture.md
│   ├── graph_model.md
│   ├── investigation_flow.md
│   ├── demo_script.md
│   ├── submission_checklist.md
│   ├── research_decisions.md
│   └── blog_outline.md
└── artifacts/
    ├── screenshots/
    └── demo/
```

## Source dataset contract

The implementation expects these files in `data/raw/`:

| File | Purpose |
|---|---|
| `transactions.csv` | Approximately 590,742 transactions and the original Vesta feature columns plus `customer_id`, `ts`, `channel`, and `risk_score` |
| `identity.csv` | Approximately 144,432 online identity records joined using `TransactionID` |
| `closed_cases_history.csv` | 5,565 resolved investigations used as labeled history and initial case memory |
| `case_pack.csv` | The twenty benchmark cases |

The raw files are UTF-8 CSVs. Amounts are USD. `transactions.csv` joins to `identity.csv` using `TransactionID`.

The implementation must never use the public IEEE-CIS/Kaggle labels or attempt to reverse transformed identifiers. Only the supplied files may be used for benchmark decisions.

## Phase zero data audit gate

Before finalizing the graph schema or writing ingestion logic, the implementation agent must execute a data audit and save the result to `runs/data_audit.json`.

The audit must record:

- Exact file sizes.
- Row counts.
- Exact headers.
- Inferred data types.
- Null percentage for relevant fields.
- Duplicate counts for primary identifiers.
- Whether `card_id` exists directly or must be derived.
- How benchmark card identifiers map to transaction rows.
- Whether every flagged transaction exists.
- Whether every benchmark customer exists.
- Whether every closed-case transaction ID exists.
- Date range.
- Whether `ts` is event time, derived time, or wall-clock time, and its timezone/epoch interpretation.
- Distinct channels.
- Distinct known outcomes and patterns.
- A sample of five rows from each file with sensitive/raw anonymous feature values omitted from logs when unnecessary.
- Cardinality and collision analysis for each proposed shared entity: card, device signature, purchaser email, recipient email, and region.
- Leakage audit proving which fields are available at transaction time versus created after investigation closure.

**Hard stop:** do not guess how `card_id` is derived. Establish the mapping from the supplied data and benchmark records. If the mapping cannot be proven, surface it as the one blocking question.

## Graph model

### Core vertices

#### `Customer`

- Primary ID: `customer_id`.
- Useful attributes: total transaction count, first seen, last seen, number of cards.

#### `Card`

- Primary ID: dataset-derived `card_id`.
- Useful attributes: card network, card type, issuer-related codes, first seen, last seen.

#### `Transaction`

- Primary ID: `TransactionID` represented consistently as a string.
- Attributes required for investigation:
  - Timestamp.
  - Amount.
  - Product code.
  - Channel.
  - Risk score.
  - Billing region and country.
  - Purchaser and recipient email domains.
  - Selected interpretable device/match/distance/count/time features.
  - A compact reference to the raw Parquet row for deeper inspection.

Load every transaction row. It is acceptable to keep anonymous high-dimensional feature columns in local Parquet rather than making every feature a graph attribute, provided the graph contains the fields needed for relationship discovery and the raw feature lookup remains available as supplementary evidence.

#### `DeviceProfile`

- Primary ID: deterministic hash of the normalized device signature.
- Signature inputs should include, when present:
  - `DeviceInfo`.
  - Device type.
  - Operating system (`id_30`).
  - Browser (`id_31`).
  - Screen (`id_33`).
- Additional attributes may include proxy category (`id_23`), match status (`id_34`), and new/found status (`id_15`).
- Store a human-readable normalized label in addition to the hash.
- Never collapse rows solely because a coarse field such as browser, operating system, or `DeviceType` matches. Generate a strong composite signature only when enough identity fields exist. When the signature is weak, store the transaction attributes but do not create a shared device edge capable of linking cards.
- Record `signature_strength` and the contributing fields so every shared-device claim is explainable.

#### `EmailDomain`

- Primary ID: normalized lowercase domain.
- Preserve whether it appeared as purchaser or recipient through edge types.

#### `BillingRegion`

- Primary ID: normalized `addr1` code.
- Store country code `addr2` when meaningful.

#### `ClosedCase`

- Primary ID: `case_id`.
- Attributes: outcome, pattern, opened/closed timestamps, exposure, actions, report flag, analyst notes, and narrative text used for retrieval.

#### `InvestigationCase`

- Primary ID: benchmark case ID or a stable prefixed version.
- Attributes: status, verdict, probability, pattern, exposure, summary, stop reason, initial actions, final actions, timestamps, metrics, and a serialized validated answer snapshot.
- Add `memory_epoch`, `query_bundle_version`, `scoring_version`, and `policy_version` to make replay and exclusion deterministic.

### Core edges

- `Customer -OWNS-> Card`
- `Card -MADE-> Transaction`
- `Transaction -FROM_DEVICE-> DeviceProfile`
- `Transaction -PURCHASER_EMAIL-> EmailDomain`
- `Transaction -RECIPIENT_EMAIL-> EmailDomain`
- `Transaction -BILLED_IN-> BillingRegion`
- `Transaction -NEXT-> Transaction`, ordered within a card by timestamp
- `ClosedCase -INVOLVES-> Transaction`
- `ClosedCase -ON_CARD-> Card`
- `ClosedCase -CONNECTED_TO-> Card`
- `InvestigationCase -INVOLVES-> Transaction`
- `InvestigationCase -ON_CARD-> Card`
- `InvestigationCase -CONNECTED_TO-> Card`
- `InvestigationCase -USES_DEVICE-> DeviceProfile`
- `InvestigationCase -SIMILAR_TO-> ClosedCase`

### Graph constraints

- IDs must be normalized once and reused everywhere.
- No answer may contain an ID absent from the source dataset or a legitimately created investigation-case vertex.
- Edge-loading operations must be idempotent.
- Re-running ingestion must not duplicate vertices or edges.
- `NEXT` edges must be produced by a deterministic sort using card ID, timestamp, and transaction ID as a stable tie-breaker.
- Every query evaluating a historical case must accept an `as_of_ts` cutoff and ignore later transactions, later labels, and cases not closed by that cutoff.
- Treat region and common email domains as potential supernodes. Never infer coordination from raw degree alone; require time proximity plus an IDF-like rarity or fraud-enrichment measure.
- Benchmark cases belong to one `memory_epoch`. They must not be visible to prior-case retrieval until every benchmark answer is frozen.

## Temporal and leakage contract

This contract applies to ingestion, queries, scoring, retrieval, and evaluation:

1. The anchor time is the flagged transaction timestamp unless the challenge explicitly defines another time.
2. A fact is admissible only if its `observed_at <= anchor_time`, except a clearly labeled simulated response requested during the investigation.
3. Closed-case outcome, analyst notes, actions, and SAR disposition may be used as training/retrieval memory only when that case closed before the new case's anchor time.
4. Graph features must be computed on the causal subgraph visible at the cutoff, never on the full graph with future edges.
5. Normalization, imputation, thresholds, calibration, and retrieval weights are fit on the training period only.
6. The benchmark twenty may never be used to tune weights, thresholds, prompts, or policies after their outputs are inspected.
7. Each evidence ledger row stores `anchor_time`, `data_max_time`, and `leakage_check_passed`.

A test named `test_no_future_evidence.py` must fail if any runtime evidence crosses its cutoff.

## Required installed GSQL queries

The agent must call a small set of purpose-built queries. Do not give the LLM unrestricted responsibility for generating the core analytics.

### `get_case_context`

Input: benchmark `case_id` or flagged transaction ID.

Return:

- Trigger information.
- Flagged transaction.
- Card and customer.
- Immediate device, email, region, and adjacent transactions.
- Risk score and relevant identifiers.

### `get_card_baseline`

Input: card ID and optional lookback window.

Return:

- Transaction count.
- Amount distribution.
- Normal channels.
- Known devices.
- Normal regions.
- Product-code distribution.
- Recurring amount/time patterns.
- Recent velocity measures.
- Robust amount baselines: median, median absolute deviation (MAD), and empirical percentile. Do not depend only on mean and standard deviation, which are easily distorted by outliers.
- The same statistics in fixed windows: one hour, twenty-four hours, seven days, thirty days, and lifetime-to-anchor.

### `get_transaction_window`

Input: card ID, anchor timestamp, hours/days before and after.

Return ordered transactions with enough attributes to detect bursts, card testing, and episode boundaries.

### `find_shared_origin_activity`

Input: device profile, region, or email domain plus a bounded time window.

Return:

- Other connected cards and customers.
- Their transactions.
- Their prior closed cases.
- Whether the shared element has confirmed-fraud history.
- Total degree, time-window degree, fraud-linked degree, and a rarity score so common domains/regions do not masquerade as rings.

This query must prevent unbounded graph expansion.

### `find_region_anomalies`

Input: card ID and flagged transaction.

Return:

- Whether the region is new for the card.
- Historical region frequencies.
- Simultaneous or nearby normal home-region activity.
- Duration and transaction count of activity in the new region.

### `find_similar_closed_cases`

Input: structured investigation features and/or vector query.

Return a balanced list containing both confirmed fraud and cleared cases when available. Each result must include why it was retrieved.

The query must exclude the current case, future-closed cases, and all cases from the active benchmark memory epoch.

### `extract_temporal_graph_features`

Input: card ID, flagged transaction, and `as_of_ts`.

Return a bounded, interpretable feature vector:

- Device/email/region degree within 1h, 24h, 7d, and all visible history.
- Distinct connected cards and customers.
- Count and recency of confirmed-fraud and cleared neighbours.
- Time-local weakly connected component size on suspicious shared-origin edges.
- Two-hop fraud reachability, with the exact paths capped and returned for provenance.
- Shared-entity rarity and fraud enrichment.
- Burst count, amount MAD score, region novelty, device novelty, and home-region overlap.

Do not add PageRank, Louvain, FastRP, or node2vec to the critical path. Add FastRP only as a Tier 2 experiment if deterministic features and the twenty-case batch are complete. Node2vec is explicitly rejected for this deadline because relevant reference implementations report materially longer runtimes.

### `calculate_case_exposure`

Input: affected transaction IDs.

Return the sum of absolute transaction amounts and explicitly report missing IDs.

### `write_investigation_case`

Input: validated answer model.

Create or update the investigation case and its evidence relationships idempotently. Return the graph case ID and a read-back confirming the stored values.

## GraphRAG design

GraphRAG in this project means retrieving a compact evidence package from graph relationships plus relevant policy/prior-case text and giving that package to the LLM.

It does not mean sending raw CSV rows or the entire graph to the model.

The context builder must produce four clearly separated sections:

1. **Trigger and baseline**: the flagged transaction and normal behaviour.
2. **Graph evidence**: sequences, shared origins, connected cards, regions, and exposure.
3. **Case memory**: similar confirmed and cleared prior cases with retrieval reasons.
4. **Policy context**: only the policy rules relevant to the current evidence.

Every evidence item supplied to the model must have:

- A claim.
- A source type.
- A query or document reference.
- Supporting entity IDs.
- A structured value where applicable.

The final answer may contain only claims traceable to this evidence package or to a recorded simulated evidence response.

### Prior-case retrieval pipeline

Implement retrieval as a deterministic two-stage pipeline:

1. **Candidate generation:** filter closed cases by causal availability, pattern/channel compatibility, amount band, novelty flags, shared entities, and graph-feature neighbourhood.
2. **Reranking:** combine normalized structured similarity, optional text embedding similarity, outcome diversity, and recency decay.

Return at most six cases:

- Up to two confirmed-fraud analogues.
- Up to two cleared/legitimate analogues.
- Up to two ambiguous or structurally close boundary cases.

For every result return a reason vector such as `same_new_device`, `similar_velocity`, `shared_origin`, `similar_amount_percentile`, `opposite_outcome`, and the component scores. Do not retrieve a case merely because its narrative shares generic fraud words.

During closed-case replay, use leave-one-case-out retrieval. During the twenty-case benchmark, freeze the historical index before the first case runs.

TigerGraph 4.2+ vector search must rerank the compact closed-case/policy candidate set in the final implementation. During local development or a temporary service outage, TF-IDF/feature cosine may exercise the same interface, but it does not satisfy the final challenge gate. The graph traversal remains authoritative; vector similarity supplies case/policy relevance rather than factual proof.

### Evidence ledger

Before any claim reaches the LLM, append an internal ledger record with:

- `evidence_id`.
- Normalized claim and typed value.
- Source entity IDs.
- Installed query name, query-bundle version, and normalized parameters.
- `anchor_time` and maximum source timestamp.
- Independence group: `trigger_model`, `customer_history`, `temporal_sequence`, `device_network`, `region_network`, `case_memory`, `customer_response`, or `policy`.
- Strength: `supporting`, `contradicting`, or `neutral`.
- SHA-256 content hash and previous-record hash.

Hash chaining is optional for judging but cheap to implement. The important requirement is that the final summary and SAR assertions reference ledger IDs and that two rows from the same independence group do not satisfy the two-independent-evidence stopping rule.

## Fraud pattern detectors

Implement deterministic candidate detectors before LLM synthesis. The LLM may refine the interpretation but must not invent raw signals.

### Card testing

Candidate conditions:

- At least three small online authorizations within one hour.
- Usually amounts below USD 5.
- Followed by a larger purchase.
- Shared device/identity consistency strengthens the signal.

### Card-not-present fraud

Candidate conditions:

- Online purchase or burst inconsistent with historical amount/product behaviour.
- Often two to four transactions within forty-eight hours.
- A single unusual online purchase remains ambiguous without corroboration.

### Card-not-present fraud from a new device

Candidate conditions:

- Card-not-present candidate conditions.
- Device marked new or unseen for the card/customer.
- Proxy or device anomalies increase confidence but do not independently prove fraud.

### Out-of-region use

Candidate conditions:

- In-person use in a region absent from card history.
- Normal activity continuing at home strengthens clone suspicion.
- Multiple days consistently in one new region weakens fraud suspicion because it may be travel.

### Account takeover

Candidate conditions:

- Mixed-channel anomalous activity.
- Device and match-flag anomalies.
- Broader behavioural inconsistency pointing to stolen credentials rather than only a stolen card number.

### Undocumented pattern

Use only when coordinated or repeated abuse is evidenced but the activity does not satisfy one of the five known patterns. The answer must describe the discovered behaviour without forcing it into a known category.

### No fraud pattern

Use `none` for legitimate or unresolved activity that does not support a fraud pattern.

## Fraud probability and calibration

Probability must be evidence-based and must not copy the supplied risk score.

Implement an explicit scoring module with:

- Named evidence features.
- Positive and negative weights.
- A documented transformation into a 0-to-1 probability.
- Caps preventing one weak signal from producing extreme confidence.
- Calibration checks against closed confirmed and cleared cases.
- Unit tests for probability boundaries and monotonic behaviour.

At minimum, consider:

- Known fraud sequence match.
- New device.
- Shared device linked to confirmed fraud.
- Shared region/email connected to other fraud.
- Customer denial or confirmation.
- Recurring legitimate pattern.
- Established travel-like behaviour.
- Amount/velocity anomaly.
- Conflict between signals.
- Similar confirmed cases.
- Similar cleared cases.

The supplied bank risk score may be one feature, but it must have limited influence.

Because the closed-case history is imbalanced, retrieval and calibration must not simply reproduce the majority class. Always compare against cleared cases as well as confirmed fraud cases.

### Required scoring implementation

Use a simple, inspectable scorer for the deadline:

1. Produce deterministic features from graph queries and robust card baselines.
2. Fit either regularized logistic regression or a small monotonic gradient-boosted model on historical closed cases.
3. Use a chronological train/calibration/test split based on case anchor/closure time. Never use a random split as the primary result.
4. Calibrate with Platt scaling by default. Use isotonic regression only when the calibration split has enough positive and negative cases to avoid a stepwise overfit.
5. Evaluate ROC-AUC, average precision/PR-AUC, Brier score, expected calibration error, precision at the review budget, and confusion counts at policy thresholds.
6. Compare against two baselines: supplied risk score alone and a no-graph model. Keep graph features only if they improve at least one operational metric without materially degrading calibration.

The output field remains `fraud_probability` only when the held-out calibration report passes these gates:

- At least twenty positive and twenty negative calibration examples.
- Brier score beats or matches the uncalibrated score.
- No obvious empty or inverted reliability bins.
- Predictions are not collapsed into only 0 and 1.

If those gates cannot be met before final generation, use a documented rule-based probability mapping, avoid values below 0.05 or above 0.95 without decisive verification, and write `runs/calibration_report.json` explaining that it is a policy confidence approximation. Never fabricate calibration quality.

### Evidence feature discipline

- Use capped, normalized feature contributions so one high-degree supernode cannot dominate.
- Keep the supplied `risk_score` contribution at no more than 20% of the pre-calibration logit/points budget.
- Represent missing evidence separately from negative evidence.
- Record positive and negative contribution tables per case.
- Detect conflicting evidence and widen uncertainty instead of averaging it away.
- Do not claim causal effects from correlational graph links.

## Deterministic fraud policy

The following rules must be implemented in `policy/`. The LLM may explain the decision but may not override these rules.

### Allowed actions and approval routes

#### Automatic route

- `ALLOW_TRANSACTION`
- `MONITOR_CARD`
- `MONITOR_CONNECTED_CARDS`
- `WARN_CUSTOMER`
- `VERIFY_WITH_CUSTOMER`
- `STEP_UP_AUTH`
- `GENERATE_REPORT`
- `CREATE_CASE`
- `ESCALATE_TO_ANALYST`
- `CLOSE_NO_FRAUD`

#### L1 route

- `DECLINE_TRANSACTION`
- `BLOCK_CARD` when exposure is less than or equal to USD 2,500

#### L2 route

- `BLOCK_CARD` when exposure is greater than USD 2,500
- `BLOCK_ALL_CARDS`
- `FILE_REPORT`

### R1 Verify before blocking on a weak signal

When the case rests on one signal and fraud probability is below 0.70, recommend `VERIFY_WITH_CUSTOMER` or `STEP_UP_AUTH` before a block.

### R2 Customer denies the transaction

Recommend `BLOCK_CARD` and `CREATE_CASE`. Add `FILE_REPORT` when exposure exceeds USD 1,000 or the case connects to a shared device profile or another card's fraud.

### R3 Customer confirms the transaction

Recommend `CLOSE_NO_FRAUD` and record the confirmation.

### R4 No response within twenty-four hours

Recommend `MONITOR_CARD` and `DECLINE_TRANSACTION` for pending authorizations. Escalate when exposure exceeds USD 500.

### R5 Card testing

Three or more small online authorizations within one hour followed by a larger purchase require `DECLINE_TRANSACTION` and `STEP_UP_AUTH`. If a purchase over USD 100 has cleared, recommend `BLOCK_CARD`.

### R6 Shared origin

When several cards show fraud from the same device profile, billing region, or recipient email in one window, name the shared element and recommend `CREATE_CASE`, `FILE_REPORT`, and `MONITOR_CONNECTED_CARDS`.

### R7 Disputed but legitimate

When a disputed charge matches the customer's recurring pattern, recommend `CREATE_CASE`, `VERIFY_WITH_CUSTOMER`, and `WARN_CUSTOMER`. Do not block.

### R8 Uncertain and exposed

When verdict is `uncertain` and exposure exceeds USD 500, or evidence conflicts materially, recommend `ESCALATE_TO_ANALYST`.

### R9 Undocumented coordinated pattern

When evidence shows coordinated or repeated abuse that fits no known pattern, recommend `CREATE_CASE`, `FILE_REPORT`, and `ESCALATE_TO_ANALYST`. Describe the pattern plainly.

### R10 Block all cards restriction

Never recommend `BLOCK_ALL_CARDS` unless at least two of the customer's cards show confirmed fraud or the customer's credentials are confirmed compromised.

### Case creation rule

Create a case when any of the following is true:

- Fraud probability is at least 0.30.
- Additional evidence is requested.
- A customer disputes a transaction.

### SAR rule

Recommend `FILE_REPORT` only when fraud is confirmed or strongly suspected and at least one condition is true:

- Exposure exceeds USD 1,000.
- Activity connects to a shared device, shared region cluster, or another customer's fraud.
- The pattern is coordinated or undocumented.

A SAR always requires a case. Most cases should not produce a SAR.

### Investigation stopping rule

Stop when one of these conditions holds:

- Probability is at least 0.85 with at least two independent evidence items.
- Probability is at most 0.15 with at least two independent evidence items.
- A verification response settles the question.
- Further investigation is unlikely to change the action, and this is explained.

## Simulated evidence design

The dataset does not provide customer or analyst responses. The system may simulate:

- Customer validation.
- Step-up authentication.
- Analyst information.

Simulation must be explicit and reproducible.

Requirements:

- Never disguise a simulated response as observed source data.
- Record the request type, investigation step, and assumed response.
- Use a deterministic seed based on case ID for repeatable runs.
- Prefer scenario rules grounded in the benchmark trigger and graph evidence rather than unconstrained LLM invention.
- Show both initial and final recommendations.
- Record what changed and why.

### Decision-impact evidence selection

Do not automatically request customer validation for every uncertain case. For each allowed request type:

1. Enumerate a small fixed set of plausible responses.
2. Recompute the deterministic policy result under each response.
3. Calculate whether verdict, final action, approval route, case creation, or SAR filing could change.
4. Subtract a configured cost/latency penalty.
5. Select the highest-impact request only when at least one material decision can change.

This is a lightweight expected-value-of-information approximation; it does not need a learned model. Store the response branches and action deltas in the trace. If no request can change the decision, stop and explain that further evidence has low decision value.

### Counterfactual decision explanation

The dashboard may show one safe, policy-level counterfactual: “If the customer confirms the transaction, actions become X; if they deny it, actions become Y.” This is a scenario explanation, not advice to a customer and not a claim that changing immutable facts would erase risk. Only show branches actually computed by the policy engine.

## Agent state machine

Define a typed `InvestigationState` containing at least:

- Case trigger.
- Investigation plan.
- Graph evidence list.
- Evidence ledger and independence groups.
- Document evidence list.
- Similar prior cases.
- Candidate patterns.
- Positive and negative evidence.
- Probability history.
- Current verdict.
- Current pattern.
- Exposure and affected transaction IDs.
- Connected cards and device profiles.
- Evidence requests and responses.
- Initial actions.
- Final actions.
- SAR decision and draft.
- Stop decision.
- Tool-call count.
- Token usage.
- Start time and latency.
- Validation errors.
- Graph write receipt.
- Append-only evidence ledger and its final hash.
- Dataset manifest, memory manifest, query-bundle version, scoring/calibration version, policy version, prompt version, and code commit when available.
- Anchor timestamp, maximum admitted data timestamp, memory epoch, and version identifiers.
- Tool budget remaining and completed-node idempotency keys.

Use this workflow:

```text
load_case
  -> establish_temporal_cutoff_and_memory_epoch
  -> collect_case_context
  -> collect_card_baseline
  -> detect_candidate_patterns
  -> expand_shared_origins
  -> inspect_region_sequence_and_temporal_graph_features
  -> retrieve_similar_cases
  -> build_evidence_ledger
  -> assemble_grounded_context
  -> synthesize_assessment
  -> compute_probability
  -> apply_initial_policy
  -> evidence_needed?
       yes -> rank_requests_by_decision_impact -> request_and_simulate_evidence -> reassess -> apply_final_policy
       no  -> final_actions_equal_initial
  -> generate_sar_if_required
  -> evaluate_stop_condition
  -> construct_answer
  -> validate_answer
  -> write_case_to_graph
  -> read_back_graph_case
  -> export_json
```

Every node must be independently testable. Conditional edges must be explicit. Limit loops to prevent runaway investigations.

Use a durable local LangGraph checkpointer (SQLite is sufficient) keyed by `case_id + run_id`. Nodes that call TigerGraph or an LLM must be idempotent and cache successful normalized results. A resumed workflow must not duplicate evidence, graph writes, or model charges.

Set hard per-case budgets in configuration:

- Maximum twelve graph/MCP calls.
- Maximum two LLM assessment calls plus one structured-output repair call.
- Maximum one evidence-request cycle.
- Maximum two graph hops and bounded rows per graph expansion.
- Maximum wall-clock time, with a deterministic fallback answer path.

Parallelize independent read-only queries only after one sequential case works. Do not parallelize graph writes.

### Two-pass benchmark execution

To guarantee reproducibility and avoid cross-case contamination:

1. **Pass A — investigate:** freeze the historical-memory manifest and run all twenty cases against it. Validate each answer and save it as `provisional` without exposing other benchmark outputs to retrieval.
2. **Freeze:** compute a manifest hash over the twenty validated provisional answers and configuration versions.
3. **Pass B — commit:** write each frozen case to TigerGraph idempotently, read it back, set `written_to_graph`, revalidate, and export the final JSON.

Run the batch twice in opposite case order during final QA. The substantive outputs must match, allowing only latency, token counts, timestamps, and graph receipt metadata to differ.

## LLM responsibilities

The LLM may:

- Select from allowed investigation tools.
- Propose a bounded investigation plan.
- Summarize structured graph evidence.
- Compare the case with retrieved prior cases.
- Propose a fraud pattern and explain uncertainty.
- Draft the analyst summary.
- Draft a SAR narrative after deterministic policy decides that a SAR is required.
- Explain why actions follow the cited policy rules.

The LLM may not:

- Invent entity or transaction IDs.
- Calculate exposure without deterministic verification.
- Decide approval routes.
- Override R1-R10.
- Create a SAR when deterministic policy says not to file.
- Run unbounded graph traversals.
- Treat a risk score as a ground-truth label.
- Claim a case was written to the graph without a successful read-back.
- See future events, hidden benchmark outcomes, or other benchmark cases from the active memory epoch.
- Convert a shared common region/domain into a fraud ring without time-local coordination evidence.
- Treat retrieved prior cases as labels for the current case.

All LLM responses use strict structured output. On validation failure, send one repair request containing only the schema errors and the prior structured response. If repair fails, construct a deterministic template summary from the evidence ledger and policy trace; do not rerun graph queries.

## Exact final answer contract

Generate one file per benchmark case at `cases/<case_id>.json`.

### Top-level fields

- `case_id`: source benchmark case ID.
- `case`: internal investigation record.
- `evidence_requests`: list of requested/simulated evidence.
- `next_best_actions`: initial and final recommendations.
- `sar`: report decision and narrative.
- `stop_reason`: why investigation ended.
- `tool_calls`: integer count.
- `tokens`: integer token total.
- `latency_s`: numeric wall-clock duration.

### `case` fields

- `status`: one of `open`, `closed_fraud`, `closed_legitimate`, `escalated`.
- `verdict`: one of `fraud`, `legitimate`, `uncertain`.
- `fraud_probability`: number from 0 through 1.
- `pattern`: one of `card_testing`, `card_not_present_fraud`, `card_not_present_new_device`, `out_of_region_use`, `account_takeover`, `undocumented`, `none`.
- `pattern_description`: required for `undocumented`; otherwise empty string.
- `affected_txn_ids`: list of source transaction IDs.
- `first_suspicious_txn_id`: source transaction ID or empty string.
- `connected_card_ids`: list of source card IDs.
- `connected_device_profiles`: list of device profile identifiers/labels.
- `exposure_usd`: verified numeric exposure.
- `evidence`: list of evidence objects.
- `similar_prior_cases`: list of closed-case IDs actually retrieved and used.
- `summary`: two to six sentences.
- `written_to_graph`: boolean based on real write/read-back.
- `graph_case_id`: graph ID or empty string.

### Evidence object fields

- `claim`: concise factual statement.
- `source`: one of `graph`, `document`, `customer`, `external`.
- `ref`: installed query, document section, or evidence-request ID.
- `entity_ids`: supporting dataset IDs.

### Evidence request fields

- `type`: one of `customer_validation`, `step_up_auth`, `analyst_info`.
- `asked_after_step`: integer.
- `assumed_response`: explicit simulated response.

### `next_best_actions` fields

- `initial`: list of action objects before requested evidence is received.
- `final`: list after evidence response.
- `what_changed`: explanation or exact string `nothing`.

Each action object contains:

- `action`: exact allowed policy identifier.
- `route`: `auto`, `L1`, or `L2`.
- `reason`: cite applicable policy rule numbers.

### `sar` fields

- `file`: boolean.
- `reason`: policy-grounded explanation.
- `narrative`: six to twelve sentences when filed; otherwise empty string.
- `subjects`: dataset IDs named in the narrative.
- `total_amount_usd`: verified suspicious amount or zero.
- `activity_dates`: first and last activity date in `YYYY-MM-DD`, or empty list.

## Cross-field validation rules

The answer validator must reject any answer that violates these rules:

1. `case_id` must exist in `case_pack.csv`.
2. Every transaction, card, customer, device, and prior-case ID must exist.
3. `fraud_probability` must be within 0 and 1.
4. Legitimate verdict requires empty affected transactions, zero exposure, and no SAR.
5. `undocumented` requires a non-empty pattern description.
6. All other patterns require an empty pattern description.
7. Exposure must equal the deterministic sum of affected transaction amounts within a currency-rounding tolerance.
8. First suspicious transaction must appear in affected transactions unless empty.
9. Similar prior cases must have been returned by retrieval.
10. Every action must use the correct approval route.
11. `FILE_REPORT` in final actions must exactly match `sar.file`.
12. A SAR requires `CREATE_CASE` in final actions.
13. A filed SAR requires a non-empty narrative, subjects, amount, and exactly two dates.
14. A non-filed SAR requires empty narrative, empty subjects, zero amount, and empty dates.
15. `BLOCK_ALL_CARDS` requires evidence satisfying R10.
16. If no evidence was requested, final actions must equal initial actions and `what_changed` must be `nothing`.
17. `written_to_graph` may be true only after successful write and read-back.
18. Summary length must remain between two and six sentences.
19. SAR narrative length must remain between six and twelve sentences when filed.
20. Every evidence claim must include a non-empty reference.
21. Every evidence reference must resolve to an internal evidence-ledger record or an allowed policy document section.
22. No ledger record may contain data newer than the case cutoff unless it is a labeled simulated response.
23. The stopping rule's two independent items must come from two distinct independence groups.
24. A shared-origin fraud claim requires time-local multi-card activity plus either fraud enrichment or a rare shared entity; raw global degree is insufficient.
25. Similar prior cases must exclude the current case, future-closed cases, and the active benchmark memory epoch.
26. A failed graph write must leave the answer valid but set `written_to_graph=false` and fail the submission gate until retried successfully.

## Dashboard specification

Build a functional Streamlit dashboard after the batch pipeline works.

### Required views

#### Case list

- Show all twenty cases.
- Show run status, verdict, probability, pattern, exposure, and validation status.
- Permit running or rerunning one case.
- Permit running all cases.

#### Investigation view

- Trigger and flagged transaction.
- Timeline of agent steps and tool calls.
- Positive and negative evidence separated clearly.
- Retrieved similar fraud and cleared cases.
- Probability history.
- Evidence ledger with independence groups and query/cutoff provenance.
- Time-window feature table and “why this is unusual for this card” robust baseline comparison.
- Graph subnetwork containing the current card, transactions, devices, regions, connected cards, and prior cases.

#### Decision view

- Initial actions with routes and policy citations.
- Evidence request and assumed response.
- Final actions and what changed.
- Stop reason.
- SAR preview when applicable.
- Computed response branches showing which evidence request could change the decision.

#### Output view

- Validated JSON preview.
- Graph write/read-back status.
- Tool calls, tokens, and latency.
- Download button for the case JSON.

The dashboard must remain usable when graph visualization fails; evidence tables and text are the fallback.

## Tests and quality gates

### Unit tests

Must cover:

- All policy rules R1-R10.
- Every action-to-route mapping.
- Case creation rule.
- SAR filing rule.
- Investigation stopping rules.
- Pattern detector boundaries.
- Probability bounds and monotonicity.
- Exposure calculation.
- Device-profile normalization.
- ID normalization.
- Pydantic answer schemas.
- All cross-field validation rules.
- Robust median/MAD baselines with zero-MAD handling.
- Shared-origin rarity and supernode caps.
- Evidence independence grouping.
- Decision-impact request selection.
- Structured-output deterministic fallback.

### Integration tests

Must cover:

- TigerGraph connection.
- Each installed query using a small known fixture.
- MCP session creation and at least one query invocation.
- End-to-end investigation of one fixture case.
- Case write followed by graph read-back.
- Batch runner recovery after one failed case.
- MCP-primary to installed-query fallback equivalence on normalized outputs.
- No-future-evidence enforcement for a historical fixture.
- Frozen-memory exclusion and batch-order invariance.

### Golden tests

Create at least three human-reviewed fixtures:

- Clear fraud.
- Clear legitimate false positive.
- Ambiguous case that requests evidence and changes actions.

Golden tests should validate structure and policy consistency without freezing free-form wording unnecessarily.

### Historical replay evaluation

Before touching the benchmark thresholds, replay historical closed cases using strict time cutoffs and leave-one-out retrieval.

- Run deterministic feature extraction/scoring on all eligible closed cases.
- Run the expensive LLM synthesis on a stratified sample only: clear fraud, clear legitimate, boundary probabilities, each known pattern, and high-exposure cases.
- Report discrimination, calibration, policy consistency, retrieval Recall@k/contrast coverage, average graph calls, latency, and validation failure rate.
- Compare `risk_score only`, `behaviour only`, and `behaviour + graph` ablations.
- Save results to `runs/evaluation/report.json` and a readable `runs/evaluation/report.md`.

This replay is a development harness, not proof of real-world performance. Closed cases may contain selection bias and the simulated evidence path is not observed ground truth.

### Submission validation gate

The final validation command must:

- Find exactly twenty JSON files.
- Confirm filenames match the twenty case IDs.
- Validate every Pydantic model.
- Run all cross-field rules.
- Verify all IDs against the dataset.
- Recompute every exposure.
- Verify SAR/action agreement.
- Verify routes.
- Verify graph write receipts or explicitly report failures.
- Produce a human-readable summary and a machine-readable validation report.
- Verify the benchmark memory manifest and two-pass freeze hash.
- Verify no case used a future event or another benchmark case as evidence.
- Verify an opposite-order rerun is substantively identical.
- Exit nonzero if any case fails.

## Observability and reproducibility

For each case, save a run trace under `runs/<case_id>/` containing:

- Configuration snapshot without secrets.
- Investigation-state checkpoints.
- Normalized tool inputs and outputs.
- Evidence package provided to the model.
- Model usage.
- Probability evolution.
- Policy decision trace.
- Validation report.
- Graph write receipt.

Do not rely on hidden chain-of-thought. Store concise decision reasons, evidence references, and deterministic policy traces.

Use stable seeds for simulations. Pin package versions. Record the model identifier used for final runs.

Version installed queries in their names or descriptions, for example `get_card_baseline_v1`, and record the exact version in every evidence record. Never silently replace a query used for frozen outputs; create a new version and rerun affected cases.

## Configuration contract

`.env.example` must contain placeholders for:

```text
TG_HOST=
TG_GRAPHNAME=HHGOAFraud
TG_USERNAME=
TG_PASSWORD=
TG_API_TOKEN=
TG_TGCLOUD=true
TG_MCP_ALLOWED_TOOLS=schema,query,discovery,utility
LLM_PROVIDER=
LLM_MODEL=
OPENAI_API_KEY=
GOOGLE_API_KEY=
DATA_DIR=./data/raw
RUNS_DIR=./runs
CASES_DIR=./cases
MEMORY_EPOCH=hhgoa_2026_benchmark_v1
MAX_GRAPH_CALLS_PER_CASE=12
MAX_LLM_CALLS_PER_CASE=3
```

Application startup must clearly report missing required variables without exposing secret values.

## Security and safety requirements

- Never commit `.env`, credentials, tokens, or source datasets.
- Use a read-only TigerGraph MCP tool subset for investigation wherever possible.
- Configure the MCP server with only the categories/tools the workflow needs; do not expose all available tools to the model. Enable tool-call logging without caller identity unless identity is explicitly required.
- Restrict graph writes to the case-writing function.
- Never expose arbitrary GSQL execution to the model in the final application.
- Bound traversal depth, result counts, and time windows.
- Redact credentials from logs.
- Validate all LLM-produced structures with Pydantic.
- Treat model output as untrusted until validated.
- Keep simulated external actions clearly labeled.
- Treat all source text, case notes, graph attributes, and retrieved documents as untrusted data. They cannot add instructions, expand tool permissions, or alter policy.
- Use a distinct service path/credential for the single case-write function where possible; the investigation workflow itself stays read-only.

## Implementation phases

### Phase 1 Foundation and data audit

Deliverables:

- Repository skeleton.
- Environment/config loading.
- Dependency file.
- Raw-data placement instructions.
- Data audit script and report.
- Finalized ID mapping.
- Answer Pydantic models.
- Initial validator tests.

Exit criteria:

- All four input files are recognized.
- All twenty flagged transactions and case IDs resolve.
- No unresolved card-ID derivation issue remains.
- Answer models can parse a complete fixture and reject an invalid fixture.

### Phase 2 Graph ingestion

Deliverables:

- TigerGraph schema.
- Prepared vertex/edge CSVs.
- Loading jobs.
- Closed-case and policy/typology vector preparation plus TigerGraph vector index.
- Idempotent ingestion command.
- Verification report containing counts and sampled traversals.

Exit criteria:

- Expected vertex/edge counts reconcile with prepared data.
- One card can be traversed to its transactions, devices, region, customer, and historical cases.
- One TigerGraph vector query retrieves a relevant closed case or policy chunk with its source ID.
- Re-running ingestion does not duplicate data.

### Phase 3 Investigation queries

Deliverables:

- Nine installed queries, including temporal graph features.
- Time-bounded WCC graph-algorithm wrapper/query and provenance output.
- Python normalizers.
- Integration tests.
- Bounded result schemas.

Exit criteria:

- Each query returns structured results for at least one fixture.
- Missing entities return useful errors rather than empty unexplained output.
- Exposure calculation matches local calculation.
- Every query respects `as_of_ts`, bounded row counts, and benchmark-memory exclusion.
- WCC is verified on a small known suspicious-component fixture.

### Phase 4 Deterministic analytics and policy

Deliverables:

- Pattern detectors.
- Probability engine.
- Policy engine.
- Approval routing.
- Stopping decisions.
- Robust baselines, temporal evaluation split, calibration report, evidence independence, and decision-impact selection.
- Complete unit tests.

Exit criteria:

- All R1-R10 tests pass.
- Fraud, legitimate, and uncertain fixtures produce appropriate decisions.
- No invalid action route can be constructed.
- Graph-feature ablation is compared against risk-score-only and behaviour-only baselines.
- Probability is either calibrated under the stated gates or explicitly documented as fallback confidence.

### Phase 5 Agent workflow

Deliverables:

- LangGraph state and nodes.
- TigerGraph MCP integration.
- Grounded GraphRAG context builder combining structural GSQL, WCC, TigerGraph vector memory, and policy evidence.
- Assessment and SAR prompts.
- Simulated evidence path.
- Per-case run trace.
- Durable checkpoints, evidence ledger, hard tool budgets, and deterministic fallback response.

Exit criteria:

- A full case runs end to end.
- Every claim in the output has evidence provenance.
- Loops are bounded.
- A failed model call can be retried without corrupting case state.
- Resuming a run does not duplicate model calls, ledger rows, or graph writes.

### Phase 6 Batch outputs

Deliverables:

- One-case runner.
- All-cases runner.
- Resume support.
- Twenty case files.
- Validation report.
- Case graph write/read-back receipts.
- Frozen historical-memory manifest and two-pass batch commit.

Exit criteria:

- Exactly twenty files pass the full validation gate.
- Batch reruns can skip already valid cases or intentionally overwrite them.
- Failure of one case does not discard completed valid cases.
- Opposite-order rerun is substantively identical.

### Phase 7 Dashboard and demo

Deliverables:

- Streamlit dashboard.
- Three curated demo cases.
- Graph/evidence view.
- Initial versus final action view.
- SAR view.
- Metrics and JSON export.
- Three-to-five-minute demo script.

Exit criteria:

- A new viewer can understand what triggered the case, what the graph found, why uncertainty changed, and why the final action follows policy.
- The demo can be run from a clean terminal using documented commands.

### Phase 8 Submission package

Deliverables:

- Final README.
- Architecture diagram.
- Twenty validated case files.
- Demo video.
- Technical blog post or finished draft.
- Social post draft.
- Submission checklist.

Exit criteria:

- A clean clone plus locally supplied data and credentials can reproduce the outputs.
- No secrets or giant raw files are tracked.
- All required links and artifacts exist.

## Time-boxed emergency schedule

The implementation agent should work in this order and must not polish later phases while an earlier gate is incomplete. Times below are engineering budgets, not calendar promises. Record actual time in `PROGRESS.md` and enforce the kill criteria.

### Block A Core setup

- Budget: 2-3 hours.
- Create skeleton and configuration.
- Place/link source data locally.
- Run audit.
- Finalize identifiers and Pydantic answer schema.
- Kill criterion: unresolved card-ID mapping stops graph design but not schema/validator/test scaffolding.

### Block B Graph

- Budget: 4-6 hours.
- Create schema.
- Prepare normalized loading files.
- Load core vertices/edges.
- Install and verify core queries.
- Use prepared CSV/loading jobs rather than row-by-row upserts. The transaction file is larger than the default 200 MB REST request limit; split prepared files into safe chunks or load through the Savanna data-loading workflow.
- Kill criterion: if advanced embeddings or broad community features are not operational in thirty minutes after core queries work, defer them. Do not defer the minimal TigerGraph closed-case/policy vector index or the bounded WCC requirement.

### Block C One perfect case

- Budget: 3-4 hours.
- Manually inspect one case.
- Execute queries.
- Create one fully valid answer.
- Write/read it from the graph.
- Use this as the golden end-to-end fixture.
- Include the evidence ledger, temporal cutoff, initial/final action branch, and deterministic fallback in this slice.

### Block D Automation

- Budget: 4-6 hours.
- Implement state machine.
- Add probability and policy logic.
- Add evidence simulation.
- Run three representative cases.
- Add historical replay for deterministic scoring first; LLM replay remains sampled.
- Kill criterion: if learned calibration cannot pass its gates within the block, freeze the documented rule-based mapping and continue.

### Block E Twenty cases

- Budget: 4-6 hours plus review.
- Run batch.
- Fix validation failures.
- Review outliers and every SAR decision.
- Freeze validated outputs.
- Execute Pass A/freeze/Pass B and the opposite-order invariance check.

### Block F Presentation

- Budget: 3-4 hours.
- Add dashboard around working pipeline.
- Record demo.
- Complete README, architecture, blog, and submission package.
- Demonstrate three cases: a graph-confirmed fraud ring, a legitimate false positive, and an uncertain case where one evidence response changes the action.

If time becomes critical, reduce UI polish and regulatory-document breadth. Never remove validation, policy enforcement, the twenty outputs, or graph case memory.

### Go/no-go gates

- Do not start the dashboard until one case passes end to end and three representative cases pass policy validation.
- Do not run all twenty until the one-case resume path and write/read-back are verified.
- Do not record the demo until the twenty-file validator exits zero.
- Do not add embeddings, community algorithms, or another agent framework after Block D begins.
- Reserve the final two hours before submission for rerun, artifact verification, upload, and contingency only.

## Manual review protocol for the twenty answers

Even after automated validation, review every case in a compact table containing:

- Case ID.
- Trigger.
- Verdict and probability.
- Pattern.
- Affected transaction count.
- Exposure.
- Connected cards.
- Initial actions.
- Evidence request.
- Final actions.
- SAR decision.
- Similar prior cases.
- Stop reason.
- Validator status.

Flag for deeper review:

- Probabilities between 0.40 and 0.60.
- Any `undocumented` pattern.
- Any `BLOCK_ALL_CARDS` action.
- Any SAR filing.
- Any exposure above USD 1,000.
- Cases with no similar prior cases.
- Cases with unusually high tool or token usage.
- Cases whose final action did not change after contradictory simulated evidence.

## Failure modes and mitigations

| Failure mode | Earliest detection | Required mitigation |
|---|---|---|
| Incorrect card/device entity resolution | Audit cardinality and collision report | Do not create shared edges for weak signatures; keep the signal transaction-local |
| Future-data leakage | Temporal fixture tests and ledger cutoff check | Reject the evidence and fail the run |
| Common email/region treated as a ring | High global degree with low rarity | Require time-local coordination and fraud enrichment; cap contribution |
| Risk score copied into verdict | Ablation/contribution report | Cap risk-score influence and compare behaviour/graph evidence |
| Case retrieval confirmation bias | Retrieved outcomes lack diversity | Force fraud/cleared contrast when candidates exist |
| Batch order changes answers | Opposite-order replay | Freeze memory epoch and use two-pass commit |
| Vector service temporarily unavailable during development | Startup capability test | Use deterministic structured/TF-IDF reranker to continue interface work, then restore and verify TigerGraph vector retrieval before Gate 2 can pass |
| MCP unavailable or bloated tool context | MCP smoke test and served-tool inventory | Use restricted tool subset; switch normalized reads to tested installed-query fallback |
| LLM emits invalid JSON | Pydantic validation | One repair attempt, then deterministic template fallback |
| Agent loops or repeats expensive calls | Tool budget/idempotency trace | Stop at budget and complete via deterministic path |
| Graph load exceeds request limits | Preflight file-size check | Prepared loading jobs and chunks below endpoint limit/Savanna loader |
| Probability cannot be calibrated | Held-out calibration report | Disclose and use conservative rule-based confidence mapping |
| Graph write succeeds partially | Read-back mismatch | Keep output provisional and retry idempotent write before submission |

## Research source and reuse register

This section records what was actually learned from external work and prevents a future implementation agent from copying entire repositories blindly.

### Adopt directly as design guidance

- [TigerGraph MCP](https://github.com/tigergraph/tigergraph-mcp): use the official server, narrow the served tools, prefer read-only investigation access, and enable tool-call logs. It exposes a large tool surface by default, so the plan intentionally limits it.
- [TigerGraph GraphRAG](https://github.com/tigergraph/graphrag): adopt pre-approved queries, hybrid graph/vector retrieval, result caps, and graceful operation when vector search is unavailable. Do not deploy the whole service on the critical path.
- [TigerGraph GSQL 4.2 reference](https://docs.tigergraph.com/gsql-ref/4.2/querying/): use installed bounded procedures for traversals and computation.
- [TigerGraph Graph Data Science algorithms](https://github.com/tigergraph/gsql-graph-algorithms): selectively use WCC/cycle/neighbor algorithms only when they answer a defined investigation question.
- [TigerGraph cryptocurrency fraud example](https://github.com/TigerGraph-DevLabs/detect-cryptocurrency-fraud): FastRP is a plausible stretch experiment; node2vec is not deadline-compatible.
- [Neo4j IEEE-CIS graph fraud reference](https://github.com/neo4j-field/finance-ieee-cis-fraud): reuse the schema insight that transactions connect cards, devices, emails, and addresses, plus interpretable graph features such as degree and community size. Reimplement in TigerGraph; do not introduce Neo4j.
- [AML Fraud Network Agent](https://github.com/RahafAba/aml-fraud-agent): adopt explicit routing, schema-aware read-only query access, and evaluation of routing/query correctness. Do not add its SQL/Neo4j stack.
- [MongoDB AML/Fraud agentic system](https://github.com/mongodb-industry-solutions/fsi-aml-fraud-detection/blob/main/docs/AGENTIC_SYSTEM_OVERVIEW.md): adopt a visible investigation pipeline and human-review state, not its storage stack.
- [LangGraph interrupts and persistence](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/): use checkpointed state and resumable human/evidence pauses; keep side effects idempotent because interrupted nodes can re-execute.
- [Case-based reasoning for fraud alerts](https://arxiv.org/abs/1907.03334): supports retrieving resolved cases to assist experts; this plan improves it with outcome contrast and causal availability.
- [Robust anomaly detection](https://wires.onlinelibrary.wiley.com/doi/10.1002/widm.1236): motivates median/MAD baselines instead of outlier-sensitive mean/standard deviation alone.
- [Classifier calibration for credit risk](https://arxiv.org/abs/1710.08901): motivates time-aware recalibration and Brier-score evaluation.
- [Leakage-safe temporal graph features](https://arxiv.org/abs/2603.06632): reinforces causal graph snapshots, temporal splits, operational precision-at-k, and calibration checks.
- [FACE counterfactual explanations](https://arxiv.org/abs/1909.09369) and [recourse as interventions](https://arxiv.org/abs/2002.06278): justify showing only feasible policy response branches, not speculative advice or impossible feature changes.

### Reuse from team repositories

- From the user's Zoho automation work: reuse plan-first delivery, deterministic validation, approval boundaries, run state, audit traces, and resumability patterns.
- From the user's Streamlit projects: reuse only UI composition and deployment patterns after the batch pipeline works.
- From ANK's repositories: reuse small licensed runtime conventions or the MIT-licensed `llm-core` only if they reduce implementation time and remain local. Do not make the project depend on an unlicensed repository or pull in an entire general agent framework.

### Explicitly rejected for this deadline

- A GNN as the primary detector. Current IEEE-CIS work shows graph models can help, but the implementation, leakage control, training, and explanation burden is too high for the remaining time.
- Multi-agent investigator swarms. They multiply tool context, failure modes, latency, and reconciliation work without improving the deterministic answer contract.
- Unrestricted natural-language-to-GSQL. Curated installed queries are more reliable and traceable.
- A separate vector database. TigerGraph vector search or a small local fallback is sufficient.
- Real-time Kafka/Redis/FastAPI infrastructure. The judged deliverable is a reproducible twenty-case investigation batch and demonstration.
- Blind copying of “top” GitHub repositories. Popularity is not evidence of fit, licensing, leakage safety, or deadline feasibility.

## Definition of Done

The project is complete only when every item below is true:

- [ ] Data audit completed and saved.
- [ ] All twenty benchmark IDs resolve to source data.
- [ ] TigerGraph schema and loading jobs are versioned locally.
- [ ] Core graph data is loaded and verified.
- [ ] TigerGraph vector index contains closed-case and policy/typology memory and is used in the final runtime.
- [ ] All required GSQL queries are installed and tested.
- [ ] Time-bounded WCC runs as a TigerGraph graph algorithm and contributes evidence to at least one qualifying investigation/demo case.
- [ ] TigerGraph MCP is connected with a restricted tool set.
- [ ] GraphRAG context combines connected graph evidence, TigerGraph vector retrieval, and relevant policy context with claim-level references.
- [ ] Pattern detectors and probability engine are tested.
- [ ] Historical replay uses a strict temporal split and produces an ablation/calibration report.
- [ ] Every runtime evidence item passes the temporal-cutoff check and has ledger provenance.
- [ ] Prior-case retrieval returns contrastive outcomes when available and excludes the active benchmark epoch.
- [ ] Decision-impact logic justifies every evidence request.
- [ ] Policy R1-R10 is implemented deterministically.
- [ ] Approval routes cannot be overridden by the LLM.
- [ ] Evidence simulation is explicit and reproducible.
- [ ] One golden case works end to end before batch execution.
- [ ] All twenty answers exist in `cases/`.
- [ ] All twenty answers pass schema and cross-field validation.
- [ ] The two-pass freeze manifest exists and an opposite-order run is substantively invariant.
- [ ] Every output ID exists in the dataset.
- [ ] Every exposure amount has been recomputed.
- [ ] Every SAR agrees with final actions and policy.
- [ ] Every final case is written to TigerGraph and read back successfully.
- [ ] Dashboard demonstrates investigation, uncertainty, and changing actions.
- [ ] Three-to-five-minute demo is recorded.
- [ ] README and architecture documentation are complete.
- [ ] Blog post is complete or ready to publish.
- [ ] Social post draft is ready.
- [ ] Repository contains no secrets or raw dataset files.
- [ ] Git history contains atomic sub-step commits and a review packet for every completed master gate.
- [ ] Submission checklist has been reviewed by a human.

## Rules for any coding agent executing this plan

1. Read the entire plan before editing files.
2. Inspect existing work before creating replacements.
3. Preserve user changes and never destroy working code to simplify implementation.
4. Work gate by gate and run the relevant tests at every exit condition.
5. Update checkboxes and maintain a short `PROGRESS.md` containing completed work, current blocker, next action, and verification commands.
6. Do not claim completion based only on code generation. Run commands and verify outputs.
7. Do not invent dataset mappings, entity IDs, query results, or successful graph writes.
8. Use deterministic code for policy, routes, exposure, validation, and stopping thresholds.
9. Keep LLM prompts concise and grounded in structured evidence.
10. Do not add infrastructure unrelated to the Definition of Done.
11. Prefer a small working vertical slice before implementing breadth.
12. If a phase is blocked by credentials or missing data, complete all safe local work first and report the exact missing input.
13. Never place secrets in source files, logs, tests, screenshots, or documentation.
14. Keep all project-specific requirements and generated documentation inside this directory.
15. Before handing work back, state exactly what was built, what was verified, what remains, and the next command to run.
16. Follow the mandatory Git discipline: atomic commit after every meaningful sub-step, progress update in the same commit, no history rewriting, and push passing gates.
17. Stop after each master gate and return its review packet. Do not begin the next gate until the user or primary engineer approves continuation.
18. The official required TigerGraph components are not optional: graph and vector storage/retrieval, GSQL, a TigerGraph graph algorithm, TigerGraph MCP, GraphRAG, and a user interface must all be implemented and demonstrated.
19. Additional libraries may support preprocessing, orchestration, testing, or presentation, but they may not replace TigerGraph in any required role.

## First prompt for an implementation agent

Use the following prompt when handing this directory to Opus, Codex Cloud, or another coding agent:

```text
Read HHGOA_FRAUD_INVESTIGATOR_BUILD_PLAN.md completely, including the authority order, official-component matrix, judging matrix, master gates, temporal/leakage contract, Git discipline, failure modes, and research register. Treat it as the implementation contract. Inspect `git status`, recent commits, and PROGRESS.md before editing. Continue from the first incomplete master gate and keep all project files inside this directory. Do not redesign the product or add out-of-scope infrastructure. Complete one meaningful sub-step at a time, run its relevant verification, update PROGRESS.md/checklists, inspect the staged diff, and create an atomic descriptive commit. Never amend, squash, reset, rebase, or force-push shared history. Never invent dataset identifiers, calibration quality, graph results, or successful writes. Deterministic code must control temporal cutoffs, evidence provenance, probability features, policy R1-R10, approval routing, exposure, stopping rules, and output validation. The final implementation must use TigerGraph for graph and vector storage/retrieval, versioned GSQL, at least time-bounded WCC as a TigerGraph graph algorithm, TigerGraph MCP as the agent-facing graph path, GraphRAG grounded in graph/vector/policy evidence, and a working UI. Additional tools may support but not replace these required components. Prioritize one perfect vertical slice, then the frozen-memory two-pass twenty-case batch, then UI polish. Defer non-required embeddings, broad community analysis, and extra frameworks when they threaten the batch. Stop after the current master gate and return the required review packet with commit hashes and actual test results; do not start the next gate until approved. If credentials or source data are missing, finish all independent work within the current gate and report the exact blocker and next command.
```

## Final product statement

FraudGraph Investigator turns an uncertain fraud alert into a traceable, policy-compliant decision. It uses TigerGraph to discover behavioural and network evidence, retrieves prior case memory, requests additional evidence when necessary, distinguishes fraud from false positives, records both initial and final recommendations, produces a SAR only when required, and stores the completed case so the next investigation benefits from it.

That is the product. Everything implemented must directly support that outcome.
