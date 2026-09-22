"""Install the loading jobs and load the prepared files into TigerGraph.

Idempotent: TigerGraph loading upserts on the primary id, so rerunning replaces
the same vertices and edges rather than adding duplicates.

    .venv/Scripts/python scripts/prepare_graph_files.py
    .venv/Scripts/python scripts/load_graph.py
    .venv/Scripts/python scripts/load_graph.py --only transactions edge_made
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph.client import (  # noqa: E402
    TigerGraphConfigError,
    connect,
    load_config,
    redact,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREPARED = PROJECT_ROOT / "data" / "prepared"
JOBS_PATH = PROJECT_ROOT / "graph" / "loading_jobs.gsql"
REPORT_PATH = PROJECT_ROOT / "runs" / "graph_load.json"

GLOBAL_SCOPE = "global"
TEMPLATE_GRAPH_NAME = "HHGOAFraud"

#: pyTigerGraph's own cap on a single upload. Every prepared file is smaller,
#: but the value is stated rather than inherited so a future larger file fails
#: loudly here instead of being truncated.
SIZE_LIMIT_BYTES = 128_000_000

#: (job name, prepared file). Vertices load before the edges that reference
#: them, and vectors load last onto vertices that already exist.
LOAD_ORDER: tuple[tuple[str, str], ...] = (
    ("load_cardholders", "cardholders.csv"),
    ("load_payment_cards", "payment_cards.csv"),
    ("load_transactions", "transactions.csv"),
    ("load_device_profiles", "device_profiles.csv"),
    ("load_email_domains", "email_domains.csv"),
    ("load_billing_regions", "billing_regions.csv"),
    ("load_closed_cases", "closed_cases.csv"),
    ("load_policy_chunks", "policy_chunks.csv"),
    ("load_edge_owns", "edge_owns.csv"),
    ("load_edge_made", "edge_made.csv"),
    ("load_edge_from_device", "edge_from_device.csv"),
    ("load_edge_purchaser_email", "edge_purchaser_email.csv"),
    ("load_edge_recipient_email", "edge_recipient_email.csv"),
    ("load_edge_billed_in", "edge_billed_in.csv"),
    ("load_edge_next", "edge_next.csv"),
    ("load_edge_case_involves", "edge_case_involves.csv"),
    ("load_edge_case_on_card", "edge_case_on_card.csv"),
    ("load_edge_case_connected_to", "edge_case_connected_to.csv"),
)

#: (prepared file, vertex type, vector attribute). These do not go through a
#: loading job; see the note at the end of graph/loading_jobs.gsql.
VECTOR_LOADS: tuple[tuple[str, str, str], ...] = (
    ("closed_case_embeddings.csv", "ClosedCase", "memory_embedding"),
    ("policy_chunk_embeddings.csv", "PolicyChunk", "policy_embedding"),
)

#: Vertices per upsert request. Each carries a 1536-float vector, so a larger
#: batch makes the request body big enough to be refused.
VECTOR_BATCH_SIZE = 250

FAILURE_MARKERS = (
    "semantic check fails",
    "failed to create",
    "could not be created",
    "not using any graphs",
)


def render_jobs(graphname: str) -> str:
    text = JOBS_PATH.read_text(encoding="utf-8")
    if graphname != TEMPLATE_GRAPH_NAME:
        text = re.sub(rf"\b{TEMPLATE_GRAPH_NAME}\b", graphname, text)
    return text


def split_jobs(text: str) -> list[tuple[str, str]]:
    """Split the file into (job name, statement) pairs.

    Each job body contains semicolons, so the file is split on the CREATE
    LOADING JOB boundaries rather than on ';'.
    """
    without_comments = re.sub(r"//.*", "", text)
    parts = re.split(r"(?=CREATE LOADING JOB\s)", without_comments)
    jobs = []
    for part in parts:
        part = part.strip()
        if not part.startswith("CREATE LOADING JOB"):
            continue
        name = part.split()[3]
        jobs.append((name, part))
    return jobs


def install_jobs(connection, config, graphname: str) -> list[str]:
    """Define every loading job, replacing any left from an earlier run."""
    jobs = split_jobs(render_jobs(graphname))
    print(f"installing {len(jobs)} loading jobs ...")
    # The graphname argument does not carry the graph context into a multi-line
    # statement, so USE GRAPH is prepended explicitly. Without it every
    # CREATE LOADING JOB returns "Currently not using any graphs".
    use = f"USE GRAPH {graphname}\n"
    for name, statement in jobs:
        # A loading job outlives the data it loaded, so drop before redefining.
        try:
            connection.gsql(f"{use}DROP JOB {name}", graphname=GLOBAL_SCOPE)
        except Exception:  # noqa: BLE001 - absent is the normal case
            pass
        result = str(connection.gsql(use + statement, graphname=GLOBAL_SCOPE)).lower()
        if any(marker in result for marker in FAILURE_MARKERS):
            raise TigerGraphConfigError(
                f"could not create loading job {name}: {redact(result, config)}"
            )
    return [name for name, _ in jobs]


def upsert_vectors(connection, path: Path, vertex_type: str, attribute: str) -> int:
    """Load a prepared embedding file through the REST upsert path.

    The file is "|" separated with the vector as a comma-separated list in the
    second column. Batched because each row carries 1536 floats.
    """
    import csv

    total = 0
    batch: list[tuple[str, dict]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="|")
        next(reader, None)  # header
        for row in reader:
            if len(row) < 2:
                continue
            vertex_id = row[0]
            vector = [float(value) for value in row[1].split(",")]
            batch.append((vertex_id, {attribute: vector}))
            if len(batch) >= VECTOR_BATCH_SIZE:
                connection.upsertVertices(vertex_type, batch)
                total += len(batch)
                batch = []
    if batch:
        connection.upsertVertices(vertex_type, batch)
        total += len(batch)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help="load only these prepared files (without the .csv), for a retry",
    )
    parser.add_argument(
        "--skip-install", action="store_true", help="reuse the loading jobs already defined"
    )
    args = parser.parse_args()

    try:
        config = load_config()
        connection = connect(config)
    except TigerGraphConfigError as error:
        print(f"FAILED: {error}")
        return 1

    graphname = config.graphname
    print(f"loading into {graphname} at {config.host}\n")

    if not args.skip_install:
        try:
            install_jobs(connection, config, graphname)
        except TigerGraphConfigError as error:
            print(f"FAILED: {error}")
            return 1
        print()

    selected = set(args.only) if args.only else None
    results = []
    failures = []

    for job_name, filename in LOAD_ORDER:
        stem = filename.removesuffix(".csv")
        if selected is not None and stem not in selected:
            continue
        path = PREPARED / filename
        if not path.exists():
            print(f"  {stem:30s} MISSING: run scripts/prepare_graph_files.py first")
            failures.append(stem)
            continue

        size = path.stat().st_size
        if size > SIZE_LIMIT_BYTES:
            print(f"  {stem:30s} TOO LARGE: {size / 1e6:.1f} MB exceeds the upload limit")
            failures.append(stem)
            continue

        started = time.time()
        print(f"  {stem:30s} {size / 1e6:>7.1f} MB ...", end=" ", flush=True)
        try:
            outcome = connection.runLoadingJobWithFile(
                str(path), "f", job_name, sizeLimit=SIZE_LIMIT_BYTES
            )
        except Exception as error:  # noqa: BLE001
            print(f"FAILED: {redact(str(error), config)[:160]}")
            failures.append(stem)
            continue

        elapsed = time.time() - started
        accepted, rejected = _counts_from(outcome)
        print(f"accepted {accepted:,} rejected {rejected:,} in {elapsed:.0f}s")
        results.append(
            {
                "job": job_name,
                "file": filename,
                "bytes": size,
                "accepted": accepted,
                "rejected": rejected,
                "seconds": round(elapsed, 1),
            }
        )
        if rejected:
            failures.append(f"{stem} ({rejected:,} rejected)")

    vector_results = []
    if selected is None or any(
        filename.removesuffix(".csv") in selected for filename, _, _ in VECTOR_LOADS
    ):
        print("")
        print("vector attributes (REST upsert, not a loading job):")
        for filename, vertex_type, attribute in VECTOR_LOADS:
            stem = filename.removesuffix(".csv")
            if selected is not None and stem not in selected:
                continue
            path = PREPARED / filename
            if not path.exists():
                print(f"  {stem:30s} MISSING")
                failures.append(stem)
                continue
            started = time.time()
            print(f"  {stem:30s} ...", end=" ", flush=True)
            try:
                count = upsert_vectors(connection, path, vertex_type, attribute)
            except Exception as error:  # noqa: BLE001
                print(f"FAILED: {redact(str(error), config)[:160]}")
                failures.append(stem)
                continue
            elapsed = time.time() - started
            print(f"upserted {count:,} in {elapsed:.0f}s")
            vector_results.append(
                {
                    "file": filename,
                    "vertex_type": vertex_type,
                    "attribute": attribute,
                    "upserted": count,
                    "seconds": round(elapsed, 1),
                }
            )

    report = {
        "graphname": graphname,
        "loads": results,
        "vector_loads": vector_results,
        "failures": failures,
        "ok": not failures,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {REPORT_PATH}")

    if failures:
        print(f"FAILED: {failures}")
        return 1
    print("Result: every prepared file loaded with no rejected lines.")
    return 0


def _counts_from(outcome) -> tuple[int, int]:
    """Pull accepted and rejected object counts out of a loading result.

    The counts live at statistics.parsingStatistics.objectLevel, split by
    vertex, edge and embedding. Reading statistics directly returns nothing,
    which silently looks like a load of zero rows.

    HEADER="true" still counts the header as one invalidAttribute line, so a
    single invalid attribute on a file whose valid objects match its row count
    is the header and not a data problem.
    """
    accepted = rejected = 0
    entries = outcome if isinstance(outcome, list) else [outcome]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        parsing = entry.get("statistics", {}).get("parsingStatistics", {})
        object_level = parsing.get("objectLevel", {})
        for kind in ("vertex", "edge", "embedding"):
            for statistic in object_level.get(kind, []) or []:
                accepted += statistic.get("validObject", 0) or 0
                rejected += statistic.get("invalidPrimaryId", 0) or 0
                rejected += statistic.get("invalidVertexType", 0) or 0
        file_level = parsing.get("fileLevel", {})
        rejected += file_level.get("rejectLine", 0) or 0
        rejected += file_level.get("notEnoughToken", 0) or 0
    return accepted, rejected


if __name__ == "__main__":
    sys.exit(main())
