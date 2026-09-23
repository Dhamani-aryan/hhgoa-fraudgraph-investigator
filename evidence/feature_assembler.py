"""Assemble the plan's complete temporal graph feature vector from eight queries.

``extract_temporal_graph_features_v1`` deliberately returns only the part of the
vector that is one traversal from the flagged transaction. This module composes
the rest from the queries that own it, so the scorer and the evidence package
see ONE vector with ONE provenance per value:

=================================  ============================================
Feature family                     Source query
=================================  ============================================
card velocity, burst, device /     extract_temporal_graph_features_v1
email / region degree, neighbours
robust amount statistics           get_card_baseline_v1 (amounts to the anchor)
region novelty, home-region        find_region_anomalies_v1
overlap
shared-entity rarity, fraud        find_shared_origin_activity_v1
enrichment
WCC size, fraud-enriched size,     wcc_shared_origin_v1
path segments, two-hop reach
candidate-episode exposure         get_transaction_window_v1 +
                                   calculate_case_exposure_v1
trigger, device identity flags     get_case_context_v1
=================================  ============================================

Unavailable is never zero
-------------------------
Every feature carries a :data:`FeatureState`. A scan withheld for budget, a
query refusal (for example a supernode), an entity the case does not have (an
in-person purchase has no device) and a query that did not run are four
different states, and none of them is the value 0 or False. A consumer that
reads ``value`` without ``state`` gets ``None`` for all four.

Resource prechecks are never features: every source is read through
:func:`graph.result_normalizers.evidence_values`, which drops each
``*precheck_lifetime_transactions`` figure before this module sees it.

The module is pure. It never calls the graph; the context builder runs the
queries through a GraphToolPort and hands the normalized results here.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from graph.result_normalizers import evidence_values
from scoring.robust_baselines import amount_stats, history_without_flagged

FeatureState = Literal["available", "withheld", "refused", "not_applicable", "unavailable"]

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

#: The deterministic candidate-episode rule, stated where it is applied: the
#: flagged transaction plus every same-card, same-channel transaction in the
#: 48 hours before it. The card-not-present pattern is "a burst of two to four
#: within 48 hours". This is a CANDIDATE for Gate 3 to accept or narrow, not an
#: exposure verdict.
EPISODE_WINDOW_HOURS = 48

#: The roles the assembler reads. Each maps to one installed query.
ROLE_QUERIES = {
    "context": "get_case_context_v1",
    "baseline": "get_card_baseline_v1",
    "window": "get_transaction_window_v1",
    "features": "extract_temporal_graph_features_v1",
    "shared_device": "find_shared_origin_activity_v1",
    "shared_region": "find_shared_origin_activity_v1",
    "region": "find_region_anomalies_v1",
    "wcc": "wcc_shared_origin_v1",
    "exposure": "calculate_case_exposure_v1",
}


class Feature(BaseModel):
    """One named value and the state that says whether it may be read."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    value: Any = None
    state: FeatureState
    source_query: str
    reason: str = ""
    unit: str = ""

    def available(self) -> bool:
        return self.state == "available"


class FeatureVector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    anchor_time: str
    features: dict[str, Feature]
    #: Latest source timestamp any feature rests on. Must not exceed the anchor.
    data_max_time: str
    leakage_violations: list[str] = Field(default_factory=list)
    #: The deterministic rule the candidate episode was selected by.
    episode_rule: str = ""

    @property
    def leakage_check_passed(self) -> bool:
        return not self.leakage_violations

    def value(self, name: str) -> Any:
        feature = self.features.get(name)
        return feature.value if feature is not None and feature.available() else None

    def state(self, name: str) -> str:
        feature = self.features.get(name)
        return feature.state if feature is not None else "unavailable"

    def indicators(self) -> dict[str, list[str]]:
        """Feature names grouped by every state other than available."""
        grouped: dict[str, list[str]] = {}
        for name, feature in sorted(self.features.items()):
            if not feature.available():
                grouped.setdefault(feature.state, []).append(name)
        return grouped


