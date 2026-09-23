"""The single entry point for writing an investigation case to the graph.

Callers use :func:`write_case`. It runs ``write_investigation_case_v1``, applies
the retrieval attributes the query cannot set itself, then reads the case back
through the separate ``read_investigation_case_v1`` query and compares what the
graph holds with what was sent. The receipt it returns is the only thing an
answer's ``written_to_graph`` may rest on.

Why the read-back is independent: the write query reports what it matched, and
a write that reports its own success is asserting, not confirming. The read
query fetches the stored vertex and walks its edges on its own, so a dropped
edge, a stale edge left by an earlier write, a truncated attribute or a lost
similarity all show up as a named mismatch rather than as a receipt.

Why the retrieval attributes are applied here rather than in GSQL: the query
needs a per-case similarity and reason list while iterating the matched prior
cases, and GSQL rejects a MAP parameter accessor inside ``ACCUM`` with TYP-1001.
Leaving the edge at zero permanently was the worse option, because an
``INV_SIMILAR_TO`` edge with no similarity and no reasons cannot answer why a
case was cited, which is the question retrieval provenance exists for.

The write stays a single path: nothing else in the project writes, and a caller
that uses this function gets a verified case or a receipt saying it did not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from graph.result_normalizers import rows, scalar

WRITE_QUERY = "write_investigation_case_v1"
READ_QUERY = "read_investigation_case_v1"

#: Every identifier collection the write reports on.
UNMATCHED_FIELDS = (
    "unmatched_txn_ids",
    "unmatched_card_ids",
    "unmatched_case_ids",
    "unmatched_device_ids",
    "unmatched_policy_chunk_ids",
)

#: InvestigationCase attributes compared on read-back. The payload key and the
#: stored attribute share a name. ``written_at`` is set by the graph with
#: ``now()`` and is not in the payload, so it is not compared.
READ_BACK_ATTRIBUTES = (
    "case_id",
    "memory_epoch",
    "status",
    "verdict",
    "fraud_probability",
    "pattern",
    "pattern_description",
    "exposure_usd",
    "first_suspicious_txn_id",
    "summary",
    "stop_reason",
    "initial_actions",
    "final_actions",
    "sar_filed",
    "sar_narrative",
    "opened_at",
    "anchor_time",
    "query_bundle_version",
    "scoring_version",
    "policy_version",
    "prompt_version",
    "code_commit",
    "answer_json",
    "memory_text",
)
FLOAT_ATTRIBUTES = frozenset({"fraud_probability", "exposure_usd"})
DATETIME_ATTRIBUTES = frozenset({"opened_at", "anchor_time"})

#: (payload key, read-back block, id attribute, read-back edge count).
#: The on-card relationship is a single id rather than a set and is handled
#: beside these.
RELATIONSHIPS = (
    ("affected_txn_ids", "affected_transactions", "txn_id", "affected_txn_edge_count"),
    ("connected_card_ids", "connected_cards", "card_id", "connected_card_edge_count"),
    ("device_profile_ids", "device_profiles", "device_id", "device_edge_count"),
    ("similar_case_ids", "similar_prior_cases", "case_id", "similar_case_edge_count"),
    ("policy_chunk_ids", "cited_policy_chunks", "chunk_id", "policy_chunk_edge_count"),
)


@dataclass(frozen=True)
class WriteReceipt:
    """What the graph actually accepted, and whether reading it back agreed."""

    case_id: str
    complete: bool
    unmatched: dict[str, list[str]] = field(default_factory=dict)
    unmatched_on_card_id: str = ""
    edge_counts: dict[str, int] = field(default_factory=dict)
    similarity_edges_attributed: int = 0
    errors: list[str] = field(default_factory=list)
    read_back_verified: bool = False
    read_back_mismatches: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True only when the write was complete AND an independent read agreed.

        A partial write is a failure, not a receipt, and so is a complete write
        whose read-back disagrees with what was sent. An answer may set
        written_to_graph=true only when the graph holds every identifier and
        value the answer claims, otherwise a case can cite evidence the graph
        does not contain.
        """
        return self.complete and not self.errors and self.read_back_verified

    @property
    def written_to_graph(self) -> bool:
        """The value an answer's ``written_to_graph`` must take."""
        return self.ok

    @property
    def graph_case_id(self) -> str:
        """The value an answer's ``graph_case_id`` must take: empty unless verified."""
        return self.case_id if self.ok else ""

    def describe(self) -> str:
        if self.ok:
            return f"{self.case_id}: complete, read back and verified"
        problems = [f"{name}={ids}" for name, ids in self.unmatched.items() if ids]
        if self.unmatched_on_card_id:
            problems.append(f"on_card={self.unmatched_on_card_id}")
        problems.extend(self.errors)
        problems.extend(f"read-back: {item}" for item in self.read_back_mismatches)
        if not self.read_back_verified and not self.read_back_mismatches:
            problems.append("read-back: not verified")
        label = "PARTIAL" if not self.complete else "NOT VERIFIED"
        return f"{self.case_id}: {label} ({'; '.join(problems) or 'unknown'})"


