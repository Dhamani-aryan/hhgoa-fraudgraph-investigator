# FraudGraph Investigator

FraudGraph Investigator is the HHGOA TigerGraph Agentic Fraud Investigation submission project. It will investigate the twenty supplied benchmark cases, gather graph and case-memory evidence, handle uncertainty, recommend policy-controlled next actions, create SARs when required, and write completed cases back to TigerGraph.

The authoritative engineering contract is [HHGOA_FRAUD_INVESTIGATOR_BUILD_PLAN.md](HHGOA_FRAUD_INVESTIGATOR_BUILD_PLAN.md). Every coding agent must read it completely and execute its master gates in order.

## Current status

Planning and challenge-alignment review are complete. Implementation has not started. The next action is Gate 0: repository, brief, and data contract.

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