# --- helpers -------------------------------------------------------------------


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:19], TIMESTAMP_FORMAT)
    except ValueError:
        return None


class _Builder:
    def __init__(self, anchor: datetime):
        self.anchor = anchor
        self.features: dict[str, Feature] = {}
        self.timestamps: list[tuple[str, datetime]] = []

    def add(self, name, value, source, *, state: FeatureState = "available", reason="", unit=""):
        if state != "available":
            value = None
        self.features[name] = Feature(
            name=name, value=value, state=state, source_query=source, reason=reason, unit=unit
        )

    def mark(self, names, source, state: FeatureState, reason: str):
        for name in names:
            self.add(name, None, source, state=state, reason=reason)

    def seen(self, label: str, value: str | None):
        """Record a source timestamp for the leakage check."""
        parsed = parse_ts(value)
        if parsed is not None:
            self.timestamps.append((label, parsed))


def _source(results: dict[str, dict[str, Any]], role: str) -> dict[str, Any] | None:
    raw = results.get(role)
    return None if raw is None else evidence_values([raw])


def _gate(values: dict[str, Any] | None) -> tuple[FeatureState, str] | None:
    """The state a whole source forces, or None when it answered."""
    if values is None:
        return "unavailable", "the query did not run"
    if values.get("refused") is True:
        return "refused", str(values.get("refusal_reason") or "the query refused the request")
    return None


def _days_between(later: datetime, earlier: datetime | None) -> float | None:
    if earlier is None:
        return None
    return round((later - earlier).total_seconds() / 86400.0, 2)


# --- the assembler --------------------------------------------------------------


def assemble_features(
    case_id: str,
    anchor_time: str,
    results: dict[str, dict[str, Any]],
) -> FeatureVector:
    """Compose the full feature vector from normalized query results by role."""
    anchor = parse_ts(anchor_time)
    if anchor is None:
        raise ValueError(f"anchor_time {anchor_time!r} is not {TIMESTAMP_FORMAT}")
    build = _Builder(anchor)

    context = _source(results, "context")
    flagged = ((context or {}).get("flagged_transaction") or [{}])[0]
    _trigger(build, context, flagged)
    _one_hop(build, _source(results, "features"))
    _amounts(build, _source(results, "baseline"), flagged)
    _region(build, _source(results, "region"))
    _shared(build, _source(results, "shared_device"), "device")
    _shared(build, _source(results, "shared_region"), "region")
    _wcc(build, _source(results, "wcc"))
    _exposure(build, _source(results, "window"), _source(results, "exposure"), flagged)

    violations = [
        f"{label} at {moment:%Y-%m-%d %H:%M:%S} is after the anchor {anchor_time}"
        for label, moment in build.timestamps
        if moment > anchor
    ]
    latest = max((moment for _, moment in build.timestamps), default=anchor)
    return FeatureVector(
        case_id=case_id,
        anchor_time=anchor_time,
        features=build.features,
        data_max_time=f"{latest:%Y-%m-%d %H:%M:%S}",
        leakage_violations=violations,
        episode_rule=(
            f"flagged transaction plus same-card, same-channel transactions in the "
            f"{EPISODE_WINDOW_HOURS}h before it"
        ),
    )


