"""The single entry point for writing an investigation case to the graph.

Callers use :func:`write_case`. It runs ``write_investigation_case_v1``, applies
the retrieval attributes the query cannot set itself, and returns a receipt
saying whether the write was complete.

Why the attributes are applied here rather than in GSQL: the query needs a
per-case similarity and reason list while iterating the matched prior cases, and
GSQL rejects a MAP parameter accessor inside ``ACCUM`` with TYP-1001. Leaving
the edge at zero permanently was the worse option, because an
``INV_SIMILAR_TO`` edge with no similarity and no reasons cannot answer why a
case was cited, which is the question retrieval provenance exists for.

The write stays a single path: nothing else in the project writes, and a caller
that uses this function gets both halves or a receipt saying it did not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from graph.result_normalizers import scalar

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


@dataclass(frozen=True)
class WriteReceipt:
    """What the graph actually accepted."""

    case_id: str
    complete: bool
    unmatched: dict[str, list[str]] = field(default_factory=dict)
    unmatched_on_card_id: str = ""
    edge_counts: dict[str, int] = field(default_factory=dict)
    similarity_edges_attributed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True only when everything asked for is in the graph.

        A partial write is a failure, not a receipt. An answer may set
        written_to_graph=true only when the graph holds every identifier the
        answer claims, otherwise a case can cite evidence the graph does not
        contain.
        """
        return self.complete and not self.errors

    def describe(self) -> str:
        if self.ok:
            return f"{self.case_id}: complete"
        problems = [f"{name}={ids}" for name, ids in self.unmatched.items() if ids]
        if self.unmatched_on_card_id:
            problems.append(f"on_card={self.unmatched_on_card_id}")
        problems.extend(self.errors)
        return f"{self.case_id}: PARTIAL ({'; '.join(problems) or 'unknown'})"


def write_case(
    connection,
    payload: dict[str, Any],
    *,
    similarity: dict[str, float] | None = None,
    reasons: dict[str, str] | None = None,
) -> WriteReceipt:
    """Write one case and attribute its retrieval edges.

    ``payload`` is the write query's parameters. ``similarity`` and ``reasons``
    are keyed by closed-case id and applied to the ``INV_SIMILAR_TO`` edges that
    the query created.
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

    return WriteReceipt(
        case_id=case_id,
        complete=bool(scalar(result, "write_complete")),
        unmatched=unmatched,
        unmatched_on_card_id=scalar(result, "unmatched_on_card_id") or "",
        edge_counts=edge_counts,
        similarity_edges_attributed=attributed,
        errors=errors,
    )


def read_case(connection, case_id: str):
    """Read a case back. The receipt an answer's written_to_graph rests on."""
    return connection.runInstalledQuery(READ_QUERY, params={"case_id": case_id})
