"""The exact answer contract for one benchmark case.

Field names, types and nesting are copied from the supplied dataset README's
Answer Format section. One file per case at ``cases/<case_id>.json``.

These models enforce what can be checked from the answer alone: types, closed
vocabularies, ranges, sentence counts, and the internal agreements the README
states (SAR fields agree with ``sar.file``; a pattern description is required
only for ``undocumented``; a legitimate verdict carries no affected
transactions, no exposure and no report).

Checks that need the dataset or the run trace -- that an ID exists, that
exposure equals the sum of the affected amounts, that a retrieved prior case
was really retrieved, that the graph write happened -- live in ``validation``.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domain.enums import (
    Action,
    ApprovalRoute,
    CaseStatus,
    EvidenceRequestType,
    EvidenceSource,
    FraudPattern,
    Verdict,
)

#: Sentence terminators used for the README's sentence-count requirements.
_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")

SUMMARY_MIN_SENTENCES = 2
SUMMARY_MAX_SENTENCES = 6
NARRATIVE_MIN_SENTENCES = 6
NARRATIVE_MAX_SENTENCES = 12


def count_sentences(text: str) -> int:
    """Count terminated sentences in a block of prose.

    A trailing fragment with no terminator is counted, so a single unpunctuated
    line still reads as one sentence rather than zero.
    """
    stripped = text.strip()
    if not stripped:
        return 0
    terminated = len(_SENTENCE_END.findall(stripped))
    if not _SENTENCE_END.search(stripped[-2:]):
        terminated += 1
    return terminated


class StrictModel(BaseModel):
    """Reject unknown fields so a renamed key cannot pass silently."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class Evidence(StrictModel):
    """One claim the case rests on, with where it came from."""

    claim: str = Field(min_length=1)
    source: EvidenceSource
    ref: str = Field(min_length=1, description="query name, document section, or request id")
    entity_ids: list[str] = Field(default_factory=list)


class EvidenceRequest(StrictModel):
    """A controlled request for more evidence and the response assumed for it.

    The challenge supplies no customer or analyst replies, so ``assumed_response``
    is a simulated answer and must say so plainly.
    """

    type: EvidenceRequestType
    asked_after_step: int = Field(ge=0)
    assumed_response: str = Field(min_length=1)


class ActionRecommendation(StrictModel):
    action: Action
    route: ApprovalRoute
    reason: str = Field(min_length=1, description="cites the policy rule number")


class NextBestActions(StrictModel):
    initial: list[ActionRecommendation] = Field(min_length=1)
    final: list[ActionRecommendation] = Field(min_length=1)
    what_changed: str = Field(min_length=1)


class SuspiciousActivityReport(StrictModel):
    """The regulatory filing. Present on every answer; filed only when policy says so."""

    file: bool
    reason: str = Field(min_length=1)
    narrative: str = ""
    subjects: list[str] = Field(default_factory=list)
    total_amount_usd: float = Field(default=0.0, ge=0.0)
    activity_dates: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_filing_consistency(self) -> SuspiciousActivityReport:
        if self.file:
            sentences = count_sentences(self.narrative)
            if not (NARRATIVE_MIN_SENTENCES <= sentences <= NARRATIVE_MAX_SENTENCES):
                raise ValueError(
                    f"a filed SAR narrative must be {NARRATIVE_MIN_SENTENCES} to "
                    f"{NARRATIVE_MAX_SENTENCES} sentences, found {sentences}"
                )
            if not self.subjects:
                raise ValueError("a filed SAR must name its subjects")
            if self.total_amount_usd <= 0:
                raise ValueError("a filed SAR must carry a positive total_amount_usd")
            if len(self.activity_dates) != 2:
                raise ValueError("a filed SAR must carry exactly two activity dates")
            for value in self.activity_dates:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError(f"activity date {value!r} is not YYYY-MM-DD")
            if self.activity_dates[0] > self.activity_dates[1]:
                raise ValueError("SAR activity dates must run first then last")
            return self

        if self.narrative:
            raise ValueError("an unfiled SAR must have an empty narrative")
        if self.subjects:
            raise ValueError("an unfiled SAR must have no subjects")
        if self.total_amount_usd != 0:
            raise ValueError("an unfiled SAR must have total_amount_usd 0")
        if self.activity_dates:
            raise ValueError("an unfiled SAR must have no activity dates")
        return self