def _trigger(build: _Builder, context, flagged) -> None:
    source = "get_case_context_v1"
    gate = _gate(context)
    names = (
        "flagged_amount_usd",
        "flagged_channel",
        "trigger_risk_score",
        "device_identity_marked_new",
        "device_proxy_category",
        "prior_cases_on_card",
    )
    if gate:
        build.mark(names, source, *gate)
        return
    build.seen("flagged transaction", flagged.get("ts"))
    build.add("flagged_amount_usd", flagged.get("amount"), source, unit="USD")
    build.add("flagged_channel", flagged.get("channel"), source)
    build.add(
        "trigger_risk_score",
        flagged.get("risk_score"),
        source,
        reason="the bank model's score: a reason to look, never a verdict",
    )
    devices = context.get("device") or []
    if not devices:
        reason = "the flagged transaction has no strong device signature"
        build.mark(
            ("device_identity_marked_new", "device_proxy_category"),
            source,
            "not_applicable",
            reason,
        )
    else:
        device = devices[0]
        build.add(
            "device_identity_marked_new",
            device.get("new_or_found") == "New",
            source,
            reason="identity record id_15 for the flagged transaction",
        )
        build.add("device_proxy_category", device.get("proxy_category") or "", source)
    prior = context.get("prior_cases_on_card") or []
    for case in prior:
        build.seen(f"prior case {case.get('case_id')} closure", case.get("closed_at"))
    build.add(
        "prior_cases_on_card",
        sorted(
            (
                {
                    "case_id": case["case_id"],
                    "outcome": case.get("outcome"),
                    "pattern": case.get("pattern"),
                    "closed_at": case.get("closed_at"),
                }
                for case in prior
            ),
            key=lambda item: item["case_id"],
        ),
        source,
    )


def _one_hop(build: _Builder, values) -> None:
    source = "extract_temporal_graph_features_v1"
    card = (
        "card_velocity_1h",
        "card_velocity_24h",
        "card_velocity_7d",
        "card_velocity_to_anchor",
        "burst_transitions",
        "device_is_novel_for_card",
    )
    device = (
        "device_degree_1h",
        "device_degree_24h",
        "device_degree_7d",
        "device_degree_to_anchor",
        "device_distinct_cards_in_window",
        "device_distinct_customers_in_window",
        "device_fraud_neighbour_cards",
        "device_cleared_neighbour_cards",
        "days_since_latest_fraud_neighbour_closure",
        "days_since_latest_cleared_neighbour_closure",
    )
    region = (
        "region_degree_1h",
        "region_degree_24h",
        "region_degree_7d",
        "region_degree_to_anchor",
        "region_distinct_cards_in_window",
    )
    email = (
        "email_degree_1h",
        "email_degree_24h",
        "email_degree_7d",
        "email_degree_to_anchor",
        "email_distinct_cards_in_window",
    )
    gate = _gate(values)
    if gate:
        build.mark(card + device + region + email, source, *gate)
        return
    build.seen("one-hop feature cutoff", values.get("effective_cutoff"))
    for scale in ("1h", "24h", "7d"):
        build.add(
            f"card_velocity_{scale}",
            values.get(f"card_degree_{scale}"),
            source,
            unit="transactions",
        )
    build.add(
        "card_velocity_to_anchor", values.get("card_degree_to_cutoff"), source, unit="transactions"
    )
    build.add(
        "burst_transitions",
        values.get("burst_transitions"),
        source,
        reason=f"consecutive gaps under {values.get('burst_gap_seconds')}s",
        unit="transitions",
    )

    has_device = bool(values.get("device"))
    if not has_device:
        build.mark(
            device + ("device_is_novel_for_card",),
            source,
            "not_applicable",
            "the flagged transaction has no strong device signature",
        )
    elif values.get("device_scan_skipped"):
        build.mark(
            device + ("device_is_novel_for_card",),
            source,
            "withheld",
            "device lifetime volume exceeds the scan budget",
        )
    else:
        build.add("device_is_novel_for_card", values.get("device_is_novel_for_card"), source)
        for scale in ("1h", "24h", "7d"):
            build.add(f"device_degree_{scale}", values.get(f"device_degree_{scale}"), source)
        build.add("device_degree_to_anchor", values.get("device_degree_to_cutoff"), source)
        for name in (
            "device_distinct_cards_in_window",
            "device_distinct_customers_in_window",
            "device_fraud_neighbour_cards",
            "device_cleared_neighbour_cards",
        ):
            build.add(name, values.get(name), source)
        for outcome in ("fraud", "cleared"):
            closure = values.get(f"latest_{outcome}_neighbour_closure")
            build.seen(f"latest {outcome} neighbour closure", closure)
            name = f"days_since_latest_{outcome}_neighbour_closure"
            moment = parse_ts(closure)
            if moment is None or values.get(f"device_{outcome}_neighbour_cards", 0) == 0:
                build.add(
                    name,
                    None,
                    source,
                    state="not_applicable",
                    reason=f"no {outcome} neighbour closed by the cutoff",
                )
            else:
                build.add(name, _days_between(build.anchor, moment), source, unit="days")

    for entity, names in (("region", region), ("email", email)):
        if values.get(f"{entity}_scan_skipped"):
            build.mark(
                names,
                source,
                "withheld",
                str(values.get(f"{entity}_features_withheld_reason") or "over budget"),
            )
            continue
        for scale in ("1h", "24h", "7d"):
            build.add(f"{entity}_degree_{scale}", values.get(f"{entity}_degree_{scale}"), source)
        build.add(f"{entity}_degree_to_anchor", values.get(f"{entity}_degree_to_cutoff"), source)
        build.add(
            f"{entity}_distinct_cards_in_window",
            values.get(f"{entity}_distinct_cards_in_window"),
            source,
        )


