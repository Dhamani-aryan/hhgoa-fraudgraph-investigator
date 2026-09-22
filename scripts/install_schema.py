"""Install the graph schema and its vector attributes into TigerGraph.

Several TigerGraph behaviours shaped this script and are worth stating, because
each one fails silently rather than loudly:

* ``CREATE VERTEX`` always creates a GLOBAL type, whatever graph the session is
  scoped to. The graph is then composed from those globals by ``CREATE GRAPH``.
  Dropping the graph therefore leaves the types behind, so ``--recreate`` drops
  this project's own types too, or the next run clashes with itself.
* Submitting a multi-statement file in one call is accepted and then does
  nothing: no error, no types. Statements are sent one at a time, which also
  reports exactly which one failed.
* ``gsql`` returns a transcript with a success status even when a statement
  inside it failed, so the transcript text is inspected for failure markers.
* ``getVertexTypes()`` returns an empty list for this graph even when the types
  exist, so membership is read from the ``LS`` catalog line instead.
* A vector attribute cannot appear in ``CREATE VERTEX``; it is added by a
  schema-change job, whose definition and ``RUN`` are two separate statements.
  The job outlives the graph, so it is dropped before being redefined.
* ``LS`` does not print vector attributes, so they are confirmed via
  ``getSchema()``.

Two of the README's suggested vertex names are unavailable in this workspace,
which ships with a starter kit owning global ``Customer`` and ``Card`` types.
Rather than drop objects belonging to the workspace, they are renamed to
``Cardholder`` and ``PaymentCard``. The rename is presentational: customer_id
and card_id keep the dataset's own values, so no answer file changes.

    .venv/Scripts/python scripts/install_schema.py
    .venv/Scripts/python scripts/install_schema.py --recreate
"""

from __future__ import annotations

import argparse
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
SCHEMA_PATH = PROJECT_ROOT / "graph" / "schema.gsql"
VECTOR_PATH = PROJECT_ROOT / "graph" / "vector_attributes.gsql"
REPORT_PATH = PROJECT_ROOT / "runs" / "schema_install.json"

GLOBAL_SCOPE = "global"

#: The graph name written in the checked-in GSQL, replaced with TG_GRAPHNAME.
TEMPLATE_GRAPH_NAME = "HHGOAFraud"

EXPECTED_EDGE_TYPES = (
    "OWNS",
    "MADE",
    "FROM_DEVICE",
    "PURCHASER_EMAIL",
    "RECIPIENT_EMAIL",
    "BILLED_IN",
    "NEXT",
    "CASE_INVOLVES",
    "CASE_ON_CARD",
    "CASE_CONNECTED_TO",
    "INV_INVOLVES",
    "INV_ON_CARD",
    "INV_CONNECTED_TO",
    "INV_USES_DEVICE",
    "INV_SIMILAR_TO",
    "INV_CITES_POLICY",
)

EXPECTED_VERTEX_TYPES = {
    # Cardholder and PaymentCard are the README's Customer and Card, renamed
    # because this workspace's starter kit owns those two names globally.
    "Cardholder",
    "PaymentCard",
    "Transaction",
    "DeviceProfile",
    "EmailDomain",
    "BillingRegion",
    "ClosedCase",
    "InvestigationCase",
    "PolicyChunk",
}

#: Transcript fragments that mean a statement failed. gsql returns a transcript
#: with a success status even when a statement inside it did not run, so the
#: text itself has to be inspected.
FAILURE_MARKERS = (
    "semantic check fails",
    "failed to create",
    "could not be created",
    "does not exist",
)


def split_statements(text: str) -> list[str]:
    """Split a GSQL file into individual statements.

    Submitting schema.gsql as one blob is accepted and then silently does
    nothing: gsql returns a transcript with no error and no types are created.
    Sending one statement at a time works and, more importantly, reports which
    statement failed. Comments are stripped first so a leading comment is never
    mistaken for a command.

    Only safe for files without braces. The vector schema-change job contains
    semicolons inside its body and is sent whole.
    """
    without_comments = re.sub(r"//.*", "", text)
    return [part.strip() for part in without_comments.split(";") if part.strip()]


def render(path: Path, graphname: str) -> str:
    text = path.read_text(encoding="utf-8")
    if graphname != TEMPLATE_GRAPH_NAME:
        text = re.sub(rf"\b{TEMPLATE_GRAPH_NAME}\b", graphname, text)
    return text