class CaseRecord(StrictModel):
    """Part 1: the bank's internal record of the investigation."""

    status: CaseStatus
    verdict: Verdict
    fraud_probability: float = Field(ge=0.0, le=1.0)
    pattern: FraudPattern
    pattern_description: str = ""
    affected_txn_ids: list[str] = Field(default_factory=list)
    first_suspicious_txn_id: str = ""
    connected_card_ids: list[str] = Field(default_factory=list)
    connected_device_profiles: list[str] = Field(default_factory=list)
    exposure_usd: float = Field(ge=0.0)
    evidence: list[Evidence] = Field(min_length=1)
    similar_prior_cases: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)
    written_to_graph: bool
    graph_case_id: str = ""

    @model_validator(mode="after")
    def _check_case_consistency(self) -> CaseRecord:
        if self.pattern is FraudPattern.UNDOCUMENTED:
            if not self.pattern_description.strip():
                raise ValueError("pattern 'undocumented' requires a pattern_description")
        elif self.pattern_description:
            raise ValueError(
                f"pattern {self.pattern.value!r} requires an empty pattern_description"
            )

        sentences = count_sentences(self.summary)
        if not (SUMMARY_MIN_SENTENCES <= sentences <= SUMMARY_MAX_SENTENCES):
            raise ValueError(
                f"summary must be {SUMMARY_MIN_SENTENCES} to {SUMMARY_MAX_SENTENCES} "
                f"sentences, found {sentences}"
            )

        if self.first_suspicious_txn_id and (
            self.first_suspicious_txn_id not in self.affected_txn_ids
        ):
            raise ValueError("first_suspicious_txn_id must appear in affected_txn_ids")

        if self.verdict is Verdict.LEGITIMATE:
            if self.affected_txn_ids:
                raise ValueError("a legitimate verdict must have no affected transactions")
            if self.exposure_usd != 0:
                raise ValueError("a legitimate verdict must have zero exposure")

        if self.written_to_graph and not self.graph_case_id:
            raise ValueError("written_to_graph=true requires a graph_case_id")
        if self.graph_case_id and not self.written_to_graph:
            raise ValueError("graph_case_id may only be set once the write succeeded")

        if len(set(self.affected_txn_ids)) != len(self.affected_txn_ids):
            raise ValueError("affected_txn_ids must not repeat a transaction")
        return self


class CaseAnswer(StrictModel):
    """The complete answer file for one benchmark case."""

    case_id: str = Field(min_length=1)
    case: CaseRecord
    evidence_requests: list[EvidenceRequest] = Field(default_factory=list)
    next_best_actions: NextBestActions
    sar: SuspiciousActivityReport
    stop_reason: str = Field(min_length=1)
    tool_calls: int = Field(ge=0)
    tokens: int = Field(ge=0)
    latency_s: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _check_answer_consistency(self) -> CaseAnswer:
        final_actions = {item.action for item in self.next_best_actions.final}

        # The README states sar.file must agree with FILE_REPORT in final actions.
        files_report = Action.FILE_REPORT in final_actions
        if files_report != self.sar.file:
            raise ValueError(
                f"sar.file={self.sar.file} disagrees with FILE_REPORT in final actions "
                f"({files_report})"
            )
        # A report always has a case behind it.
        if self.sar.file and Action.CREATE_CASE not in final_actions:
            raise ValueError("a filed SAR requires CREATE_CASE in the final actions")

        if self.case.verdict is Verdict.LEGITIMATE and self.sar.file:
            raise ValueError("a legitimate verdict must not file a report")

        # If nothing was requested, the recommendation cannot have moved.
        if not self.evidence_requests:
            initial = [item.model_dump() for item in self.next_best_actions.initial]
            final = [item.model_dump() for item in self.next_best_actions.final]
            if initial != final:
                raise ValueError(
                    "no evidence was requested, so final actions must equal initial actions"
                )
            if self.next_best_actions.what_changed.strip().lower() != "nothing":
                raise ValueError(
                    "no evidence was requested, so what_changed must be exactly 'nothing'"
                )
        return self
