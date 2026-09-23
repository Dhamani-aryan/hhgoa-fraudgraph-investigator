"""Run one case's structural graph queries through a GraphToolPort.

The order is fixed and every call is bounded, so one case costs a known number
of graph calls against the plan's budget of twelve:

1. get_case_context_v1           -- trigger, flagged transaction, device, region
2. get_card_baseline_v1          -- amounts and counts to the anchor
3. get_transaction_window_v1     -- the 48 h before the anchor
4. extract_temporal_graph_features_v1
5. find_shared_origin_activity_v1 (device), when the flagged transaction has one
6. find_shared_origin_activity_v1 (region), when it has a billing region
7. find_region_anomalies_v1
8. wcc_shared_origin_v1          -- two hops, bounded, with path segments
9. calculate_case_exposure_v1    -- over the candidate episode from step 3

Retrieval adds two more (prior cases and policy), for eleven at most.

The anchor is the flagged transaction's own timestamp, read from step 1. The
review time (``as_of_ts``) is when the alert is being looked at; every query
that takes both bounds itself by the earlier, so evidence is a property of the
case rather than of when someone looked. The baseline and the exposure take a
single cutoff, and are given the anchor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evidence.feature_assembler import EPISODE_WINDOW_HOURS, episode_rows
from graph.tool_port import GraphToolPort, QueryResult

WCC_MAX_HOPS = 2


@dataclass(frozen=True)
class CaseTrigger:
    """One benchmark alert, as case_pack.csv gives it."""

    case_id: str
    flagged_txn_id: str
    card_id: str
    customer_id: str
    trigger_type: str
    trigger_text: str
    opened_at: str
    risk_score: float | None = None


class CaseCollectionError(RuntimeError):
    """The trigger cannot be investigated: its transaction is unknown or refused."""


@dataclass
class CollectedResults:
    trigger: CaseTrigger
    anchor_time: str
    #: Normalized values by assembler role.
    values: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: The QueryResult behind each role, for provenance.
    results: dict[str, QueryResult] = field(default_factory=dict)

    @property
    def flagged(self) -> dict[str, Any]:
        return (self.values["context"].get("flagged_transaction") or [{}])[0]

    @property
    def device_id(self) -> str | None:
        devices = self.values["context"].get("device") or []
        return devices[0]["device_id"] if devices else None


def collect_graph_results(port: GraphToolPort, trigger: CaseTrigger) -> CollectedResults:
    review = trigger.opened_at

    def run(role: str, name: str, params: dict[str, Any]) -> dict[str, Any]:
        result = port.run_query(name, params)
        collected.results[role] = result
        collected.values[role] = result.values
        return result.values

    context_result = port.run_query(
        "get_case_context_v1", {"flagged_txn_id": trigger.flagged_txn_id, "as_of_ts": review}
    )
    if context_result.refused:
        raise CaseCollectionError(
            f"{trigger.case_id}: {context_result.values.get('refusal_reason')}"
        )
    flagged = context_result.values["flagged_transaction"][0]
    if flagged.get("card_id") != trigger.card_id:
        raise CaseCollectionError(
            f"{trigger.case_id}: flagged transaction belongs to {flagged.get('card_id')}, "
            f"not {trigger.card_id}"
        )
    anchor = flagged["ts"]
    collected = CollectedResults(trigger=trigger, anchor_time=anchor)
    collected.results["context"] = context_result
    collected.values["context"] = context_result.values

    card = trigger.card_id
    run("baseline", "get_card_baseline_v1", {"card_id": card, "as_of_ts": anchor})
    window = run(
        "window",
        "get_transaction_window_v1",
        {
            "card_id": card,
            "anchor_ts": anchor,
            "as_of_ts": review,
            "hours_before": EPISODE_WINDOW_HOURS,
        },
    )
    run(
        "features",
        "extract_temporal_graph_features_v1",
        {"flagged_txn_id": trigger.flagged_txn_id, "as_of_ts": review},
    )
    shared = {"anchor_ts": anchor, "as_of_ts": review, "exclude_card_id": card}
    if collected.device_id:
        run(
            "shared_device",
            "find_shared_origin_activity_v1",
            {"entity_kind": "device", "entity_id": collected.device_id, **shared},
        )
    if flagged.get("addr1"):
        run(
            "shared_region",
            "find_shared_origin_activity_v1",
            {"entity_kind": "region", "entity_id": flagged["addr1"], **shared},
        )
    run(
        "region",
        "find_region_anomalies_v1",
        {"card_id": card, "flagged_txn_id": trigger.flagged_txn_id, "as_of_ts": review},
    )
    run(
        "wcc",
        "wcc_shared_origin_v1",
        {"seed_card_id": card, "anchor_ts": anchor, "as_of_ts": review, "max_hops": WCC_MAX_HOPS},
    )
    episode = [
        item["txn_id"] for item in episode_rows(window.get("window_transactions") or [], flagged)
    ]
    run("exposure", "calculate_case_exposure_v1", {"txn_ids": episode, "as_of_ts": anchor})
    return collected