def _amounts(build: _Builder, values, flagged) -> None:
    source = "get_card_baseline_v1"
    names = (
        "amount_history_count",
        "amount_median_usd",
        "amount_mad_usd",
        "amount_robust_deviation",
        "amount_deviation_state",
        "amount_empirical_percentile",
        "amount_equals_constant_history",
    )
    gate = _gate(values)
    if gate:
        build.mark(names, source, *gate)
        return
    if values.get("scan_skipped"):
        build.mark(names, source, "withheld", str(values.get("skip_reason") or "over budget"))
        return
    build.seen("baseline last seen", values.get("last_seen"))
    amount = flagged.get("amount")
    if amount is None:
        build.mark(names, source, "unavailable", "the flagged amount is not known")
        return
    history = history_without_flagged(values.get("amounts_to_anchor") or [], amount)
    stats = amount_stats(history, amount)
    build.add(
        "amount_history_count",
        stats.history_count,
        source,
        unit="transactions",
        reason="card transactions before the flagged one, to the anchor",
    )
    build.add("amount_deviation_state", stats.deviation_state, source)
    if stats.deviation_state == "no_history":
        build.mark(
            names[1:4] + names[5:], source, "not_applicable", "the card has no prior transactions"
        )
        return
    build.add("amount_median_usd", round(stats.median, 2), source, unit="USD")
    build.add("amount_mad_usd", round(stats.mad, 2), source, unit="USD")
    build.add("amount_empirical_percentile", round(stats.empirical_percentile, 4), source)
    if stats.deviation_state == "zero_mad":
        build.add(
            "amount_robust_deviation",
            None,
            source,
            state="not_applicable",
            reason="MAD is 0: the deviation is undefined, not zero",
        )
        build.add("amount_equals_constant_history", stats.amount_equals_constant_history, source)
    else:
        build.add(
            "amount_robust_deviation",
            round(stats.robust_deviation, 3),
            source,
            reason="0.6745 * (amount - median) / MAD",
        )
        build.add(
            "amount_equals_constant_history",
            None,
            source,
            state="not_applicable",
            reason="the history is not constant",
        )


