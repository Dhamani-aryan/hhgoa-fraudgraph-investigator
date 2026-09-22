"""Install the versioned GSQL queries in graph/queries/.

Query names carry their version (``find_similar_closed_cases_v1``) so a frozen
run can record exactly which query produced its evidence, and a later change
becomes a new version rather than silently replacing the old one.

    .venv/Scripts/python scripts/install_queries.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph.client import (  # noqa: E402
    TigerGraphConfigError,
    connect,
    load_config,
    redact,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUERIES_DIR = PROJECT_ROOT / "graph" / "queries"
REPORT_PATH = PROJECT_ROOT / "runs" / "query_install.json"

GLOBAL_SCOPE = "global"
TEMPLATE_GRAPH_NAME = "HHGOAFraud"

FAILURE_MARKERS = (
    "semantic check fails",
    "syntax error",
    "failed to create",
    "not using any graphs",
)


def render(path: Path, graphname: str) -> str:
    text = path.read_text(encoding="utf-8")
    if graphname != TEMPLATE_GRAPH_NAME:
        text = re.sub(rf"\b{TEMPLATE_GRAPH_NAME}\b", graphname, text)
    return text


def query_name(text: str) -> str:
    match = re.search(r"CREATE\s+QUERY\s+(\w+)", text)
    if not match:
        raise ValueError("file does not declare a query name")
    return match.group(1)


def main() -> int:
    try:
        config = load_config()
        connection = connect(config)
    except TigerGraphConfigError as error:
        print(f"FAILED: {error}")
        return 1

    graphname = config.graphname
    # A multi-line statement loses the graph context unless USE GRAPH leads it.
    use = f"USE GRAPH {graphname}\n"

    files = sorted(QUERIES_DIR.glob("*.gsql"))
    print(f"installing {len(files)} queries into {graphname}\n")

    installed, failures = [], []
    for path in files:
        text = render(path, graphname)
        name = query_name(text)
        print(f"  {name} ...", end=" ", flush=True)

        # Drop first so a redefinition replaces the old body rather than
        # failing on the name.
        try:
            connection.gsql(f"{use}DROP QUERY {name}", graphname=GLOBAL_SCOPE)
        except Exception:  # noqa: BLE001 - absent is the normal case
            pass

        created = str(connection.gsql(use + text, graphname=GLOBAL_SCOPE))
        if any(marker in created.lower() for marker in FAILURE_MARKERS):
            print("FAILED")
            print(f"      {redact(created, config).strip()[:400]}")
            failures.append(name)
            continue

        result = str(connection.gsql(f"{use}INSTALL QUERY {name}", graphname=GLOBAL_SCOPE))
        if "successfully" not in result.lower() and "install" not in result.lower():
            print("INSTALL FAILED")
            print(f"      {redact(result, config).strip()[:400]}")
            failures.append(name)
            continue

        print("installed")
        installed.append(name)

    report = {
        "graphname": graphname,
        "installed": installed,
        "failures": failures,
        "ok": not failures,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nwrote {REPORT_PATH}")

    if failures:
        print(f"FAILED: {failures}")
        return 1
    print(f"Result: {len(installed)} queries installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
