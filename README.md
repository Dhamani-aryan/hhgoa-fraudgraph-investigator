# FraudGraph Investigator

FraudGraph Investigator is the HHGOA TigerGraph Agentic Fraud Investigation submission project. It will investigate the twenty supplied benchmark cases, gather graph and case-memory evidence, handle uncertainty, recommend policy-controlled next actions, create SARs when required, and write completed cases back to TigerGraph.

The authoritative engineering contract is [HHGOA_FRAUD_INVESTIGATOR_BUILD_PLAN.md](HHGOA_FRAUD_INVESTIGATOR_BUILD_PLAN.md). Every coding agent must read it completely and execute its master gates in order.

## Current status

Gate 0 (repository, brief, and data contract) is complete and awaiting review.
The dataset is audited, the card identifier mapping is proven against 14,975
labelled links, and the answer contract is executable with 119 passing tests.

Gate 1 (TigerGraph graph and vector foundation) is blocked only on TigerGraph
credentials. See [PROGRESS.md](PROGRESS.md).

## Getting started

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows
cp .env.example .env                              # then fill the TG_* values
python scripts/bootstrap.py
```

Place the four supplied files and the dataset README in `data/raw/`; see
[data/README.md](data/README.md). They are git-ignored and never committed.

```bash
python scripts/prove_card_mapping.py  # prove the derived card_id
python scripts/run_data_audit.py      # write runs/data_audit.json
python scripts/validate_all_cases.py  # the submission validation gate
python -m pytest tests/ -q
```

## Required platform path

The final submission must visibly use:

- TigerGraph Savanna for graph and vector storage/retrieval.
- Versioned GSQL and at least one TigerGraph graph algorithm.
- TigerGraph MCP as the agent-facing graph interface.
- GraphRAG grounded in graph, vector, and policy evidence.
- A working analyst interface.
- Exactly twenty validated benchmark answer files written back to the graph.

## Data and secrets

The supplied dataset and credentials are local-only and must never be committed. See `.gitignore` and the plan's security requirements.

## Deadline

24 September 2026 at 11:59 PM IST. One team submission; no resubmissions.

