"""Prove the Gate 1 exit criteria against the live graph.

Three things must hold, and each is checked against the Gate 0 audit rather
than against itself:

1. Loaded counts reconcile with the prepared files and the audit.
2. One card traverses to its transactions, cardholder, device, region and
   prior cases.
3. One semantic query returns a relevant prior case or policy chunk from
   TigerGraph vector search.

``--reload-check`` additionally reloads a file and confirms the counts do not
move, which is what idempotence means here.

    .venv/Scripts/python scripts/verify_graph.py
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
from retrieval.embeddings import embed  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "runs" / "graph_verification.json"

#: Counts the Gate 0 audit established. The graph must match them exactly.
EXPECTED_VERTEX_COUNTS = {
    "Cardholder": 13553,
    "PaymentCard": 14317,
    "Transaction": 590742,
    "DeviceProfile": 9706,
    "EmailDomain": 60,
    "BillingRegion": 332,
    "ClosedCase": 5565,
    "PolicyChunk": 27,
}

EXPECTED_EDGE_COUNTS = {
    "OWNS": 14317,
    "MADE": 590742,
    "FROM_DEVICE": 120833,
    "PURCHASER_EMAIL": 496262,
    "RECIPIENT_EMAIL": 137453,
    "BILLED_IN": 525003,
    "NEXT": 576425,
    "CASE_INVOLVES": 14955,
    "CASE_ON_CARD": 5565,
    "CASE_CONNECTED_TO": 92,
}

#: A benchmark card, so the traversal is proven on a case that matters.
SAMPLE_CARD = "C04570-K1"

TRAVERSAL_QUERY = """
INTERPRET QUERY () FOR GRAPH {graph} {{
  SEED = {{PaymentCard.*}};
  card = SELECT c FROM SEED:c WHERE c.card_id == "{card}";
  holder = SELECT h FROM card:c -(OWNED_BY>)- Cardholder:h;
  txns = SELECT t FROM card:c -(MADE>)- Transaction:t;
  devices = SELECT d FROM txns:t -(FROM_DEVICE>)- DeviceProfile:d;
  regions = SELECT r FROM txns:t -(BILLED_IN>)- BillingRegion:r;
  cases = SELECT k FROM card:c -(CARD_HAS_CASE>)- ClosedCase:k;
  PRINT card.size() AS cards, holder.size() AS cardholders,
        txns.size() AS transactions, devices.size() AS devices,
        regions.size() AS regions, cases.size() AS prior_cases;
}}
"""

#: Vector search runs through installed queries. vectorSearch is rejected in an
#: INTERPRET QUERY with "Unsupported Statement|TOPK_VEC_SEARCH_FUNC".
CASE_VECTOR_QUERY = "find_similar_closed_cases_v1"
POLICY_VECTOR_QUERY = "find_policy_chunks_v1"

#: Later than every closed case (all close by 2016-11-06), so the causal filter
#: admits the whole history for this check rather than silently emptying it.
VERIFY_AS_OF_TS = "2016-12-31 23:59:59"


def run(connection, query: str, params: dict | None = None):
    return connection.runInterpretedQuery(query, params=params)


def check_counts(connection) -> dict:
    """Compare live counts with the audit.

    realtime=True matters: the cached count lags a load badly enough to report
    a half-loaded graph as finished.
    """
    vertices, edges, problems = {}, {}, []
    for name, expected in EXPECTED_VERTEX_COUNTS.items():
        actual = connection.getVertexCount(name, realtime=True)
        vertices[name] = {"expected": expected, "actual": actual, "ok": actual == expected}
        if actual != expected:
            problems.append(f"{name}: expected {expected:,}, found {actual:,}")
    for name, expected in EXPECTED_EDGE_COUNTS.items():
        actual = connection.getEdgeCount(name)
        edges[name] = {"expected": expected, "actual": actual, "ok": actual == expected}
        if actual != expected:
            problems.append(f"{name}: expected {expected:,}, found {actual:,}")
    return {"vertices": vertices, "edges": edges, "problems": problems}


def check_traversal(connection, graphname: str) -> dict:
    result = run(connection, TRAVERSAL_QUERY.format(graph=graphname, card=SAMPLE_CARD))
    counts = result[0] if result else {}
    reached = {
        key: counts.get(key, 0)
        for key in ("cards", "cardholders", "transactions", "devices", "regions", "prior_cases")
    }
    problems = []
    if reached.get("cards", 0) != 1:
        problems.append(f"card {SAMPLE_CARD} not found")
    # The Gate 1 exit names device and history traversal explicitly, so both
    # are required rather than merely recorded. SAMPLE_CARD is chosen to have
    # online transactions and a prior closed case; if a future sample card has
    # neither, the right fix is a different card, not a weaker assertion.
    for key in ("cardholders", "transactions", "devices", "regions", "prior_cases"):
        if reached.get(key, 0) < 1:
            problems.append(f"card {SAMPLE_CARD} reached no {key}")
    return {"card": SAMPLE_CARD, "reached": reached, "problems": problems}


def check_vector_search(connection, graphname: str) -> dict:
    query_text = (
        "three small online authorizations within an hour followed by a larger "
        "purchase from a device new to the account, card testing"
    )
    vector = embed(query_text)

    cases = connection.runInstalledQuery(
        CASE_VECTOR_QUERY,
        params={"query_vector": vector, "as_of_ts": VERIFY_AS_OF_TS, "k": 5},
    )
    policy = connection.runInstalledQuery(
        POLICY_VECTOR_QUERY, params={"query_vector": vector, "k": 3}
    )

    case_hits = _rows(cases)
    policy_hits = _rows(policy)

    problems = []
    if not case_hits:
        problems.append("closed-case vector search returned nothing")
    if not policy_hits:
        problems.append("policy vector search returned nothing")

    return {
        "query_text": query_text,
        "closed_case_hits": case_hits,
        "policy_hits": policy_hits,
        "problems": problems,
    }


def _rows(result) -> list[dict]:
    """Flatten a query result into plain dicts.

    A PRINT of an accumulator names its attributes after the alias, so the keys
    arrive as "admissible.case_id". The prefix is stripped so callers can read
    "case_id" without knowing the alias used inside the query.
    """
    if not result:
        return []
    payload = result[0]
    for value in payload.values():
        if not isinstance(value, list):
            continue
        rows = []
        for item in value:
            attributes = item.get("attributes", item) if isinstance(item, dict) else item
            rows.append(
                {key.split(".", 1)[-1]: field for key, field in attributes.items()}
                if isinstance(attributes, dict)
                else attributes
            )
        return rows
    return []


def check_reload_idempotent(connection, config) -> dict:
    """Reload one file and confirm the counts do not move."""
    before = connection.getVertexCount("ClosedCase", realtime=True)
    path = PROJECT_ROOT / "data" / "prepared" / "closed_cases.csv"
    connection.runLoadingJobWithFile(str(path), "f", "load_closed_cases")
    after = connection.getVertexCount("ClosedCase", realtime=True)
    return {
        "vertex_type": "ClosedCase",
        "before": before,
        "after": after,
        "ok": before == after,
        "problems": [] if before == after else [f"reload changed the count {before} -> {after}"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reload-check",
        action="store_true",
        help="reload one file and confirm the counts do not move",
    )
    args = parser.parse_args()

    try:
        config = load_config()
        connection = connect(config)
    except TigerGraphConfigError as error:
        print(f"FAILED: {error}")
        return 1

    graphname = config.graphname
    print(f"verifying {graphname} at {config.host}\n")

    report: dict = {"graphname": graphname}
    problems: list[str] = []

    print("1. counts against the Gate 0 audit")
    try:
        counts = check_counts(connection)
    except Exception as error:  # noqa: BLE001
        print(f"   FAILED: {redact(str(error), config)[:200]}")
        return 1
    report["counts"] = counts
    problems += counts["problems"]
    for name, entry in counts["vertices"].items():
        mark = "ok " if entry["ok"] else "BAD"
        print(f"   {mark} {name:18s} {entry['actual']:>8,} / {entry['expected']:>8,}")
    for name, entry in counts["edges"].items():
        mark = "ok " if entry["ok"] else "BAD"
        print(f"   {mark} {name:18s} {entry['actual']:>8,} / {entry['expected']:>8,}")

    print("\n2. traversal from one card")
    try:
        traversal = check_traversal(connection, graphname)
    except Exception as error:  # noqa: BLE001
        print(f"   FAILED: {redact(str(error), config)[:300]}")
        return 1
    report["traversal"] = traversal
    problems += traversal["problems"]
    print(f"   card {traversal['card']} reached {traversal['reached']}")

    print("\n3. TigerGraph vector search")
    try:
        vectors = check_vector_search(connection, graphname)
    except Exception as error:  # noqa: BLE001
        print(f"   FAILED: {redact(str(error), config)[:300]}")
        return 1
    report["vector_search"] = vectors
    problems += vectors["problems"]
    print(f"   query: {vectors['query_text'][:70]}...")
    for hit in vectors["closed_case_hits"][:5]:
        print(
            f"     {hit.get('case_id'):10s} {hit.get('outcome', ''):16s} "
            f"{hit.get('pattern', ''):28s} closed {hit.get('closed_at', '')}"
        )
    for hit in vectors["policy_hits"][:3]:
        print(f"     {hit.get('chunk_id'):34s} {hit.get('title', '')[:50]}")

    if args.reload_check:
        print("\n4. reload idempotence")
        reload_result = check_reload_idempotent(connection, config)
        report["reload"] = reload_result
        problems += reload_result["problems"]
        print(
            f"   ClosedCase {reload_result['before']:,} -> {reload_result['after']:,} "
            f"{'unchanged' if reload_result['ok'] else 'CHANGED'}"
        )

    report["problems"] = problems
    report["passed"] = not problems
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {REPORT_PATH}")

    if problems:
        print("\nFAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nResult: Gate 1 exit criteria met.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
