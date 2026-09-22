"""Cross-field validation rules for a case answer.

These are the checks the Pydantic models cannot make alone, because they need
the supplied dataset or the run trace. Each rule returns a list of failures;
an empty list means the rule held.

Rules are numbered to match the build plan's cross-field validation list. Rules
that need a run trace (evidence ledger, retrieval log, graph receipt, memory
manifest) take a ``RunContext``. When no trace is supplied those rules report
``skipped`` rather than passing, so an answer produced without a trace can
never look fully validated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from domain.answer_models import CaseAnswer
from domain.enums import Action, FraudPattern, Verdict, required_route
from validation.dataset_ids import EXPOSURE_TOLERANCE_USD, DatasetIndex


class Outcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    name: str
    outcome: Outcome
    failures: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is not Outcome.FAILED


@dataclass(frozen=True)
class RunContext:
    """What the investigation recorded while producing this answer.

    Supplied from ``runs/<case_id>/`` once the agent exists. Until then the
    rules that need it report ``skipped``.
    """

    #: evidence_id -> ledger record, for claim provenance
    ledger_refs: frozenset[str] | None = None
    #: policy document sections an evidence ref may cite
    policy_refs: frozenset[str] | None = None
    #: closed-case IDs prior-case retrieval actually returned
    retrieved_case_ids: frozenset[str] | None = None
    #: independence group per evidence ref, for the stopping rule
    independence_groups: dict[str, str] | None = None
    #: true only after a successful write followed by a successful read-back
    graph_write_confirmed: bool | None = None
    #: memory epoch whose cases must not appear in similar_prior_cases
    active_memory_epoch_case_ids: frozenset[str] | None = None
    #: latest source timestamp admitted per evidence ref
    evidence_max_ts: dict[str, str] | None = None
    #: evidence refs that are labelled simulated responses
    simulated_refs: frozenset[str] = frozenset()
    #: evidence that satisfies the shared-origin coordination bar
    shared_origin_supported: bool | None = None
    #: cards of this customer with confirmed fraud, for R10
    customer_confirmed_fraud_cards: frozenset[str] | None = None
    #: true when the customer's credentials are confirmed compromised, for R10
    credentials_confirmed_compromised: bool | None = None


def _result(rule_id: str, name: str, failures: list[str]) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        name=name,
        outcome=Outcome.FAILED if failures else Outcome.PASSED,
        failures=failures,
    )


def _skip(rule_id: str, name: str, detail: str) -> RuleResult:
    return RuleResult(rule_id=rule_id, name=name, outcome=Outcome.SKIPPED, detail=detail)


# --------------------------------------------------------------------------
# Rules checkable from the dataset alone
# --------------------------------------------------------------------------


def rule_01_case_id_exists(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    failures = []
    if answer.case_id not in index.benchmark_case_ids:
        failures.append(f"case_id {answer.case_id!r} is not in case_pack.csv")
    return _result("R01", "case_id exists in the case pack", failures)


def rule_02_ids_exist(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    case = answer.case
    failures = []
    for label, kind, values in (
        ("affected_txn_ids", "transaction", case.affected_txn_ids),
        (
            "first_suspicious_txn_id",
            "transaction",
            [case.first_suspicious_txn_id] if case.first_suspicious_txn_id else [],
        ),
        ("connected_card_ids", "card", case.connected_card_ids),
        ("connected_device_profiles", "device_profile", case.connected_device_profiles),
        ("similar_prior_cases", "closed_case", case.similar_prior_cases),
    ):
        unknown = index.unknown(kind, values)
        if unknown:
            failures.append(f"{label} contains IDs absent from the dataset: {unknown}")

    # Evidence entity IDs may name any dataset entity, so check against the union.
    known_any = (
        index.transaction_ids
        | index.card_ids
        | index.customer_ids
        | index.closed_case_ids
        | index.benchmark_case_ids
        | index.device_profiles
    )
    for position, item in enumerate(case.evidence):
        unknown = [value for value in item.entity_ids if value not in known_any]
        if unknown:
            failures.append(f"evidence[{position}].entity_ids not in the dataset: {unknown}")

    unknown_subjects = [value for value in answer.sar.subjects if value not in known_any]
    if unknown_subjects:
        failures.append(f"sar.subjects not in the dataset: {unknown_subjects}")
    return _result("R02", "every identifier exists in the dataset", failures)


def rule_03_probability_range(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    value = answer.case.fraud_probability
    failures = [] if 0.0 <= value <= 1.0 else [f"fraud_probability {value} is outside 0..1"]
    return _result("R03", "fraud probability within 0 and 1", failures)


def rule_04_legitimate_is_clean(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    failures = []
    if answer.case.verdict is Verdict.LEGITIMATE:
        if answer.case.affected_txn_ids:
            failures.append("legitimate verdict lists affected transactions")
        if answer.case.exposure_usd != 0:
            failures.append(f"legitimate verdict reports exposure {answer.case.exposure_usd}")
        if answer.sar.file:
            failures.append("legitimate verdict files a report")
    return _result("R04", "legitimate verdict carries no exposure and no report", failures)


def rule_05_06_pattern_description(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    case = answer.case
    failures = []
    if case.pattern is FraudPattern.UNDOCUMENTED and not case.pattern_description.strip():
        failures.append("pattern 'undocumented' has no description")
    if case.pattern is not FraudPattern.UNDOCUMENTED and case.pattern_description:
        failures.append(f"pattern {case.pattern.value!r} carries a description")
    return _result("R05-06", "pattern description matches the pattern", failures)


def rule_07_exposure_recomputed(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    expected, unknown = index.exposure_of(answer.case.affected_txn_ids)
    failures = []
    if unknown:
        failures.append(f"cannot recompute exposure, unknown transactions: {unknown}")
    tolerance = max(EXPOSURE_TOLERANCE_USD, 0.005 * len(answer.case.affected_txn_ids))
    if not unknown and abs(answer.case.exposure_usd - expected) > tolerance:
        failures.append(
            f"exposure_usd {answer.case.exposure_usd} does not match the sum of the "
            f"affected transaction amounts {expected}"
        )
    return _result("R07", "exposure equals the sum of affected amounts", failures)


def rule_08_first_suspicious_in_affected(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    case = answer.case
    failures = []
    if case.first_suspicious_txn_id and case.first_suspicious_txn_id not in case.affected_txn_ids:
        failures.append("first_suspicious_txn_id is not in affected_txn_ids")
    return _result("R08", "first suspicious transaction is among the affected", failures)


def rule_10_routes_correct(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    failures = []
    exposure = answer.case.exposure_usd
    for label, items in (
        ("initial", answer.next_best_actions.initial),
        ("final", answer.next_best_actions.final),
    ):
        for position, item in enumerate(items):
            expected = required_route(item.action, exposure)
            if item.route is not expected:
                failures.append(
                    f"{label}[{position}] {item.action.value} has route {item.route.value}, "
                    f"policy requires {expected.value} at exposure {exposure}"
                )
    return _result("R10", "every action uses the route the policy requires", failures)


def rule_11_12_sar_agrees_with_actions(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    final_actions = {item.action for item in answer.next_best_actions.final}
    failures = []
    if (Action.FILE_REPORT in final_actions) != answer.sar.file:
        failures.append(f"sar.file={answer.sar.file} disagrees with FILE_REPORT in final actions")
    if answer.sar.file and Action.CREATE_CASE not in final_actions:
        failures.append("a filed report has no CREATE_CASE behind it")
    return _result("R11-12", "report filing agrees with the final actions", failures)


def rule_13_14_sar_fields(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    sar = answer.sar
    failures = []
    if sar.file:
        if not sar.narrative.strip():
            failures.append("filed report has an empty narrative")
        if not sar.subjects:
            failures.append("filed report names no subjects")
        if sar.total_amount_usd <= 0:
            failures.append("filed report has no positive amount")
        if len(sar.activity_dates) != 2:
            failures.append("filed report does not carry exactly two activity dates")
    else:
        if sar.narrative or sar.subjects or sar.total_amount_usd or sar.activity_dates:
            failures.append("unfiled report carries narrative, subjects, amount or dates")
    return _result("R13-14", "report fields match the filing decision", failures)


def rule_16_no_request_no_change(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    failures = []
    if not answer.evidence_requests:
        initial = [item.model_dump(mode="json") for item in answer.next_best_actions.initial]
        final = [item.model_dump(mode="json") for item in answer.next_best_actions.final]
        if initial != final:
            failures.append("no evidence was requested but the actions changed")
        if answer.next_best_actions.what_changed.strip().lower() != "nothing":
            failures.append("no evidence was requested but what_changed is not 'nothing'")
    return _result("R16", "actions only move when evidence was requested", failures)


def rule_18_summary_length(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    from domain.answer_models import SUMMARY_MAX_SENTENCES, SUMMARY_MIN_SENTENCES, count_sentences

    sentences = count_sentences(answer.case.summary)
    failures = (
        []
        if SUMMARY_MIN_SENTENCES <= sentences <= SUMMARY_MAX_SENTENCES
        else [f"summary has {sentences} sentences, allowed 2 to 6"]
    )
    return _result("R18", "summary length within two to six sentences", failures)


def rule_19_narrative_length(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    from domain.answer_models import (
        NARRATIVE_MAX_SENTENCES,
        NARRATIVE_MIN_SENTENCES,
        count_sentences,
    )

    failures = []
    if answer.sar.file:
        sentences = count_sentences(answer.sar.narrative)
        if not (NARRATIVE_MIN_SENTENCES <= sentences <= NARRATIVE_MAX_SENTENCES):
            failures.append(f"filed narrative has {sentences} sentences, allowed 6 to 12")
    return _result("R19", "filed narrative length within six to twelve sentences", failures)


def rule_20_evidence_has_reference(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    failures = [
        f"evidence[{position}] has an empty ref"
        for position, item in enumerate(answer.case.evidence)
        if not item.ref.strip()
    ]
    return _result("R20", "every evidence claim carries a reference", failures)


def rule_25a_prior_cases_exclude_self(answer: CaseAnswer, index: DatasetIndex) -> RuleResult:
    """The benchmark case itself can never be its own prior case."""
    failures = []
    if answer.case_id in answer.case.similar_prior_cases:
        failures.append("similar_prior_cases contains the current case")
    benchmark_ids = [
        value for value in answer.case.similar_prior_cases if value in index.benchmark_case_ids
    ]
    if benchmark_ids:
        failures.append(f"similar_prior_cases contains benchmark cases: {benchmark_ids}")
    return _result("R25a", "prior cases exclude the current and benchmark cases", failures)


def rule_25b_prior_cases_closed_before_anchor(
    answer: CaseAnswer, index: DatasetIndex
) -> RuleResult:
    """A prior case is memory only if it closed at or before the anchor time."""
    anchor = index.benchmark_anchor_ts.get(answer.case_id)
    if anchor is None:
        return _skip("R25b", "prior cases closed before the anchor", "anchor time unknown")
    late = [
        case_id
        for case_id in answer.case.similar_prior_cases
        if (closed := index.closed_case_closed_at.get(case_id)) is not None and closed > anchor
    ]
    failures = [f"prior cases closed after the anchor {anchor}: {late}"] if late else []
    return _result("R25b", "prior cases closed before the anchor", failures)


DATASET_RULES = (
    rule_01_case_id_exists,
    rule_02_ids_exist,
    rule_03_probability_range,
    rule_04_legitimate_is_clean,
    rule_05_06_pattern_description,
    rule_07_exposure_recomputed,
    rule_08_first_suspicious_in_affected,
    rule_10_routes_correct,
    rule_11_12_sar_agrees_with_actions,
    rule_13_14_sar_fields,
    rule_16_no_request_no_change,
    rule_18_summary_length,
    rule_19_narrative_length,
    rule_20_evidence_has_reference,
    rule_25a_prior_cases_exclude_self,
    rule_25b_prior_cases_closed_before_anchor,
)


# --------------------------------------------------------------------------
# Rules that need the run trace
# --------------------------------------------------------------------------


def rule_09_prior_cases_were_retrieved(answer: CaseAnswer, run: RunContext) -> RuleResult:
    if run.retrieved_case_ids is None:
        return _skip("R09", "prior cases were actually retrieved", "no retrieval log supplied")
    unseen = [
        case_id
        for case_id in answer.case.similar_prior_cases
        if case_id not in run.retrieved_case_ids
    ]
    failures = [f"cited prior cases retrieval never returned: {unseen}"] if unseen else []
    return _result("R09", "prior cases were actually retrieved", failures)


def rule_15_block_all_cards_justified(answer: CaseAnswer, run: RunContext) -> RuleResult:
    uses_block_all = any(
        item.action is Action.BLOCK_ALL_CARDS
        for items in (answer.next_best_actions.initial, answer.next_best_actions.final)
        for item in items
    )
    if not uses_block_all:
        return _result("R15", "BLOCK_ALL_CARDS satisfies R10", [])
    if run.customer_confirmed_fraud_cards is None and run.credentials_confirmed_compromised is None:
        return _skip("R15", "BLOCK_ALL_CARDS satisfies R10", "no R10 evidence supplied")
    cards = run.customer_confirmed_fraud_cards or frozenset()
    compromised = bool(run.credentials_confirmed_compromised)
    failures = []
    if len(cards) < 2 and not compromised:
        failures.append(
            "BLOCK_ALL_CARDS requires two of the customer's cards showing confirmed fraud "
            "or confirmed compromised credentials (R10)"
        )
    return _result("R15", "BLOCK_ALL_CARDS satisfies R10", failures)


def rule_17_graph_write_confirmed(answer: CaseAnswer, run: RunContext) -> RuleResult:
    if not answer.case.written_to_graph:
        return _result("R17", "written_to_graph rests on a real read-back", [])
    if run.graph_write_confirmed is None:
        return _skip(
            "R17",
            "written_to_graph rests on a real read-back",
            "no graph receipt supplied, so the claim is unverified",
        )
    failures = (
        []
        if run.graph_write_confirmed
        else ["written_to_graph is true but no successful read-back was recorded"]
    )
    return _result("R17", "written_to_graph rests on a real read-back", failures)


def rule_21_refs_resolve(answer: CaseAnswer, run: RunContext) -> RuleResult:
    if run.ledger_refs is None and run.policy_refs is None:
        return _skip("R21", "evidence references resolve", "no evidence ledger supplied")
    allowed = (run.ledger_refs or frozenset()) | (run.policy_refs or frozenset())
    unresolved = [item.ref for item in answer.case.evidence if item.ref not in allowed]
    failures = (
        [f"evidence refs resolve to no ledger record or policy section: {unresolved}"]
        if unresolved
        else []
    )
    return _result("R21", "evidence references resolve", failures)


def rule_22_no_future_evidence(answer: CaseAnswer, run: RunContext) -> RuleResult:
    if run.evidence_max_ts is None:
        return _skip("R22", "no evidence crosses the case cutoff", "no ledger timestamps supplied")
    anchor = run.evidence_max_ts.get("__anchor__")
    if anchor is None:
        return _skip("R22", "no evidence crosses the case cutoff", "no anchor time in the ledger")
    late = [
        ref
        for ref, max_ts in run.evidence_max_ts.items()
        if ref != "__anchor__" and ref not in run.simulated_refs and max_ts > anchor
    ]
    failures = [f"evidence newer than the anchor {anchor}: {late}"] if late else []
    return _result("R22", "no evidence crosses the case cutoff", failures)


def rule_23_two_independent_groups(answer: CaseAnswer, run: RunContext) -> RuleResult:
    if run.independence_groups is None:
        return _skip(
            "R23", "stopping rests on two independence groups", "no independence groups supplied"
        )
    groups = {
        run.independence_groups.get(item.ref)
        for item in answer.case.evidence
        if run.independence_groups.get(item.ref)
    }
    probability = answer.case.fraud_probability
    decisive = probability >= 0.85 or probability <= 0.15
    failures = []
    if decisive and len(groups) < 2:
        failures.append(
            f"probability {probability} is decisive but the evidence spans only "
            f"{len(groups)} independence group(s)"
        )
    return _result("R23", "stopping rests on two independence groups", failures)


def rule_24_shared_origin_supported(answer: CaseAnswer, run: RunContext) -> RuleResult:
    claims_shared_origin = bool(answer.case.connected_card_ids) or any(
        item.action is Action.MONITOR_CONNECTED_CARDS for item in answer.next_best_actions.final
    )
    if not claims_shared_origin:
        return _result("R24", "shared-origin claims meet the coordination bar", [])
    if run.shared_origin_supported is None:
        return _skip(
            "R24",
            "shared-origin claims meet the coordination bar",
            "no shared-origin evidence summary supplied",
        )
    failures = (
        []
        if run.shared_origin_supported
        else [
            "a shared-origin claim needs time-local multi-card activity plus fraud "
            "enrichment or a rare shared entity; raw degree is not enough"
        ]
    )
    return _result("R24", "shared-origin claims meet the coordination bar", failures)


def rule_25c_memory_epoch_excluded(answer: CaseAnswer, run: RunContext) -> RuleResult:
    if run.active_memory_epoch_case_ids is None:
        return _skip("R25c", "active memory epoch excluded", "no memory manifest supplied")
    leaked = [
        case_id
        for case_id in answer.case.similar_prior_cases
        if case_id in run.active_memory_epoch_case_ids
    ]
    failures = [f"prior cases from the active benchmark epoch: {leaked}"] if leaked else []
    return _result("R25c", "active memory epoch excluded", failures)


RUN_RULES = (
    rule_09_prior_cases_were_retrieved,
    rule_15_block_all_cards_justified,
    rule_17_graph_write_confirmed,
    rule_21_refs_resolve,
    rule_22_no_future_evidence,
    rule_23_two_independent_groups,
    rule_24_shared_origin_supported,
    rule_25c_memory_epoch_excluded,
)


def evaluate(
    answer: CaseAnswer, index: DatasetIndex, run: RunContext | None = None
) -> list[RuleResult]:
    """Run every cross-field rule and return one result per rule."""
    results = [rule(answer, index) for rule in DATASET_RULES]
    context = run or RunContext()
    results.extend(rule(answer, context) for rule in RUN_RULES)
    return results
