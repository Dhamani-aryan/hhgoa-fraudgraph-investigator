"""Build the GraphRAG evidence package for one case.

The pipeline, every step deterministic and every graph call through one
GraphToolPort (MCP primary):

    collect_graph_results      nine structural installed queries
    assemble_features          the full temporal graph feature vector
    retrieve_prior_cases       structural pools + TigerGraph vector search
    retrieve_policy            TigerGraph vector search over PolicyChunk
    -> evidence items          templated claims, appended to a hash-chained ledger
    -> EvidencePackage         four sections + provenance metadata

Claims are produced here from typed values by fixed templates. No model
writes a fact. Each item names its independence group and whether it
supports, contradicts or is neutral to a fraud reading, and an item is only
``contradicting`` when the query behind it completed: a withheld, refused or
inapplicable section yields a ``neutral`` item whose availability says so,
because an unknown is not evidence of absence.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from evidence.collector import CaseTrigger, CollectedResults, collect_graph_results
from evidence.feature_assembler import FeatureVector, assemble_features, parse_ts
from evidence.ledger import EvidenceLedger
from evidence.models import SECTIONS, CallSummary, EvidencePackage, PackageMetadata
from graph.tool_port import MAX_GRAPH_CALLS, QUERY_BUNDLE_VERSION, GraphToolPort, paths_used
from retrieval.case_retriever import PriorCaseRetrieval, case_signals, retrieve_prior_cases
from retrieval.policy_retriever import PolicyRetrieval, retrieve_policy

PACKAGE_CAPS = {
    "prior_cases": 6,
    "policy_chunks": 4,
    "path_segments": 25,
    "entity_ids_per_item": 25,
    "items": 60,
}

#: Timestamp fields that describe the data. ``as_of_ts`` (the review time) and
#: ``anchor_ts`` (a parameter echo) are not data and are not checked.
TIME_KEYS = frozenset(
    {
        "ts",
        "closed_at",
        "effective_cutoff",
        "last_seen",
        "flagged_ts",
        "flagged_region_last_seen",
        "card_last_seen_to_anchor",
    }
)

#: Keys whose string values are dataset identifiers.
ID_KEYS = frozenset(
    {
        "txn_id",
        "card_id",
        "customer_id",
        "device_id",
        "case_id",
        "chunk_id",
        "region_code",
        "domain",
        "from_card",
        "to_card",
        "seed_card_id",
        "flagged_region",
    }
)
ID_LIST_KEYS = frozenset(
    {
        "component_cards",
        "linking_devices",
        "fraud_enriched_cards",
        "cards_in_window",
        "cards_with_confirmed_fraud",
        "fraud_neighbour_card_ids",
        "in_window_card_set",
        "via_devices",
        "via_from_cards",
        "excluded_after_cutoff",
    }
)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _walk(value: Any, keys: frozenset[str], list_keys: frozenset[str] = frozenset()):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in keys and isinstance(item, str) and item:
                yield item
            elif key in list_keys and isinstance(item, list):
                yield from (entry for entry in item if isinstance(entry, str) and entry)
            else:
                yield from _walk(item, keys, list_keys)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item, keys, list_keys)


def max_time(values: Any) -> str | None:
    moments = [moment for moment in map(parse_ts, _walk(values, TIME_KEYS)) if moment]
    return f"{max(moments):%Y-%m-%d %H:%M:%S}" if moments else None


def observed_ids(
    collected: CollectedResults, cases: PriorCaseRetrieval, policy: PolicyRetrieval
) -> list[str]:
    found = set(_walk(collected.values, ID_KEYS, ID_LIST_KEYS))
    found |= {case.case_id for case in cases.cases} | {case.card_id for case in cases.cases}
    found |= set(policy.retrieved_ranked)
    return sorted(found)


class _Claims:
    """Appends items with the provenance of the query behind them."""

    def __init__(self, ledger: EvidenceLedger, collected: CollectedResults, anchor: str):
        self.ledger = ledger
        self.collected = collected
        self.anchor = anchor

    def graph(
        self,
        section,
        role,
        claim,
        *,
        entities,
        group,
        strength,
        value=None,
        features=(),
        availability="observed",
        path_segments=None,
        data_max_time=None,
        query_name=None,
        retrieval=None,
    ):
        result = self.collected.results[role]
        if availability != "observed":
            strength = "neutral"
        dmt = data_max_time or max_time(result.values) or self.anchor
        return self.ledger.append(
            section=section,
            claim=claim,
            source_type="graph",
            ref=f"query:{query_name or result.query_name}",
            query_name=query_name or result.query_name,
            query_bundle_version=QUERY_BUNDLE_VERSION,
            parameters=result.record.parameters,
            entity_ids=_cap(entities),
            value=value,
            feature_names=list(features),
            anchor_time=self.anchor,
            data_max_time=dmt,
            leakage_check_passed=dmt <= self.anchor,
            independence_group=group,
            strength=strength,
            availability=availability,
            retrieval=retrieval,
            path_segments=path_segments,
            trace_id=result.record.trace_id,
        )


def _cap(entities) -> list[str]:
    unique = sorted({str(item) for item in entities if item})
    return unique[: PACKAGE_CAPS["entity_ids_per_item"]]


def _availability(vector: FeatureVector, name: str) -> str:
    state = vector.state(name)
    return {"available": "observed", "withheld": "withheld", "refused": "refused"}.get(
        state, "not_applicable"
    )


def _money(value) -> str:
    return f"${float(value):,.2f}"


# --- section 1: trigger and baseline --------------------------------------------------


def _trigger_and_baseline(claims: _Claims, vector: FeatureVector, trigger: CaseTrigger):
    v = vector.value
    flagged = claims.collected.flagged
    txn, card = trigger.flagged_txn_id, trigger.card_id
    section = "trigger_and_baseline"

    score = v("trigger_risk_score")
    scored = (
        f"; the bank model scored it {score:.2f}, a reason to look and never a verdict"
        if trigger.trigger_type == "risk_score" and score is not None
        else ""
    )
    claims.graph(
        section,
        "context",
        f"{trigger.case_id} was raised by a {trigger.trigger_type} trigger on transaction {txn} "
        f"({_money(flagged.get('amount'))}, {flagged.get('channel')}) on card {card} at "
        f"{flagged.get('ts')}{scored}",
        entities=[txn, card, trigger.customer_id],
        group="trigger_model",
        strength="neutral",
        value={
            "trigger_type": trigger.trigger_type,
            "risk_score": score,
            "amount_usd": flagged.get("amount"),
            "channel": flagged.get("channel"),
            "ts": flagged.get("ts"),
            "region": flagged.get("addr1"),
        },
        features=["trigger_risk_score", "flagged_amount_usd", "flagged_channel"],
    )

    state = vector.value("amount_deviation_state")
    availability = _availability(vector, "amount_history_count")
    amount = flagged.get("amount")
    if availability != "observed":
        claims.graph(
            section,
            "baseline",
            f"No amount baseline for card {card}: {vector.features['amount_history_count'].reason}",
            entities=[card],
            group="customer_history",
            strength="neutral",
            availability=availability,
            features=["amount_history_count"],
        )
    elif state == "no_history":
        claims.graph(
            section,
            "baseline",
            f"Card {card} has no transaction before {txn}",
            entities=[card, txn],
            group="customer_history",
            strength="neutral",
            availability="not_applicable",
            features=["amount_history_count"],
        )
    else:
        pct, dev = v("amount_empirical_percentile"), v("amount_robust_deviation")
        history = v("amount_history_count")
        if state == "zero_mad":
            equal = v("amount_equals_constant_history")
            strength = "contradicting" if equal else "supporting"
            text = (
                f"The {_money(amount)} amount {'matches' if equal else 'differs from'} the "
                f"constant amount of the card's {history} prior transactions "
                f"(median {_money(v('amount_median_usd'))}, MAD 0, so the robust deviation "
                "is undefined rather than zero)"
            )
        else:
            if dev >= 3.5 or pct >= 0.95:
                strength = "supporting"
            elif abs(dev) < 2.0 and 0.05 < pct < 0.95:
                strength = "contradicting"
            else:
                strength = "neutral"
            text = (
                f"The {_money(amount)} amount sits at the {pct:.0%} percentile of card "
                f"{card}'s {history} prior amounts (median {_money(v('amount_median_usd'))}, "
                f"MAD {_money(v('amount_mad_usd'))}, robust deviation {dev:+.2f})"
            )
        claims.graph(
            section,
            "baseline",
            text,
            entities=[card, txn],
            group="customer_history",
            strength=strength,
            value={
                name: v(name)
                for name in (
                    "amount_history_count",
                    "amount_median_usd",
                    "amount_mad_usd",
                    "amount_robust_deviation",
                    "amount_deviation_state",
                    "amount_empirical_percentile",
                    "amount_equals_constant_history",
                )
            },
            features=[
                "amount_empirical_percentile",
                "amount_robust_deviation",
                "amount_median_usd",
                "amount_mad_usd",
            ],
        )

    episode = v("candidate_episode_txn_ids")
    if episode is None:
        claims.graph(
            section,
            "window",
            f"The 48-hour transaction window of card {card} is unavailable: "
            f"{vector.features['candidate_episode_txn_ids'].reason}",
            entities=[card],
            group="temporal_sequence",
            strength="neutral",
            availability=_availability(vector, "candidate_episode_txn_ids"),
            features=["candidate_episode_txn_ids"],
        )
    else:
        small = v("small_online_authorizations_1h_before") or []
        velocity = {s: v(f"card_velocity_{s}") for s in ("1h", "24h", "7d")}
        if len(small) >= 3:
            strength, text = (
                "supporting",
                (
                    f"Card-testing sequence: {len(small)} online authorizations under $5 on card "
                    f"{card} in the hour before {txn}"
                ),
            )
        elif len(episode) >= 2:
            strength, text = (
                "supporting",
                (
                    f"Burst: {len(episode)} same-channel transactions on card {card} in the "
                    f"48 hours to {txn} ({', '.join(episode)})"
                ),
            )
        else:
            strength, text = (
                "contradicting",
                (
                    f"No burst: {txn} is the only same-channel transaction on card {card} in "
                    f"the 48 hours before it, with no card-testing sequence (card velocity "
                    f"1h/24h/7d = "
                    f"{velocity['1h']}/{velocity['24h']}/{velocity['7d']})"
                ),
            )
        claims.graph(
            section,
            "window",
            text,
            entities=[card, *episode, *small],
            group="temporal_sequence",
            strength=strength,
            value={
                "candidate_episode_txn_ids": episode,
                "small_online_authorizations_1h_before": small,
                "card_velocity": velocity,
            },
            features=[
                "candidate_episode_txn_ids",
                "small_online_authorizations_1h_before",
                "card_velocity_1h",
                "card_velocity_24h",
                "card_velocity_7d",
            ],
        )
        claims.graph(
            section,
            "exposure",
            f"The candidate episode ({', '.join(episode)}) totals "
            f"{_money(v('candidate_episode_exposure_usd'))} by "
            "calculate_case_exposure_v1, "
            + (
                "agreeing with the local sum of the window rows"
                if v("candidate_episode_exposure_agrees")
                else "DISAGREEING with the local sum of the window rows"
            ),
            entities=episode,
            group="temporal_sequence",
            strength="neutral",
            value={
                "exposure_usd": v("candidate_episode_exposure_usd"),
                "local_sum_usd": v("candidate_episode_local_sum_usd"),
                "agrees": v("candidate_episode_exposure_agrees"),
                "rule": vector.episode_rule,
            },
            features=["candidate_episode_exposure_usd", "candidate_episode_exposure_agrees"],
        )

    prior = v("prior_cases_on_card") or []
    claims.graph(
        section,
        "context",
        (
            f"Card {card} carries {len(prior)} closed case(s) closed by the anchor: "
            + ", ".join(f"{c['case_id']} ({c['outcome']}, {c['pattern']})" for c in prior)
        )
        if prior
        else f"Card {card} has no closed case closed by the anchor",
        entities=[card, *(c["case_id"] for c in prior)],
        group="customer_history",
        strength="neutral",
        value=prior,
        features=["prior_cases_on_card"],
    )


# --- section 2: graph evidence ---------------------------------------------------------------


def _graph_evidence(claims: _Claims, vector: FeatureVector, trigger: CaseTrigger):
    v = vector.value
    section = "graph_evidence"
    card = trigger.card_id
    device = claims.collected.device_id
    flagged = claims.collected.flagged

    availability = _availability(vector, "device_is_novel_for_card")
    if availability != "observed":
        claims.graph(
            section,
            "features",
            f"No device evidence for {trigger.flagged_txn_id}: "
            f"{vector.features['device_is_novel_for_card'].reason}",
            entities=[trigger.flagged_txn_id, *([device] if device else [])],
            group="device_network",
            strength="neutral",
            availability=availability,
            features=["device_is_novel_for_card"],
        )
    else:
        novel, marked = v("device_is_novel_for_card"), v("device_identity_marked_new")
        claims.graph(
            section,
            "features",
            (
                f"Device {device} had not been used by card {card} before {trigger.flagged_txn_id}"
                if novel
                else f"Device {device} is familiar to card {card}: "
                f"{v('card_prior_transactions_on_device')} earlier transaction(s) on it"
            )
            + ("; the identity record marks it New" if marked else ""),
            entities=[device, card, trigger.flagged_txn_id],
            group="device_network",
            strength="supporting" if novel else "contradicting",
            value={
                "card_prior_transactions_on_device": v("card_prior_transactions_on_device"),
                "device_is_novel_for_card": novel,
                "identity_marked_new": marked,
                "device_degree_to_anchor": v("device_degree_to_anchor"),
            },
            features=["device_is_novel_for_card", "device_identity_marked_new"],
        )

        fraud_n, cleared_n = v("device_fraud_neighbour_cards"), v("device_cleared_neighbour_cards")
        fraud_ids = claims.collected.values["features"].get("fraud_neighbour_card_ids") or []
        # On a supernode device, neighbour outcomes are raw degree: the plan
        # forbids reading coordination -- or its absence -- from them.
        supernode = bool(v("shared_device_is_supernode"))
        caveat = (
            f"; the device is a supernode ({v('shared_device_cards_to_anchor')} cards by the "
            "anchor), so this is raw degree and implies no coordination"
            if supernode
            else ""
        )
        if fraud_n:
            claims.graph(
                section,
                "features",
                f"{fraud_n} other card(s) using device {device} in the window carry "
                f"confirmed fraud closed by the anchor, the latest "
                f"{v('days_since_latest_fraud_neighbour_closure')} days before it{caveat}",
                entities=[device, *fraud_ids],
                group="device_network",
                strength="neutral" if supernode else "supporting",
                value={"fraud_neighbour_cards": fraud_n, "card_ids": sorted(fraud_ids)},
                features=[
                    "device_fraud_neighbour_cards",
                    "days_since_latest_fraud_neighbour_closure",
                ],
            )
        if cleared_n:
            claims.graph(
                section,
                "features",
                f"{cleared_n} other card(s) using device {device} in the window were "
                f"investigated and cleared, the latest "
                f"{v('days_since_latest_cleared_neighbour_closure')} days before the "
                f"anchor{caveat}",
                entities=[device],
                group="device_network",
                strength="neutral" if supernode else "contradicting",
                value={"cleared_neighbour_cards": cleared_n},
                features=[
                    "device_cleared_neighbour_cards",
                    "days_since_latest_cleared_neighbour_closure",
                ],
            )

    if "shared_device" in claims.collected.results:
        _shared_device(claims, vector, device)

    _wcc(claims, vector, card)

    region = flagged.get("addr1")
    availability = _availability(vector, "region_is_new_for_card")
    if region and availability == "observed":
        new = v("region_is_new_for_card")
        claims.graph(
            section,
            "region",
            f"Billing region {region} is new for card {card}"
            if new
            else f"Billing region {region} is familiar to card {card}: "
            f"{v('flagged_region_prior_count')} prior transactions there",
            entities=[region, card],
            group="region_network",
            strength="supporting" if new else "contradicting",
            value={"region_is_new_for_card": new, "prior_count": v("flagged_region_prior_count")},
            features=["region_is_new_for_card", "flagged_region_prior_count"],
        )
        other = v("other_region_activity_in_window")
        in_person = flagged.get("channel") == "in_person"
        claims.graph(
            section,
            "region",
            f"Card {card} was active in {other} transaction(s) in another region within "
            "72 hours of the flagged one"
            + (
                "" if in_person else "; for an online purchase this does not indicate a cloned card"
            ),
            entities=[card, region],
            group="region_network",
            strength="supporting" if (other and in_person) else "neutral",
            value={"other_region_activity_in_window": other},
            features=["other_region_activity_in_window", "concurrent_home_region_activity"],
        )
    for name, role in (
        ("region_degree_to_anchor", "features"),
        ("shared_region_fraud_enrichment_ratio", "shared_region"),
    ):
        if (
            region
            and role in claims.collected.results
            and vector.state(name) in ("withheld", "refused")
        ):
            claims.graph(
                section,
                role,
                f"Region {region} co-occurrence is unknown, not absent: "
                f"{vector.features[name].reason}",
                entities=[region],
                group="region_network",
                strength="neutral",
                availability=_availability(vector, name),
                features=[name],
            )


def _shared_device(claims: _Claims, vector: FeatureVector, device: str):
    v = vector.value
    values = claims.collected.values["shared_device"]
    availability = _availability(vector, "shared_device_is_supernode")
    if availability != "observed":
        claims.graph(
            "graph_evidence",
            "shared_device",
            f"Shared-origin analysis of device {device} is unknown: {values.get('refusal_reason')}",
            entities=[device],
            group="device_network",
            strength="neutral",
            availability=availability,
            features=["shared_device_is_supernode"],
        )
        return
    cards = v("shared_device_cards_to_anchor")
    if v("shared_device_is_supernode"):
        claims.graph(
            "graph_evidence",
            "shared_device",
            f"Device {device} touched {cards} cards by the anchor, above the supernode "
            f"threshold of {values.get('supernode_threshold')}, so co-occurrence on it "
            "cannot imply coordination",
            entities=[device],
            group="device_network",
            strength="neutral",
            value={"cards_to_anchor": cards, "supernode": True},
            features=["shared_device_is_supernode", "shared_device_cards_to_anchor"],
        )
        return
    window_cards = v("shared_device_distinct_cards_in_window")
    fraud = v("shared_device_fraud_enriched_cards") or []
    ratio = v("shared_device_fraud_enrichment_ratio")
    others = sorted(values.get("cards_in_window") or [])
    if window_cards and fraud:
        strength = "supporting"
        text = (
            f"Device {device} is rare ({cards} cards by the anchor) and was used by "
            f"{window_cards} other card(s) in the window, {len(fraud)} with confirmed fraud "
            f"closed by the anchor ({', '.join(fraud)}; enrichment {ratio:.0%})"
        )
    elif window_cards:
        strength = "contradicting"
        text = (
            f"Device {device} was used by {window_cards} other card(s) in the window, none "
            "with confirmed fraud closed by the anchor"
        )
    else:
        strength = "contradicting"
        text = f"No other card used device {device} in the window"
    claims.graph(
        "graph_evidence",
        "shared_device",
        text,
        entities=[device, *others, *fraud],
        group="device_network",
        strength=strength,
        value={
            "cards_to_anchor": cards,
            "rarity": v("shared_device_rarity"),
            "other_cards_in_window": window_cards,
            "fraud_cards": fraud,
            "fraud_enrichment_ratio": ratio,
        },
        features=[
            "shared_device_rarity",
            "shared_device_distinct_cards_in_window",
            "shared_device_fraud_enrichment_ratio",
        ],
    )


def _wcc(claims: _Claims, vector: FeatureVector, card: str):
    v = vector.value
    availability = _availability(vector, "wcc_component_size")
    if availability != "observed":
        claims.graph(
            "graph_evidence",
            "wcc",
            f"The WCC component of {card} is unknown: "
            f"{vector.features['wcc_component_size'].reason}",
            entities=[card],
            group="device_network",
            strength="neutral",
            availability=availability,
            features=["wcc_component_size"],
        )
        return
    size = v("wcc_component_size")
    values = claims.collected.values["wcc"]
    if size == 1:
        claims.graph(
            "graph_evidence",
            "wcc",
            f"Card {card} is isolated in the time-local shared-device WCC: no device it "
            f"used in the {values.get('window_hours')}h window was shared by 2 to "
            f"{values.get('device_card_threshold')} cards",
            entities=[card],
            group="device_network",
            strength="contradicting",
            value={"component_size": 1, "devices_considered": values.get("devices_considered")},
            features=["wcc_component_size", "wcc_isolated"],
            path_segments=[],
        )
        return
    segments = (v("wcc_path_segments") or [])[: PACKAGE_CAPS["path_segments"]]
    fraud = v("wcc_fraud_enriched_members") or []
    reach = v("two_hop_fraud_reachable_cards") or []
    members = {s["to_card"] for s in segments} | {s["from_card"] for s in segments}
    devices = {s["device_id"] for s in segments}
    claims.graph(
        "graph_evidence",
        "wcc",
        f"Time-local WCC over shared devices joins card {card} to {size - 1} other "
        f"card(s) within {values.get('hops_run')} hop(s); {len(fraud)} carry confirmed "
        f"fraud closed by the anchor, {len(reach)} of them within two hops, along "
        f"{len(segments)} exact predecessor-device-member segment(s)",
        entities=[card, *members, *devices],
        group="device_network",
        strength="supporting" if fraud else "neutral",
        value={
            "component_size": size,
            "fraud_enriched_members": fraud,
            "two_hop_reachable_cards": v("two_hop_reachable_cards"),
            "two_hop_fraud_reachable_cards": reach,
            "segments_truncated_in_query": v("wcc_path_segments_truncated"),
        },
        features=[
            "wcc_component_size",
            "wcc_fraud_enriched_members",
            "two_hop_fraud_reachable_cards",
            "wcc_path_segments",
        ],
        path_segments=segments,
    )


# --- sections 3 and 4: case memory and policy ----------------------------------------------


def _case_memory(ledger: EvidenceLedger, anchor: str, retrieval: PriorCaseRetrieval):
    strength_of = {
        "confirmed_fraud_analogue": "supporting",
        "cleared_analogue": "contradicting",
        "boundary": "neutral",
    }
    for case in retrieval.cases:
        similarity = (
            "n/a"
            if case.vector_cosine_similarity is None
            else f"{case.vector_cosine_similarity:.3f}"
        )
        ledger.append(
            section="case_memory",
            claim=(
                f"Retrieved {case.outcome} case {case.case_id} ({case.pattern}, closed "
                f"{case.closed_at[:10]}) as a {case.group.replace('_', ' ')}: composite "
                f"retrieval score {case.composite_retrieval_score:.3f}, TigerGraph cosine "
                f"similarity {similarity} (rank {case.vector_pool_rank} in "
                f"{case.vector_pool}); reasons: {', '.join(case.reasons)}"
            ),
            source_type="graph_vector"
            if retrieval.retrieval_path == "tigergraph_vector"
            else "graph",
            ref=f"query:{case.source_query}",
            query_name=case.source_query,
            query_bundle_version=case.query_bundle_version,
            parameters={"query_vector": retrieval.query_vector, "as_of_ts": anchor},
            entity_ids=[case.case_id, case.card_id],
            value={
                "outcome": case.outcome,
                "pattern": case.pattern,
                "exposure_usd": case.exposure_usd,
                "n_txns": case.n_txns,
            },
            anchor_time=anchor,
            data_max_time=case.closed_at,
            leakage_check_passed=case.closed_at <= anchor,
            independence_group="case_memory",
            strength=strength_of[case.group],
            retrieval=case.model_dump(
                include={
                    "group",
                    "composite_retrieval_score",
                    "component_scores",
                    "recency_contribution",
                    "vector_cosine_distance",
                    "vector_cosine_similarity",
                    "vector_pool",
                    "vector_pool_rank",
                    "reasons",
                    "closed_before_anchor",
                }
            ),
            trace_id=retrieval.trace_id,
        )


def _policy_context(ledger: EvidenceLedger, anchor: str, retrieval: PolicyRetrieval):
    for chunk in retrieval.chunks:
        ledger.append(
            section="policy_context",
            claim=(
                f"{chunk.chunk_id} ({chunk.title}) is relevant to the observed signal "
                f"{chunk.signal}: {chunk.excerpt[:240]}"
            ),
            source_type="policy_document",
            ref=chunk.chunk_id,
            query_name=chunk.source_query,
            document_ref=f"{chunk.source_document}#{chunk.anchor}",
            query_bundle_version=chunk.query_bundle_version,
            parameters={"query_vector": retrieval.query_vector},
            entity_ids=[chunk.chunk_id],
            value={"title": chunk.title, "signal": chunk.signal},
            anchor_time=anchor,
            data_max_time=None,
            leakage_check_passed=True,
            independence_group="policy",
            strength="neutral",
            retrieval=chunk.model_dump(
                include={
                    "vector_cosine_distance",
                    "vector_cosine_similarity",
                    "tigergraph_vector_rank",
                    "selection_reason",
                }
            ),
            trace_id=retrieval.trace_id,
        )


# --- the package -----------------------------------------------------------------------------


def build_evidence_package(
    port: GraphToolPort, trigger: CaseTrigger, *, created_at: str | None = None
) -> EvidencePackage:
    collected = collect_graph_results(port, trigger)
    anchor = collected.anchor_time
    vector = assemble_features(trigger.case_id, anchor, collected.values)
    cases = retrieve_prior_cases(
        port, vector, seed_card=trigger.card_id, trigger_type=trigger.trigger_type
    )
    signals = case_signals(vector, trigger.card_id, trigger.trigger_type)
    policy = retrieve_policy(port, signals, trigger.case_id)

    ledger = EvidenceLedger(trigger.case_id)
    claims = _Claims(ledger, collected, anchor)
    _trigger_and_baseline(claims, vector, trigger)
    _graph_evidence(claims, vector, trigger)
    _case_memory(ledger, anchor, cases)
    _policy_context(ledger, anchor, policy)

    sections = {section: [i for i in ledger.items if i.section == section] for section in SECTIONS}
    item_times = [item.data_max_time for item in ledger.items if item.data_max_time]
    data_max = max([vector.data_max_time, *item_times])
    log = port.log
    primary = getattr(port, "primary", port)
    metadata = PackageMetadata(
        port_mode=port.mode,
        primary_adapter=primary.adapter,
        fallback_occurred=bool(getattr(port, "fallback_occurred", False)),
        fallback_events=[event.as_dict() for event in getattr(port, "fallback_events", [])],
        adapters_used=paths_used(log),
        mcp_trace_ids=[r.trace_id for r in log.records if r.adapter == "mcp" and r.ok],
        graph_call_count=port.budget.used,
        graph_call_budget=port.budget.max_calls,
        calls=[
            CallSummary(
                trace_id=r.trace_id,
                adapter=r.adapter,
                tool=r.tool,
                query_name=r.query_name,
                duration_ms=r.duration_ms,
                ok=r.ok,
                result_bytes=r.result_bytes,
                error_class=r.error_class,
            )
            for r in log.records
        ],
        query_versions={r.query_name: QUERY_BUNDLE_VERSION for r in log.records if r.ok},
        query_bundle_version=QUERY_BUNDLE_VERSION,
        created_at=created_at or _now(),
        anchor_time=anchor,
        review_time=trigger.opened_at,
        data_max_time=data_max,
        withheld_or_unavailable=vector.indicators(),
        caps={**PACKAGE_CAPS, "graph_calls": MAX_GRAPH_CALLS},
        truncated={
            "wcc_path_segments": len(vector.value("wcc_path_segments") or [])
            > PACKAGE_CAPS["path_segments"],
            "wcc_segments_in_query": bool(vector.value("wcc_path_segments_truncated")),
            "transaction_window": bool(collected.values["window"].get("window_truncated")),
        },
    )
    package_id = (
        "PKG-"
        + hashlib.sha256(f"{trigger.case_id}|{anchor}|{ledger.last_hash}".encode()).hexdigest()[:16]
    )
    return EvidencePackage(
        package_id=package_id,
        case_id=trigger.case_id,
        trigger={
            "case_id": trigger.case_id,
            "trigger_type": trigger.trigger_type,
            "trigger_text": trigger.trigger_text,
            "flagged_txn_id": trigger.flagged_txn_id,
            "card_id": trigger.card_id,
            "customer_id": trigger.customer_id,
            "opened_at": trigger.opened_at,
            "risk_score": trigger.risk_score,
        },
        anchor_time=anchor,
        data_max_time=data_max,
        leakage_check_passed=vector.leakage_check_passed
        and data_max <= anchor
        and all(item.leakage_check_passed for item in ledger.items),
        sections=sections,
        features=vector.features,
        prior_case_retrieval=cases,
        policy_retrieval=policy,
        observed_entity_ids=observed_ids(collected, cases, policy),
        ledger_final_hash=ledger.last_hash,
        metadata=metadata,
    )