def _region(build: _Builder, values) -> None:
    source = "find_region_anomalies_v1"
    names = (
        "region_is_new_for_card",
        "flagged_region_prior_count",
        "other_region_activity_in_window",
        "concurrent_home_region_activity",
    )
    gate = _gate(values)
    if gate:
        build.mark(names, source, *gate)
        return
    build.seen("flagged transaction", values.get("flagged_ts"))
    build.seen("flagged region last seen", values.get("flagged_region_last_seen"))
    for item in values.get("concurrent_other_region_activity") or []:
        build.seen(f"concurrent transaction {item.get('txn_id')}", item.get("ts"))
    if not values.get("flagged_region"):
        build.mark(names, source, "not_applicable", "the flagged transaction has no region")
        return
    build.add("region_is_new_for_card", values.get("region_is_new_for_card"), source)
    build.add("flagged_region_prior_count", values.get("flagged_region_prior_count"), source)
    other = values.get("other_region_activity_in_window")
    build.add(
        "other_region_activity_in_window",
        other,
        source,
        reason="card activity in a different region within the home window",
    )
    build.add("concurrent_home_region_activity", bool(other), source)


def _shared(build: _Builder, values, entity: str) -> None:
    source = "find_shared_origin_activity_v1"
    prefix = f"shared_{entity}"
    names = (
        f"{prefix}_cards_to_anchor",
        f"{prefix}_is_supernode",
        f"{prefix}_rarity",
        f"{prefix}_distinct_cards_in_window",
        f"{prefix}_fraud_enriched_cards",
        f"{prefix}_fraud_enrichment_ratio",
    )
    if values is None:
        build.mark(
            names,
            source,
            "not_applicable" if entity == "device" else "unavailable",
            f"no {entity} to examine",
        )
        return
    build.seen(f"shared {entity} cutoff", values.get("effective_cutoff"))
    if values.get("refused_over_scan_budget") or values.get("refused_unknown_entity"):
        build.mark(
            names,
            source,
            "withheld" if values.get("refused_over_scan_budget") else "refused",
            str(values.get("refusal_reason")),
        )
        return
    cards = values.get("entity_cards_to_cutoff")
    build.add(
        f"{prefix}_cards_to_anchor",
        cards,
        source,
        unit="cards",
        reason="distinct cards on the entity to the cutoff",
    )
    build.add(
        f"{prefix}_rarity",
        round(1.0 / cards, 6) if cards else None,
        source,
        state="available" if cards else "not_applicable",
        reason="1 / distinct cards to the cutoff; 1.0 is unshared",
    )
    supernode = bool(values.get("refused_as_supernode"))
    build.add(
        f"{prefix}_is_supernode",
        supernode,
        source,
        reason=f"more than {values.get('supernode_threshold')} cards at the cutoff",
    )
    if supernode:
        build.mark(names[3:], source, "refused", str(values.get("refusal_reason")))
        return
    window_cards = values.get("distinct_cards_in_window") or 0
    enriched = values.get("fraud_enriched_card_count") or 0
    for case in values.get("prior_fraud_cases") or []:
        build.seen(f"shared {entity} fraud case {case.get('case_id')}", case.get("closed_at"))
    for item in values.get("shared_transactions") or []:
        build.seen(f"shared {entity} transaction {item.get('txn_id')}", item.get("ts"))
    build.add(f"{prefix}_distinct_cards_in_window", window_cards, source, unit="cards")
    build.add(
        f"{prefix}_fraud_enriched_cards",
        sorted(values.get("cards_with_confirmed_fraud") or []),
        source,
    )
    build.add(
        f"{prefix}_fraud_enrichment_ratio",
        round(enriched / window_cards, 4) if window_cards else None,
        source,
        state="available" if window_cards else "not_applicable",
        reason="confirmed-fraud cards / other cards in the window",
    )


