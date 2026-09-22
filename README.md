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

Python 3.11 or newer. Every command below uses the virtual environment's
interpreter explicitly, so nothing depends on which `python` is on PATH or on
whether the environment is activated.

Create the environment:

```bash
python -m venv .venv
```

Install. Use the pinned lock to reproduce the recorded results exactly:

```bash
.venv/Scripts/python -m pip install -r requirements.lock.txt
```

```bash
.venv/Scripts/python -m pip install -e . --no-deps
```

Or resolve fresh from `pyproject.toml`, which may pick up newer versions:

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```

On macOS or Linux the interpreter is `.venv/bin/python` instead of
`.venv/Scripts/python`; `requirements.lock.txt` is Windows-specific, so resolve
from `pyproject.toml` there and record a separate lock.

Configure. Copy the template and fill the `TG_*` values locally; `.env` is
git-ignored and must never be committed:

```bash
cp .env.example .env
```

Place the four supplied files and the dataset README in `data/raw/`; see
[data/README.md](data/README.md). They are git-ignored and never committed.

Check the environment and the dataset. This reports any missing `TG_*`
variable by name without printing its value:

```bash
.venv/Scripts/python scripts/bootstrap.py
```

## Verify

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

`validate_all_cases.py` is the submission gate. It exits non-zero until all
twenty answers exist, pass every rule, and each carries a confirmed TigerGraph
write and read-back receipt.

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