def _same_float(sent: Any, stored: Any) -> bool:
    try:
        return math.isclose(float(sent), float(stored), rel_tol=1e-9, abs_tol=1e-6)
    except (TypeError, ValueError):
        return False


def _as_datetime(value: Any) -> datetime | None:
    text = str(value).strip().replace("T", " ")
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def _same_datetime(sent: Any, stored: Any) -> bool:
    left, right = _as_datetime(sent), _as_datetime(stored)
    if left is None or right is None:
        return str(sent) == str(stored)
    return left == right


def _requested_ids(payload: dict[str, Any], key: str) -> set[str]:
    return {str(item) for item in payload.get(key) or []}


def verify_read_back(
    payload: dict[str, Any],
    result: Any,
    *,
    similarity: dict[str, float] | None = None,
    reasons: dict[str, str] | None = None,
) -> list[str]:
    """Compare a ``read_investigation_case_v1`` result with what was written.

    Returns one human-readable line per disagreement; an empty list means the
    graph holds exactly what the payload asked for. Pure, so the comparison is
    unit-testable without a graph.

    Relationship ids are compared as SETS in both directions. A stored id that
    was not requested is a mismatch too: edges are additive, so a rewrite with
    fewer identifiers leaves the earlier edges behind, and a graph whose edges
    do not mirror the answer is not a receipt for that answer.
    """
    similarity = similarity or {}
    reasons = reasons or {}
    mismatches: list[str] = []

    if scalar(result, "found") is not True:
        return [f"case {payload.get('case_id')!r} was not found by {READ_QUERY}"]

    stored_rows = rows(result, "investigation_case")
    if len(stored_rows) != 1:
        return [f"expected one stored InvestigationCase, read {len(stored_rows)}"]
    stored = stored_rows[0]

    for name in READ_BACK_ATTRIBUTES:
        if name not in payload:
            continue
        if name not in stored:
            mismatches.append(f"attribute {name} was not returned")
            continue
        sent, held = payload[name], stored[name]
        if name in FLOAT_ATTRIBUTES:
            same = _same_float(sent, held)
        elif name in DATETIME_ATTRIBUTES:
            same = _same_datetime(sent, held)
        elif isinstance(sent, bool):
            same = held is sent
        else:
            same = str(sent) == str(held)
        if not same:
            mismatches.append(f"attribute {name}: sent {sent!r}, stored {held!r}")

    for key, block, id_attribute, count_name in RELATIONSHIPS:
        requested = _requested_ids(payload, key)
        read = rows(result, block)
        stored_ids = {str(item.get(id_attribute)) for item in read}
        missing = sorted(requested - stored_ids)
        extra = sorted(stored_ids - requested)
        if missing:
            mismatches.append(f"{key}: requested but not stored {missing}")
        if extra:
            mismatches.append(f"{key}: stored but not requested {extra}")
        count = scalar(result, count_name)
        if count != len(requested):
            mismatches.append(f"{count_name}: {count} edges read, {len(requested)} requested")
        if len(read) != len(stored_ids):
            mismatches.append(f"{block}: {len(read)} rows for {len(stored_ids)} distinct ids")

    on_card_id = str(payload.get("on_card_id") or "")
    requested_on_card = {on_card_id} if on_card_id else set()
    stored_on_card = {str(item.get("card_id")) for item in rows(result, "on_card")}
    if stored_on_card != requested_on_card:
        mismatches.append(
            f"on_card: requested {sorted(requested_on_card)}, stored {sorted(stored_on_card)}"
        )
    if scalar(result, "on_card_edge_count") != len(requested_on_card):
        mismatches.append(
            f"on_card_edge_count: {scalar(result, 'on_card_edge_count')} edges read, "
            f"{len(requested_on_card)} requested"
        )

    requested_cases = _requested_ids(payload, "similar_case_ids")
    for item in rows(result, "similar_prior_cases"):
        closed_case_id = str(item.get("case_id"))
        if closed_case_id not in requested_cases:
            continue  # already reported as stored but not requested
        sent_similarity = similarity.get(closed_case_id, 0.0)
        sent_reasons = str(reasons.get(closed_case_id, ""))
        if not _same_float(sent_similarity, item.get("similarity")):
            mismatches.append(
                f"similarity of {closed_case_id}: sent {sent_similarity!r}, "
                f"stored {item.get('similarity')!r}"
            )
        if str(item.get("reasons", "")) != sent_reasons:
            mismatches.append(
                f"reasons of {closed_case_id}: sent {sent_reasons!r}, "
                f"stored {item.get('reasons')!r}"
            )

    return mismatches