def _wcc(build: _Builder, values) -> None:
    source = "wcc_shared_origin_v1"
    names = (
        "wcc_component_size",
        "wcc_fraud_enriched_members",
        "wcc_path_segments",
        "wcc_path_segments_truncated",
        "two_hop_reachable_cards",
        "two_hop_fraud_reachable_cards",
        "wcc_isolated",
    )
    gate = _gate(values)
    if gate:
        build.mark(names, source, *gate)
        return
    build.seen("WCC cutoff", values.get("effective_cutoff"))
    seed = values.get("seed_card_id")
    for case in values.get("component_prior_fraud_cases") or []:
        build.seen(f"WCC fraud case {case.get('case_id')}", case.get("closed_at"))
    segments = sorted(
        values.get("path_segments") or [],
        key=lambda s: (s["hop"], s["to_card"], s["from_card"], s["device_id"]),
    )
    fraud_cards = set(values.get("fraud_enriched_cards") or []) - {seed}
    build.add("wcc_component_size", values.get("component_size"), source, unit="cards")
    build.add("wcc_isolated", values.get("component_size") == 1, source)
    build.add(
        "wcc_fraud_enriched_members",
        sorted(fraud_cards),
        source,
        reason="component cards other than the seed with confirmed fraud closed by the cutoff",
    )
    build.add("wcc_path_segments", segments, source)
    build.add("wcc_path_segments_truncated", values.get("path_segments_truncated"), source)

    # Two-hop reach, derived ONLY from returned, bounded segments: a card counts
    # when a chain of returned segments of length <= 2 connects it to the seed.
    reachable = _reachable_within(seed, segments, 2)
    build.add(
        "two_hop_reachable_cards",
        sorted(reachable),
        source,
        reason="cards joined to the seed by <= 2 returned path segments",
    )
    build.add("two_hop_fraud_reachable_cards", sorted(reachable & fraud_cards), source)


def _reachable_within(seed: str, segments: list[dict], hops: int) -> set[str]:
    frontier, reached = {seed}, set()
    for _ in range(hops):
        step = {s["to_card"] for s in segments if s["from_card"] in frontier} - reached - {seed}
        reached |= step
        frontier = step
    return reached


def _exposure(build: _Builder, window, exposure, flagged) -> None:
    source = "calculate_case_exposure_v1"
    names = (
        "candidate_episode_txn_ids",
        "candidate_episode_exposure_usd",
        "candidate_episode_local_sum_usd",
        "candidate_episode_exposure_agrees",
        "candidate_episode_excluded_after_cutoff",
    )
    for gate_values in (window, exposure):
        gate = _gate(gate_values)
        if gate:
            build.mark(names, source, *gate)
            return
    if window.get("window_truncated"):
        build.mark(names, source, "withheld", "the transaction window was truncated")
        return
    rows = window.get("window_transactions") or []
    for item in rows:
        build.seen(f"window transaction {item.get('txn_id')}", item.get("ts"))
    for item in exposure.get("transactions") or []:
        build.seen(f"exposure transaction {item.get('txn_id')}", item.get("ts"))
    episode = episode_rows(rows, flagged)
    local = round(sum(abs(float(item["amount"])) for item in episode), 2)
    graph_total = round(float(exposure.get("exposure_usd") or 0.0), 2)
    build.add("candidate_episode_txn_ids", sorted(item["txn_id"] for item in episode), source)
    build.add(
        "candidate_episode_exposure_usd",
        graph_total,
        source,
        unit="USD",
        reason="calculate_case_exposure_v1 over the candidate episode",
    )
    build.add("candidate_episode_local_sum_usd", local, "get_transaction_window_v1", unit="USD")
    build.add(
        "candidate_episode_exposure_agrees",
        math.isclose(local, graph_total, abs_tol=0.005) and not exposure.get("missing_txn_ids"),
        source,
    )
    build.add(
        "candidate_episode_excluded_after_cutoff",
        sorted(exposure.get("excluded_after_cutoff") or []),
        source,
    )


def episode_rows(rows: list[dict], flagged: dict) -> list[dict]:
    """The deterministic candidate episode from a card's window rows."""
    channel = flagged.get("channel")
    return sorted(
        (
            item
            for item in rows
            if item.get("channel") == channel or item.get("txn_id") == flagged.get("txn_id")
        ),
        key=lambda item: (item.get("ts") or "", item.get("txn_id") or ""),
    )
