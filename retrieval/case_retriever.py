"""Hybrid prior-case retrieval: structural candidates, TigerGraph vector search, rerank.

The plan's two-stage pipeline, deterministic end to end:

Stage 1 -- structural candidate generation, in GSQL
    ``find_similar_closed_cases_v1`` admits only closed cases that closed at or
    before the anchor, excludes the current case, and never reads
    ``InvestigationCase`` (the active benchmark memory epoch). It splits the
    admissible pool into confirmed-fraud and cleared, narrows each to an
    exposure band around the candidate episode, adds a shared-origin pool of
    cases on cards the graph already connects to this one (WCC component,
    shared-device fraud cards, the card itself), and runs TigerGraph
    ``vectorSearch`` over each pool with ``candidate_set``.

Stage 2 -- deterministic reranking, here
    Each candidate gets named component scores in [0, 1] and one composite:

    ========================  ======  ==========================================
    component                 weight  what it measures
    ========================  ======  ==========================================
    vector_cosine_similarity  0.30    1 - TigerGraph's cosine distance
    pattern_compatibility     0.25    candidate pattern vs the observed signals
    shared_origin             0.20    candidate card joined to this case
    size_similarity           0.15    episode size vs the case's n_txns
    recency                   0.10    exp(-days since closure / 90)
    ========================  ======  ==========================================

    The vector weight is capped at 0.30 so generic narrative word overlap
    cannot outrank structure. ``composite_retrieval_score`` is a weighted sum,
    NOT a similarity, and is named accordingly; it is strictly positive because
    recency is. It is the value stored on ``INV_SIMILAR_TO.similarity``.

Selection -- at most six, contrastive by construction
    up to two confirmed-fraud analogues, up to two cleared analogues, and up to
    two structurally closest remaining cases as boundary cases, each with a
    non-empty reason vector. Ties break on case id.

If the TigerGraph vector query cannot run, :func:`retrieve_prior_cases` falls
back to local lexical cosine over a caller-supplied closed-case memory and marks
the result ``retrieval_path="local_fallback_not_tigergraph"``. That path exists
for development and outages only and does not satisfy the Gate 2 exit.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from evidence.feature_assembler import FeatureVector, parse_ts
from graph.tool_port import (
    QUERY_BUNDLE_VERSION,
    GraphToolError,
    GraphToolPort,
    vector_fingerprint,
)
from retrieval.embeddings import cosine, embed

CASE_QUERY = "find_similar_closed_cases_v1"
K_PER_POOL = 6
MAX_RESULTS = 6
PER_GROUP = 2
RECENCY_DAYS = 90.0

WEIGHTS = {
    "vector_cosine_similarity": 0.30,
    "pattern_compatibility": 0.25,
    "shared_origin": 0.20,
    "size_similarity": 0.15,
    "recency": 0.10,
}

RetrievalPath = Literal["tigergraph_vector", "local_fallback_not_tigergraph"]
Group = Literal["confirmed_fraud_analogue", "cleared_analogue", "boundary"]


class RetrievedCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    outcome: str
    pattern: str
    closed_at: str
    card_id: str
    exposure_usd: float
    n_txns: int
    group: Group
    composite_retrieval_score: float
    component_scores: dict[str, float]
    recency_contribution: float
    vector_cosine_distance: float | None
    vector_cosine_similarity: float | None
    vector_pool: str
    vector_pool_rank: int
    reasons: list[str]
    source_query: str
    query_bundle_version: str
    closed_before_anchor: bool


class PriorCaseRetrieval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    anchor_time: str
    retrieval_path: RetrievalPath
    fallback_reason: str = ""
    query_text: str
    query_vector: dict[str, Any]
    source_query: str
    trace_id: str = ""
    admissibility_cutoff: str
    pool_sizes: dict[str, int] = Field(default_factory=dict)
    band: dict[str, float] = Field(default_factory=dict)
    band_relaxed: dict[str, bool] = Field(default_factory=dict)
    candidates_considered: int
    #: Rows rejected by the defensive admissibility check, with the reason.
    rejected_inadmissible: dict[str, str] = Field(default_factory=dict)
    cases: list[RetrievedCase]
    weights: dict[str, float] = Field(default_factory=lambda: dict(WEIGHTS))

    @property
    def case_ids(self) -> list[str]:
        return [case.case_id for case in self.cases]


# --- what the case looks like ---------------------------------------------------------


@dataclass(frozen=True)
class CaseSignals:
    """The observed signals retrieval conditions on, all read from the feature vector."""

    channel: str
    device_new: bool
    burst: bool
    small_amount_burst: bool
    region_new: bool
    shared_origin_fraud: bool
    connected_component: bool
    episode_size: int
    episode_exposure: float
    related_cards: tuple[str, ...]
    trigger_type: str
    seed_card: str = ""

    def compatible_patterns(self) -> set[str]:
        patterns = set()
        if self.channel == "online":
            patterns.add("card_not_present_fraud")
            if self.device_new:
                patterns.add("card_not_present_new_device")
        if self.small_amount_burst:
            patterns.add("card_testing")
        if self.region_new and self.channel == "in_person":
            patterns.add("out_of_region_use")
        if self.shared_origin_fraud or self.connected_component:
            patterns.add("undocumented")
        if self.device_new and self.region_new:
            patterns.add("account_takeover")
        return patterns


def case_signals(vector: FeatureVector, seed_card: str, trigger_type: str) -> CaseSignals:
    value = vector.value
    episode = value("candidate_episode_txn_ids") or []
    related = set(value("wcc_fraud_enriched_members") or [])
    related |= {segment["to_card"] for segment in value("wcc_path_segments") or []}
    related |= set(value("shared_device_fraud_enriched_cards") or [])
    related.add(seed_card)
    # A burst means the candidate episode itself holds several transactions,
    # not the card's lifetime count of short gaps.
    burst = len(episode) >= 2
    return CaseSignals(
        channel=value("flagged_channel") or "",
        device_new=bool(value("device_is_novel_for_card") or value("device_identity_marked_new")),
        burst=burst,
        small_amount_burst=len(value("small_online_authorizations_1h_before") or []) >= 3,
        region_new=bool(value("region_is_new_for_card")),
        shared_origin_fraud=bool(value("shared_device_fraud_enrichment_ratio")),
        connected_component=(value("wcc_component_size") or 1) > 1,
        episode_size=max(len(episode), 1),
        episode_exposure=float(value("candidate_episode_exposure_usd") or 0.0),
        related_cards=tuple(sorted(related)),
        trigger_type=trigger_type,
        seed_card=seed_card,
    )


def query_text(signals: CaseSignals) -> str:
    """A deterministic description of the observed behaviour, for the embedding."""
    parts = [
        "online card not present purchase"
        if signals.channel == "online"
        else "in person card present purchase",
    ]
    if signals.device_new:
        parts.append("device new for this account")
    if signals.small_amount_burst:
        parts.append("several small authorizations in quick succession then a larger purchase")
    elif signals.burst:
        parts.append("burst of transactions in quick succession")
    if signals.region_new:
        parts.append("billing region new for the card")
    if signals.shared_origin_fraud:
        parts.append("shared device used by another card with confirmed fraud")
    if signals.connected_component:
        parts.append("several cards connected through shared devices")
    parts.append(f"{signals.episode_size} transactions")
    return ". ".join(parts)


# --- scoring --------------------------------------------------------------------------


def _days(anchor: datetime, closed_at: str) -> float:
    moment = parse_ts(closed_at)
    return max((anchor - moment).total_seconds() / 86400.0, 0.0) if moment else 365.0


def score_candidate(candidate: dict[str, Any], signals: CaseSignals, anchor: datetime):
    """Named component scores in [0, 1], their composite, and the reason vector."""
    outcome = candidate.get("outcome", "")
    pattern = candidate.get("pattern", "")
    distance = candidate.get("vector_cosine_distance")
    similarity = None if distance is None else max(0.0, min(1.0, 1.0 - float(distance)))
    compatible = signals.compatible_patterns()
    if outcome == "cleared":
        pattern_score = 0.5  # a cleared case is a contrast, not a pattern match
    else:
        pattern_score = 1.0 if pattern in compatible else 0.0
    shared = 1.0 if candidate.get("card_id") in signals.related_cards else 0.0
    n_txns = int(candidate.get("n_txns") or 0)
    size = 1.0 / (1.0 + abs(n_txns - signals.episode_size))
    days = _days(anchor, candidate.get("closed_at", ""))
    recency = math.exp(-days / RECENCY_DAYS)
    components = {
        "vector_cosine_similarity": round(similarity or 0.0, 6),
        "pattern_compatibility": pattern_score,
        "shared_origin": shared,
        "size_similarity": round(size, 6),
        "recency": round(recency, 6),
    }
    composite = sum(WEIGHTS[name] * value for name, value in components.items())

    reasons: list[str] = []
    if signals.seed_card and candidate.get("card_id") == signals.seed_card:
        reasons.append("same_card")
    elif shared:
        reasons.append("shared_origin")
    if pattern_score == 1.0:
        reasons.append(f"compatible_pattern:{pattern}")
        if pattern == "card_not_present_new_device" and signals.device_new:
            reasons.append("same_new_device")
        if pattern == "card_testing" and signals.small_amount_burst:
            reasons.append("similar_velocity")
    if size >= 0.5:
        reasons.append("similar_episode_size")
    if outcome == "cleared":
        reasons.append("opposite_outcome")
    reasons.append(f"tigergraph_vector_rank:{candidate.get('vector_pool_rank')}")
    structural = (
        composite - WEIGHTS["vector_cosine_similarity"] * components["vector_cosine_similarity"]
    )
    return components, round(composite, 6), round(structural, 6), reasons, similarity


def _ranked(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach each case's rank within the pool that retrieved it, by distance."""
    pools: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        pool = sorted(row.get("retrieved_by") or ["unknown"])[0]
        pools.setdefault(pool, []).append(row)
    ranked = []
    for pool, members in pools.items():
        members.sort(key=lambda row: (row.get("vector_cosine_distance") or 9.0, row["case_id"]))
        for rank, row in enumerate(members, start=1):
            ranked.append({**row, "vector_pool": pool, "vector_pool_rank": rank})
    return ranked


