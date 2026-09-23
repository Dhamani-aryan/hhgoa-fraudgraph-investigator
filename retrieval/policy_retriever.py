"""Policy and typology retrieval through TigerGraph vector search over PolicyChunk.

Two steps, both deterministic:

1. **TigerGraph vector search.** A query text built from the observed signals is
   embedded and searched with ``find_policy_chunks_v1`` (k = 10). Every hit
   carries TigerGraph's cosine distance and its rank.
2. **Deterministic selection.** Each observed signal names the policy and
   typology anchors it makes relevant, in priority order (the table below). A
   retrieved chunk is kept only when an observed signal makes it relevant, and
   at most :data:`MAX_CHUNKS` are kept: first the best retrieved anchor of each
   signal, in signal order, then remaining places by priority. Broad policy
   text that no signal calls for is never kept.

A relevant anchor that TigerGraph did not return in its top ten is reported in
``relevant_not_retrieved`` rather than added: the vector path is the retrieval
path, and this module never injects a chunk the search did not find.

================================  =============================================
observed signal                   relevant anchors, in priority order
================================  =============================================
shared-origin fraud / component   policy:R6, pattern:shared-origin-caution,
                                  policy:R9, pattern:undocumented
card-testing sequence             policy:R5, pattern:card_testing
customer report                   policy:R2, policy:R3, policy:R7
new device, online                pattern:card_not_present_new_device
online, no new device             pattern:card_not_present_fraud
new region, in person             pattern:out_of_region_use
risk-score trigger                policy:R1, pattern:risk-score
analyst request                   policy:R8
================================  =============================================
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from graph.tool_port import QUERY_BUNDLE_VERSION, GraphToolPort, vector_fingerprint
from retrieval.case_retriever import CaseSignals
from retrieval.embeddings import embed

POLICY_QUERY = "find_policy_chunks_v1"
SEARCH_K = 10
MAX_CHUNKS = 4
EXCERPT_CHARS = 600


class RetrievedPolicyChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str
    anchor: str
    title: str
    source_document: str
    excerpt: str
    vector_cosine_distance: float
    vector_cosine_similarity: float
    tigergraph_vector_rank: int
    selection_reason: str
    signal: str
    source_query: str
    query_bundle_version: str


class PolicyRetrieval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    query_text: str
    query_vector: dict[str, Any]
    source_query: str
    trace_id: str
    retrieved_ranked: list[str]
    relevant_anchors: list[str]
    relevant_not_retrieved: list[str] = Field(default_factory=list)
    chunks: list[RetrievedPolicyChunk]

    @property
    def chunk_ids(self) -> list[str]:
        return [chunk.chunk_id for chunk in self.chunks]


def relevance(signals: CaseSignals) -> list[tuple[str, str]]:
    """(signal, anchor) pairs in priority order, deduplicated by anchor."""
    pairs: list[tuple[str, str]] = []
    if signals.shared_origin_fraud or signals.connected_component:
        pairs += [
            ("shared_origin", a)
            for a in (
                "policy:R6",
                "pattern:shared-origin-caution",
                "policy:R9",
                "pattern:undocumented",
            )
        ]
    if signals.small_amount_burst:
        pairs += [("card_testing_sequence", a) for a in ("policy:R5", "pattern:card_testing")]
    if signals.trigger_type == "customer_report":
        pairs += [("customer_report", a) for a in ("policy:R2", "policy:R3", "policy:R7")]
    if signals.channel == "online":
        if signals.device_new:
            pairs.append(("new_device_online", "pattern:card_not_present_new_device"))
        else:
            pairs.append(("online_purchase", "pattern:card_not_present_fraud"))
    if signals.region_new and signals.channel == "in_person":
        pairs.append(("new_region_in_person", "pattern:out_of_region_use"))
    if signals.trigger_type == "risk_score":
        pairs += [("risk_score_trigger", a) for a in ("policy:R1", "pattern:risk-score")]
    if signals.trigger_type == "analyst_request":
        pairs.append(("analyst_request", "policy:R8"))
    seen: set[str] = set()
    ordered = []
    for signal, anchor in pairs:
        if anchor not in seen:
            seen.add(anchor)
            ordered.append((signal, anchor))
    return ordered


def select_anchors(wanted: list[tuple[str, str]], retrieved: dict[str, Any]) -> list[str]:
    """At most MAX_CHUNKS relevant, retrieved anchors: one per signal first.

    A first pass keeps the best retrieved anchor of each observed signal, in
    signal order, so a case with several signals is not described by one of
    them four times over. A second pass fills any remaining places by priority.
    """
    available = [(signal, anchor) for signal, anchor in wanted if anchor in retrieved]
    kept: list[str] = []
    signals_done: set[str] = set()
    for signal, anchor in available:
        if signal not in signals_done and len(kept) < MAX_CHUNKS:
            kept.append(anchor)
            signals_done.add(signal)
    for _, anchor in available:
        if anchor not in kept and len(kept) < MAX_CHUNKS:
            kept.append(anchor)
    return kept


def policy_query_text(signals: CaseSignals) -> str:
    parts = []
    if signals.shared_origin_fraud or signals.connected_component:
        parts.append("several cards show fraud from the same device profile shared origin")
    if signals.small_amount_burst:
        parts.append("three small online authorizations within an hour then a larger purchase")
    if signals.trigger_type == "customer_report":
        parts.append("customer disputes the transaction")
    if signals.channel == "online":
        parts.append(
            "online card not present purchase"
            + (" from a device new for the account" if signals.device_new else "")
        )
    if signals.region_new and signals.channel == "in_person":
        parts.append("card present purchase in a new billing region")
    if signals.trigger_type == "risk_score":
        parts.append("risk score is a reason to look verify before blocking on a weak signal")
    if signals.trigger_type == "analyst_request":
        parts.append("analyst request escalate uncertain exposure")
    return ". ".join(parts) or "fraud alert investigation policy"


def retrieve_policy(port: GraphToolPort, signals: CaseSignals, case_id: str) -> PolicyRetrieval:
    text = policy_query_text(signals)
    embedding = embed(text)
    result = port.run_query(POLICY_QUERY, {"query_vector": embedding, "k": SEARCH_K})
    hits = sorted(
        result.values.get("hits") or [],
        key=lambda hit: (float(hit.get("vector_cosine_distance", 9.0)), hit["chunk_id"]),
    )
    rank = {hit["chunk_id"]: index for index, hit in enumerate(hits, start=1)}
    by_id = {hit["chunk_id"]: hit for hit in hits}
    wanted = relevance(signals)
    signal_of = dict((anchor, signal) for signal, anchor in wanted)

    kept = select_anchors(wanted, by_id)
    chunks = []
    for anchor in kept:
        hit = by_id[anchor]
        distance = float(hit.get("vector_cosine_distance"))
        chunks.append(
            RetrievedPolicyChunk(
                chunk_id=anchor,
                anchor=hit.get("anchor", ""),
                title=hit.get("title", ""),
                source_document=hit.get("source_document", ""),
                excerpt=(hit.get("body") or "")[:EXCERPT_CHARS],
                vector_cosine_distance=round(distance, 6),
                vector_cosine_similarity=round(1.0 - distance, 6),
                tigergraph_vector_rank=rank[anchor],
                selection_reason=(
                    f"observed signal {signal_of[anchor]} makes {anchor} relevant; "
                    f"TigerGraph vector rank {rank[anchor]} of {len(hits)}"
                ),
                signal=signal_of[anchor],
                source_query=POLICY_QUERY,
                query_bundle_version=QUERY_BUNDLE_VERSION,
            )
        )
    return PolicyRetrieval(
        case_id=case_id,
        query_text=text,
        query_vector=vector_fingerprint([round(item, 6) for item in embedding]),
        source_query=POLICY_QUERY,
        trace_id=result.record.trace_id,
        retrieved_ranked=[hit["chunk_id"] for hit in hits],
        relevant_anchors=[anchor for _, anchor in wanted],
        relevant_not_retrieved=[anchor for _, anchor in wanted if anchor not in by_id],
        chunks=chunks,
    )
