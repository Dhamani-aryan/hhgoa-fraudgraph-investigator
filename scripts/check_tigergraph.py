"""Confirm the TigerGraph workspace is reachable and usable.

The first Gate 1 step. Read-only apart from creating the graph when asked, and
it never prints a credential.

Run it as soon as .env carries the workspace endpoint and secret:

    .venv/Scripts/python scripts/check_tigergraph.py

Add --create-graph to create the graph named by TG_GRAPHNAME if it does not
exist yet. Nothing else in this script writes.
"""

from __future__ import annotations

import argparse
import json
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
REPORT_PATH = PROJECT_ROOT / "runs" / "tigergraph_connection.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--create-graph",
        action="store_true",
        help="create the graph named by TG_GRAPHNAME if it does not exist",
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except TigerGraphConfigError as error:
        print(f"FAILED: {error}")
        return 1

    print("TigerGraph connection check")
    print(f"  target: {config.describe()}")
    print()

    try:
        connection = connect(config)
    except TigerGraphConfigError as error:
        print(f"FAILED: {error}")
        print()
        print("Common causes:")
        print("  - the workspace is stopped; start it in Savanna and retry")
        print("  - TG_HOST is not the workspace endpoint, or carries a path")
        print("  - the secret was regenerated, so the old value no longer works")
        return 1

    report: dict[str, object] = {
        "host": config.host,
        "graphname": config.graphname,
        "tg_cloud": config.tg_cloud,
        "authenticated": True,
    }

    try:
        version = connection.getVer()
        report["server_version"] = version
        print(f"  authenticated, server version {version}")
    except Exception as error:  # noqa: BLE001
        print(f"  authenticated, but version lookup failed: {redact(str(error), config)}")
        report["server_version"] = None

    try:
        existing = connection.gsql("LS")
        graph_present = config.graphname in str(existing)
    except Exception as error:  # noqa: BLE001
        print(f"FAILED: could not list the catalog: {redact(str(error), config)}")
        return 1

    report["graph_exists"] = graph_present
    print(f"  graph {config.graphname!r} exists: {graph_present}")

    if not graph_present and args.create_graph:
        print(f"  creating graph {config.graphname!r} ...")
        try:
            result = connection.gsql(f"CREATE GRAPH {config.graphname}()")
        except Exception as error:  # noqa: BLE001
            print(f"FAILED: could not create the graph: {redact(str(error), config)}")
            return 1
        print(f"    {str(result).strip().splitlines()[-1] if result else 'done'}")
        report["graph_created"] = True
        report["graph_exists"] = True
    elif not graph_present:
        print("  rerun with --create-graph to create it")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {REPORT_PATH}")

    if not report["graph_exists"]:
        print("Result: connected, but the graph does not exist yet.")
        return 1
    print("Result: connected and the graph is present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