def select(
    candidates: list[dict[str, Any]], signals: CaseSignals, anchor: datetime, anchor_text: str
) -> list[RetrievedCase]:
    scored = []
    for row in candidates:
        components, composite, structural, reasons, similarity = score_candidate(
            row, signals, anchor
        )
        scored.append((row, components, composite, structural, reasons, similarity))

    def build(item, group: Group) -> RetrievedCase:
        row, components, composite, _, reasons, similarity = item
        return RetrievedCase(
            case_id=row["case_id"],
            outcome=row.get("outcome", ""),
            pattern=row.get("pattern", ""),
            closed_at=row.get("closed_at", ""),
            card_id=row.get("card_id", ""),
            exposure_usd=float(row.get("exposure_usd") or 0.0),
            n_txns=int(row.get("n_txns") or 0),
            group=group,
            composite_retrieval_score=composite,
            component_scores=components,
            recency_contribution=round(WEIGHTS["recency"] * components["recency"], 6),
            vector_cosine_distance=row.get("vector_cosine_distance"),
            vector_cosine_similarity=None if similarity is None else round(similarity, 6),
            vector_pool=row.get("vector_pool", ""),
            vector_pool_rank=int(row.get("vector_pool_rank") or 0),
            reasons=reasons if group != "boundary" else ["structurally_close_boundary", *reasons],
            source_query=CASE_QUERY,
            query_bundle_version=QUERY_BUNDLE_VERSION,
            closed_before_anchor=(row.get("closed_at") or "9999") <= anchor_text,
        )

    by_composite = sorted(scored, key=lambda item: (-item[2], item[0]["case_id"]))
    chosen: list[RetrievedCase] = []
    taken: set[str] = set()
    for outcome, group in (
        ("confirmed_fraud", "confirmed_fraud_analogue"),
        ("cleared", "cleared_analogue"),
    ):
        for item in [entry for entry in by_composite if entry[0].get("outcome") == outcome][
            :PER_GROUP
        ]:
            chosen.append(build(item, group))
            taken.add(item[0]["case_id"])
    by_structure = sorted(scored, key=lambda item: (-item[3], item[0]["case_id"]))
    for item in [entry for entry in by_structure if entry[0]["case_id"] not in taken][:PER_GROUP]:
        chosen.append(build(item, "boundary"))
        taken.add(item[0]["case_id"])
    return chosen[:MAX_RESULTS]


