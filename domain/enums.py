"""Closed vocabularies taken verbatim from the supplied dataset README.

The dataset README is authority #1. Every literal in this module is copied
from its Fraud Policy and Answer Format sections. Nothing here may be extended
with a value the challenge does not define: an answer using an unknown action,
route, pattern, status, verdict or source is invalid.
"""

from __future__ import annotations

from enum import StrEnum


class CaseStatus(StrEnum):
    """Where the case stands when the agent stops."""

    OPEN = "open"
    CLOSED_FRAUD = "closed_fraud"
    CLOSED_LEGITIMATE = "closed_legitimate"
    ESCALATED = "escalated"


class Verdict(StrEnum):
    FRAUD = "fraud"
    LEGITIMATE = "legitimate"
    UNCERTAIN = "uncertain"


class FraudPattern(StrEnum):
    """The five documented patterns plus the two open values."""

    CARD_TESTING = "card_testing"
    CARD_NOT_PRESENT_FRAUD = "card_not_present_fraud"
    CARD_NOT_PRESENT_NEW_DEVICE = "card_not_present_new_device"
    OUT_OF_REGION_USE = "out_of_region_use"
    ACCOUNT_TAKEOVER = "account_takeover"
    UNDOCUMENTED = "undocumented"
    NONE = "none"


class EvidenceSource(StrEnum):
    GRAPH = "graph"
    DOCUMENT = "document"
    CUSTOMER = "customer"
    EXTERNAL = "external"


class EvidenceRequestType(StrEnum):
    CUSTOMER_VALIDATION = "customer_validation"
    STEP_UP_AUTH = "step_up_auth"
    ANALYST_INFO = "analyst_info"


class Action(StrEnum):
    """The fourteen actions the supplied policy allows, in policy order."""

    ALLOW_TRANSACTION = "ALLOW_TRANSACTION"
    DECLINE_TRANSACTION = "DECLINE_TRANSACTION"
    MONITOR_CARD = "MONITOR_CARD"
    MONITOR_CONNECTED_CARDS = "MONITOR_CONNECTED_CARDS"
    WARN_CUSTOMER = "WARN_CUSTOMER"
    VERIFY_WITH_CUSTOMER = "VERIFY_WITH_CUSTOMER"
    STEP_UP_AUTH = "STEP_UP_AUTH"
    BLOCK_CARD = "BLOCK_CARD"
    BLOCK_ALL_CARDS = "BLOCK_ALL_CARDS"
    GENERATE_REPORT = "GENERATE_REPORT"
    CREATE_CASE = "CREATE_CASE"
    FILE_REPORT = "FILE_REPORT"
    ESCALATE_TO_ANALYST = "ESCALATE_TO_ANALYST"
    CLOSE_NO_FRAUD = "CLOSE_NO_FRAUD"


class ApprovalRoute(StrEnum):
    AUTO = "auto"
    L1 = "L1"
    L2 = "L2"


class TriggerType(StrEnum):
    """Trigger types used by case_pack.csv."""

    RISK_SCORE = "risk_score"
    CUSTOMER_REPORT = "customer_report"
    ANALYST_REQUEST = "analyst_request"


#: Actions the agent may execute alone. Every other action is a recommendation
#: that waits for a named human approver.
AUTO_ROUTE_ACTIONS: frozenset[Action] = frozenset(
    {
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
)

#: Always a team-lead decision, whatever the exposure.
ALWAYS_L1_ACTIONS: frozenset[Action] = frozenset({Action.DECLINE_TRANSACTION})

#: Always a fraud-manager decision, whatever the exposure.
ALWAYS_L2_ACTIONS: frozenset[Action] = frozenset({Action.BLOCK_ALL_CARDS, Action.FILE_REPORT})

#: BLOCK_CARD is L1 at or below this exposure and L2 above it.
BLOCK_CARD_L2_EXPOSURE_USD = 2500.0


def required_route(action: Action, exposure_usd: float) -> ApprovalRoute:
    """Return the one approval route the supplied policy allows for an action.

    Routing is a property of the action and the exposure, never of the model's
    opinion. ``BLOCK_CARD`` is the only exposure-dependent action.
    """
    if action in AUTO_ROUTE_ACTIONS:
        return ApprovalRoute.AUTO
    if action in ALWAYS_L2_ACTIONS:
        return ApprovalRoute.L2
    if action in ALWAYS_L1_ACTIONS:
        return ApprovalRoute.L1
    if action is Action.BLOCK_CARD:
        return ApprovalRoute.L2 if exposure_usd > BLOCK_CARD_L2_EXPOSURE_USD else ApprovalRoute.L1
    raise ValueError(f"no route defined for action {action!r}")