def gsql(connection, statements: str, scope: str) -> str:
    return str(connection.gsql(statements, graphname=scope))


def run_gsql(connection, statements: str, config, label: str, scope: str) -> str:
    print(f"  running {label} ...")
    try:
        text = gsql(connection, statements, scope)
    except Exception as error:  # noqa: BLE001
        raise TigerGraphConfigError(f"{label} failed: {redact(str(error), config)}") from None
    lowered = text.lower()
    if any(marker in lowered for marker in FAILURE_MARKERS):
        raise TigerGraphConfigError(f"{label} reported an error:\n{redact(text, config)}")
    return text


def catalog(connection, config) -> str:
    try:
        return gsql(connection, "LS", GLOBAL_SCOPE)
    except Exception as error:  # noqa: BLE001
        # Surfaced, never swallowed: a hidden failure here would make the
        # installer believe the graph is absent and then clash on its name.
        print(f"  warning: could not read the catalog ({type(error).__name__}: {error})")
        return ""


def installed_types(connection, graphname: str) -> tuple[set[str], set[str]]:
    """Read the graph's membership from the catalog.

    getVertexTypes() returns an empty list for this graph even when the types
    demonstrably exist, so the catalog is parsed instead. LS lists a graph's
    members on one line as ``Graph Name(Type:v, EDGE:e, ...)``, which is the
    authoritative statement of what the graph actually contains.
    """
    try:
        text = gsql(connection, "LS", GLOBAL_SCOPE)
    except Exception:  # noqa: BLE001 - catalog unavailable
        return set(), set()
    match = re.search(rf"Graph {re.escape(graphname)}\(([^)]*)\)", text)
    if not match:
        return set(), set()
    vertices, edges = set(), set()
    for member in match.group(1).split(","):
        member = member.strip()
        if member.endswith(":v"):
            vertices.add(member[:-2])
        elif member.endswith(":e"):
            edges.add(member[:-2])
    return vertices, edges


EXPECTED_VECTOR_ATTRIBUTES = {
    "ClosedCase": "memory_embedding",
    "InvestigationCase": "memory_embedding",
    "PolicyChunk": "policy_embedding",
}


def vector_attributes(connection) -> dict[str, list[str]]:
    """Vector attributes per vertex type, read from the schema API.

    LS does not print vector attributes in a vertex definition, so the catalog
    cannot confirm them. getSchema does.
    """
    found: dict[str, list[str]] = {}
    try:
        schema = connection.getSchema(force=True)
    except Exception:  # noqa: BLE001
        return found
    for vertex in schema.get("VertexTypes", []):
        attributes = vertex.get("EmbeddingAttributes") or []
        if attributes:
            found[vertex.get("Name")] = [item.get("Name") for item in attributes]
    return found


def install_vector_attributes(connection, config, graphname: str) -> None:
    """Define and run the vector schema-change job.

    The job definition and its RUN are two statements. Sent together they are
    accepted and silently do nothing, so they are sent separately. A rerun
    reports a name conflict, which means the attribute is already there and is
    treated as success.
    """
    text = re.sub(r"//.*", "", render(VECTOR_PATH, graphname))
    marker = "RUN GLOBAL SCHEMA_CHANGE JOB"
    index = text.index(marker)
    definition, run = text[:index].strip(), text[index:].strip()

    # A schema-change job outlives the graph it altered, so a rerun hits
    # "the job name already exists". Drop it first; absent is the normal case.
    job_name = run.split()[-1]
    try:
        gsql(connection, f"DROP JOB {job_name}", GLOBAL_SCOPE)
    except Exception:  # noqa: BLE001
        pass

    for label, statement in (("define vector job", definition), ("run vector job", run)):
        print(f"  running {label} ...")
        result = gsql(connection, statement, GLOBAL_SCOPE).lower()
        if "conflict with another vector" in result:
            print("    already present, leaving it alone")
            continue
        if any(marker_text in result for marker_text in FAILURE_MARKERS):
            raise TigerGraphConfigError(f"{label} failed: {redact(result, config)}")


