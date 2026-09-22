"""Keep the local policy documents and the code in agreement.

The knowledge documents are copies of the supplied dataset README. If the code
and the copy drift, evidence that cites `policy:<anchor>` stops meaning what
the policy says. These tests fail on drift rather than letting it pass.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from domain.enums import (
    ALWAYS_L1_ACTIONS,
    ALWAYS_L2_ACTIONS,
    AUTO_ROUTE_ACTIONS,
    Action,
    ApprovalRoute,
    FraudPattern,
    required_route,
)

KNOWLEDGE = Path(__file__).resolve().parents[2] / "knowledge"
POLICY = KNOWLEDGE / "fraud_policy.md"
PATTERNS = KNOWLEDGE / "fraud_patterns.md"

ANCHOR = re.compile(r"^## (policy|pattern):([a-zA-Z0-9_-]+)\s*$", re.MULTILINE)


def anchors(path: Path, kind: str) -> set[str]:
    return {
        match.group(2)
        for match in ANCHOR.finditer(path.read_text(encoding="utf-8"))
        if match.group(1) == kind
    }


def test_all_ten_policy_rules_have_an_anchor():
    found = anchors(POLICY, "policy")
    missing = {f"R{number}" for number in range(1, 11)} - found
    assert not missing, f"policy document is missing anchors for {sorted(missing)}"


def test_supporting_policy_anchors_exist():
    found = anchors(POLICY, "policy")
    required = {
        "actions",
        "routing",
        "case-vs-report",
        "exposure",
        "evidence-gathering",
        "stopping",
        "explaining",
    }
    assert required <= found, f"missing {sorted(required - found)}"


def test_anchors_are_unique():
    text = POLICY.read_text(encoding="utf-8")
    found = [match.group(0) for match in ANCHOR.finditer(text)]
    assert len(found) == len(set(found)), "duplicate policy anchors would make refs ambiguous"


@pytest.mark.parametrize("action", list(Action))
def test_every_action_appears_in_the_policy_document(action: Action):
    assert f"`{action.value}`" in POLICY.read_text(encoding="utf-8")


@pytest.mark.parametrize("pattern", list(FraudPattern))
def test_every_pattern_has_a_section(pattern: FraudPattern):
    assert pattern.value in anchors(PATTERNS, "pattern")


def test_route_sets_partition_the_actions():
    """Every action belongs to exactly one routing group."""
    exposure_dependent = {Action.BLOCK_CARD}
    groups = [AUTO_ROUTE_ACTIONS, ALWAYS_L1_ACTIONS, ALWAYS_L2_ACTIONS, exposure_dependent]
    union: set[Action] = set()
    for group in groups:
        overlap = union & set(group)
        assert not overlap, f"action in two routing groups: {overlap}"
        union |= set(group)
    assert union == set(Action), f"unrouted actions: {set(Action) - union}"


def test_documented_routing_table_matches_required_route():
    """The routes named in the document are the ones the code computes."""
    documented_auto = {
        Action.ALLOW_TRANSACTION,
        Action.MONITOR_CARD,
        Action.MONITOR_CONNECTED_CARDS,
        Action.WARN_CUSTOMER,
        Action.VERIFY_WITH_CUSTOMER,
        Action.STEP_UP_AUTH,
        Action.GENERATE_REPORT,
        Action.CREATE_CASE,
        Action.ESCALATE_TO_ANALYST,
        Action.CLOSE_NO_FRAUD,
    }
    for action in documented_auto:
        assert required_route(action, 0.0) is ApprovalRoute.AUTO
        assert required_route(action, 1_000_000.0) is ApprovalRoute.AUTO

    assert required_route(Action.DECLINE_TRANSACTION, 1_000_000.0) is ApprovalRoute.L1
    assert required_route(Action.BLOCK_CARD, 2_500.0) is ApprovalRoute.L1
    assert required_route(Action.BLOCK_CARD, 2_500.01) is ApprovalRoute.L2
    assert required_route(Action.BLOCK_ALL_CARDS, 0.0) is ApprovalRoute.L2
    assert required_route(Action.FILE_REPORT, 0.0) is ApprovalRoute.L2


def test_policy_thresholds_match_settings():
    """The numbers in settings.yaml are the numbers the policy states."""
    import yaml

    settings_path = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"
    policy = yaml.safe_load(settings_path.read_text(encoding="utf-8"))["policy"]
    assert policy["case_creation_probability"] == 0.30
    assert policy["weak_signal_probability"] == 0.70
    assert policy["sar_exposure_threshold_usd"] == 1000.0
    assert policy["block_card_l2_exposure_usd"] == 2500.0
    assert policy["escalate_uncertain_exposure_usd"] == 500.0
    assert policy["no_reply_escalation_exposure_usd"] == 500.0
    assert policy["stop_high_probability"] == 0.85
    assert policy["stop_low_probability"] == 0.15
    assert policy["stop_min_independent_evidence"] == 2

    from domain.enums import BLOCK_CARD_L2_EXPOSURE_USD

    assert policy["block_card_l2_exposure_usd"] == BLOCK_CARD_L2_EXPOSURE_USD