# --- retrieval ------------------------------------------------------------------------


def exposure_band(signals: CaseSignals) -> tuple[float, float]:
    """A factor-of-four band around the candidate episode; (0, 0) means no band."""
    if signals.episode_exposure <= 0:
        return 0.0, 0.0
    return round(signals.episode_exposure / 4.0, 2), round(signals.episode_exposure * 4.0, 2)


def retrieve_prior_cases(
    port: GraphToolPort,
    vector: FeatureVector,
    *,
    seed_card: str,
    trigger_type: str,
    exclude_case_id: str = "",
    local_memory: list[dict[str, Any]] | None = None,
) -> PriorCaseRetrieval:
    anchor = parse_ts(vector.anchor_time)
    signals = case_signals(vector, seed_card, trigger_type)
    text = query_text(signals)
    embedding = embed(text)
    low, high = exposure_band(signals)
    params = {
        "query_vector": embedding,
        "as_of_ts": vector.anchor_time,
        "k": K_PER_POOL,
        "related_card_ids": list(signals.related_cards),
        "min_exposure": low,
        "max_exposure": high,
    }
    if exclude_case_id:
        params["exclude_case_id"] = exclude_case_id
    try:
        result = port.run_query(CASE_QUERY, params)
    except GraphToolError as error:
        if local_memory is None:
            raise
        return _local_fallback(
            vector,
            signals,
            text,
            embedding,
            local_memory,
            exclude_case_id,
            f"{type(error).__name__}: {error}",
        )
    values = result.values
    admitted, rejected = admissible_rows(
        values.get("admissible") or [], vector.anchor_time, exclude_case_id
    )
    candidates = _ranked(admitted)
    cases = select(candidates, signals, anchor, vector.anchor_time)
    return PriorCaseRetrieval(
        case_id=vector.case_id,
        anchor_time=vector.anchor_time,
        retrieval_path="tigergraph_vector",
        query_text=text,
        query_vector=vector_fingerprint([round(item, 6) for item in embedding]),
        source_query=CASE_QUERY,
        trace_id=result.record.trace_id,
        admissibility_cutoff=str(values.get("admissibility_cutoff", "")),
        pool_sizes={
            "admissible": int(values.get("admissible_pool_size") or 0),
            "confirmed_fraud": int(values.get("fraud_pool_size") or 0),
            "cleared": int(values.get("cleared_pool_size") or 0),
            "shared_origin": int(values.get("shared_origin_pool_size") or 0),
        },
        band={"min_exposure": low, "max_exposure": high},
        band_relaxed={
            "confirmed_fraud": bool(values.get("fraud_band_relaxed")),
            "cleared": bool(values.get("cleared_band_relaxed")),
        },
        candidates_considered=len(candidates),
        rejected_inadmissible=rejected,
        cases=cases,
    )