def write_report(connection, config, graphname: str, action: str) -> dict:
    """Write runs/schema_install.json from the live schema, not from memory."""
    vertices, edges = installed_types(connection, graphname)
    vectors = vector_attributes(connection)
    missing = sorted(EXPECTED_VERTEX_TYPES - vertices)
    missing_vectors = [
        f"{vertex}.{name}"
        for vertex, name in EXPECTED_VECTOR_ATTRIBUTES.items()
        if name not in vectors.get(vertex, [])
    ]
    try:
        version = connection.getVer()
    except Exception:  # noqa: BLE001
        version = None
    report = {
        "graphname": graphname,
        "action": action,
        "server_version": version,
        "vertex_types": sorted(vertices),
        "edge_types": sorted(edges),
        "missing_vertex_types": missing,
        "vector_attributes": vectors,
        "missing_vector_attributes": missing_vectors,
        "installed": not missing and not missing_vectors,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def total_vertices(connection, types: set[str]) -> int:
    total = 0
    for name in types:
        try:
            total += int(connection.getVertexCount(name))
        except Exception:  # noqa: BLE001 - best effort
            continue
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="drop the graph and reinstall; refused when the graph holds data",
    )
    args = parser.parse_args()

    try:
        config = load_config()
        connection = connect(config)
    except TigerGraphConfigError as error:
        print(f"FAILED: {error}")
        return 1

    graphname = config.graphname
    print(f"schema install into {graphname} at {config.host}")

    present = f"Graph {graphname}" in catalog(connection, config)
    vertices, _ = installed_types(connection, graphname)
    print(f"  graph exists: {present}, vertex types: {len(vertices)}")

    if present and not args.recreate:
        missing = EXPECTED_VERTEX_TYPES - vertices
        if not missing:
            # Still write the full report: a no-op run is evidence too, and a
            # stub would discard the vector-attribute record from the install.
            print("  schema already installed, nothing to do")
            write_report(connection, config, graphname, action="none")
            return 0
        print(f"  schema is incomplete; missing {sorted(missing)}")
        print("  rerun with --recreate to reinstall from scratch")
        return 1

    if present and args.recreate:
        count = total_vertices(connection, vertices)
        if count > 0:
            print(f"REFUSED: the graph holds {count:,} vertices.")
            print("  Drop it deliberately in Savanna if you really mean to discard them.")
            return 1
        print("  graph holds no data; dropping it")
        run_gsql(connection, f"DROP GRAPH {graphname}", config, "DROP GRAPH", GLOBAL_SCOPE)

    if args.recreate:
        # CREATE VERTEX always creates a GLOBAL type, so dropping the graph
        # leaves this project's types behind and the next run clashes with
        # itself. Edges are dropped first because a vertex in use cannot go.
        # Types this project never created are left alone.
        print("  dropping this project's global types from any earlier run")
        for name in EXPECTED_EDGE_TYPES:
            try:
                gsql(connection, f"DROP EDGE {name}", GLOBAL_SCOPE)
            except Exception:  # noqa: BLE001 - absent is the normal case
                pass
        for name in sorted(EXPECTED_VERTEX_TYPES):
            try:
                gsql(connection, f"DROP VERTEX {name}", GLOBAL_SCOPE)
            except Exception:  # noqa: BLE001 - absent is the normal case
                pass

    try:
        statements = split_statements(render(SCHEMA_PATH, graphname))
        print(f"  running schema.gsql ({len(statements)} statements) ...")
        for number, statement in enumerate(statements, 1):
            head = " ".join(statement.split())[:60]
            run_gsql(
                connection,
                statement,
                config,
                f"[{number}/{len(statements)}] {head}",
                GLOBAL_SCOPE,
            )
        install_vector_attributes(connection, config, graphname)
    except TigerGraphConfigError as error:
        print(f"FAILED: {error}")
        return 1

    report = write_report(connection, config, graphname, action="install")
    missing = report["missing_vertex_types"]
    missing_vectors = report["missing_vector_attributes"]

    vertex_list = report["vertex_types"]
    print("")
    print(f"  vertex types: {len(vertex_list)} -> {vertex_list}")
    print(f"  edge types  : {len(report['edge_types'])}")
    print(f"  vector attrs: {report['vector_attributes']}")
    print(f"wrote {REPORT_PATH}")

    if missing:
        print(f"FAILED: missing vertex types {missing}")
        return 1
    if missing_vectors:
        print(f"FAILED: missing vector attributes {missing_vectors}")
        return 1
    print("Result: schema and vector attributes installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