def write_case(
    connection,
    payload: dict[str, Any],
    *,
    similarity: dict[str, float] | None = None,
    reasons: dict[str, str] | None = None,
) -> WriteReceipt:
    """Write one case, attribute its retrieval edges, then read it back.

    ``payload`` is the write query's parameters. ``similarity`` and ``reasons``
    are keyed by closed-case id and applied to the ``INV_SIMILAR_TO`` edges that
    the query created. The receipt is ``ok`` only when the write was complete,
    every attribution succeeded, and an independent read-back agreed with the
    payload on every attribute, relationship and retrieval attribute.
    """
    similarity = similarity or {}
    reasons = reasons or {}
    case_id = payload["case_id"]

    result = connection.runInstalledQuery(WRITE_QUERY, params=payload, usePost=True)

    unmatched = {name: list(scalar(result, name) or []) for name in UNMATCHED_FIELDS}
    edge_counts = {
        name: scalar(result, name)
        for name in (
            "affected_txn_edges_written",
            "connected_card_edges_written",
            "on_card_edges_written",
            "device_edges_written",
            "similar_case_edges_written",
            "policy_chunk_edges_written",
        )
    }

    errors: list[str] = []
    attributed = 0

    # Only cases the query actually matched can carry an edge to attribute.
    matched_cases = set(payload.get("similar_case_ids", [])) - set(unmatched["unmatched_case_ids"])
    for closed_case_id in sorted(matched_cases):
        if closed_case_id not in similarity and closed_case_id not in reasons:
            continue
        try:
            connection.upsertEdge(
                "InvestigationCase",
                case_id,
                "INV_SIMILAR_TO",
                "ClosedCase",
                closed_case_id,
                {
                    "similarity": float(similarity.get(closed_case_id, 0.0)),
                    "reasons": str(reasons.get(closed_case_id, "")),
                },
            )
            attributed += 1
        except Exception as error:  # noqa: BLE001
            errors.append(f"could not attribute {closed_case_id}: {error}")

    # The independent read-back. A failure to read is a failure to verify.
    try:
        read_back = read_case(connection, case_id)
        mismatches = verify_read_back(payload, read_back, similarity=similarity, reasons=reasons)
    except Exception as error:  # noqa: BLE001
        mismatches = [f"{READ_QUERY} failed: {error}"]

    return WriteReceipt(
        case_id=case_id,
        complete=bool(scalar(result, "write_complete")),
        unmatched=unmatched,
        unmatched_on_card_id=scalar(result, "unmatched_on_card_id") or "",
        edge_counts=edge_counts,
        similarity_edges_attributed=attributed,
        errors=errors,
        read_back_verified=not mismatches,
        read_back_mismatches=mismatches,
    )


def read_case(connection, case_id: str):
    """Read a case back. The receipt an answer's written_to_graph rests on."""
    return connection.runInstalledQuery(READ_QUERY, params={"case_id": case_id})