def admissible_rows(
    rows: list[dict[str, Any]], anchor_time: str, exclude_case_id: str
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Belt and braces over the GSQL filter: only closed cases, closed by the anchor.

    The query already enforces all three conditions. They are checked again
    here so that no change to the query, and no other vertex type, can put a
    future case, the case itself or a benchmark-epoch case in front of the
    investigator. Anything rejected is reported by id.
    """
    admitted, rejected = [], {}
    for row in rows:
        case_id = str(row.get("case_id", ""))
        if not case_id.startswith("CC-"):
            rejected[case_id] = "not a ClosedCase from the supplied history"
        elif case_id == exclude_case_id:
            rejected[case_id] = "the case being investigated"
        elif not row.get("closed_at") or row["closed_at"] > anchor_time:
            rejected[case_id] = f"closed at {row.get('closed_at')}, after the anchor"
        else:
            admitted.append(row)
    return admitted, rejected


# --- the marked local fallback ----------------------------------------------------------


def load_local_memory(path: Path) -> list[dict[str, Any]]:
    """Closed cases from the prepared CSV, for the development fallback only."""
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            {
                "case_id": row["case_id"],
                "outcome": row.get("outcome", ""),
                "pattern": row.get("pattern", ""),
                "closed_at": row.get("closed_at", ""),
                "card_id": row.get("card_id", ""),
                "exposure_usd": float(row.get("exposure_usd") or 0.0),
                "n_txns": int(float(row.get("n_txns") or 0)),
                "memory_text": row.get("memory_text", ""),
            }
            for row in csv.DictReader(handle)
        ]


def _local_fallback(vector, signals, text, embedding, memory, exclude_case_id, reason):
    anchor = parse_ts(vector.anchor_time)
    admissible, _ = admissible_rows(memory, vector.anchor_time, exclude_case_id)
    rows = []
    for row in admissible:
        distance = round(1.0 - cosine(embedding, embed(row.get("memory_text", ""))), 6)
        pool = {"confirmed_fraud": "local_fraud_pool", "cleared": "local_cleared_pool"}.get(
            row.get("outcome"), "local_other_pool"
        )
        rows.append({**row, "vector_cosine_distance": distance, "retrieved_by": [pool]})
    ranked = [row for row in _ranked(rows) if row["vector_pool_rank"] <= K_PER_POOL]
    cases = select(ranked, signals, anchor, vector.anchor_time)
    # The reasons must not claim a TigerGraph rank on this path.
    cases = [
        case.model_copy(
            update={
                "reasons": [
                    reason_item.replace("tigergraph_vector_rank", "local_lexical_rank")
                    for reason_item in case.reasons
                ]
            }
        )
        for case in cases
    ]
    return PriorCaseRetrieval(
        case_id=vector.case_id,
        anchor_time=vector.anchor_time,
        retrieval_path="local_fallback_not_tigergraph",
        fallback_reason=reason[:300],
        query_text=text,
        query_vector=vector_fingerprint([round(item, 6) for item in embedding]),
        source_query="local_lexical_cosine",
        admissibility_cutoff=vector.anchor_time,
        pool_sizes={"admissible": len(admissible)},
        candidates_considered=len(ranked),
        cases=cases,
    )
