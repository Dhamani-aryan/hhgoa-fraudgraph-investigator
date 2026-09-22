"""Validate one answer file, or the whole cases/ directory.

Two layers run in order:

1. The Pydantic contract in ``domain.answer_models`` -- shape, vocabularies,
   ranges and the agreements an answer can check about itself.
2. The cross-field rules in ``validation.cross_field_rules`` -- everything that
   needs the supplied dataset or the run trace.

A rule that needs a run trace and has none reports ``skipped``. A report with
skipped rules is not a passing submission report: ``ready_for_submission`` is
true only when every rule passed and none was skipped.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pydantic import ValidationError

from domain.answer_models import CaseAnswer
from validation.cross_field_rules import Outcome, RuleResult, RunContext, evaluate
from validation.dataset_ids import DatasetIndex, load_dataset_index


@dataclass
class AnswerReport:
    path: str
    case_id: str | None
    schema_valid: bool
    schema_errors: list[str] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)

    @property
    def failed_rules(self) -> list[dict]:
        return [rule for rule in self.rules if rule["outcome"] == Outcome.FAILED]

    @property
    def skipped_rules(self) -> list[dict]:
        return [rule for rule in self.rules if rule["outcome"] == Outcome.SKIPPED]

    @property
    def valid(self) -> bool:
        """Schema holds and no cross-field rule failed."""
        return self.schema_valid and not self.failed_rules

    @property
    def ready_for_submission(self) -> bool:
        """Valid and fully checked: nothing was skipped for want of a trace."""
        return self.valid and not self.skipped_rules


def _rule_to_dict(result: RuleResult) -> dict:
    payload = asdict(result)
    payload["outcome"] = result.outcome.value
    return payload


def _schema_errors(error: ValidationError) -> list[str]:
    messages = []
    for item in error.errors():
        location = ".".join(str(part) for part in item.get("loc", ())) or "<root>"
        messages.append(f"{location}: {item.get('msg')}")
    return messages


def validate_answer(
    answer: CaseAnswer,
    index: DatasetIndex,
    run: RunContext | None = None,
    path: str = "<memory>",
) -> AnswerReport:
    results = evaluate(answer, index, run)
    return AnswerReport(
        path=path,
        case_id=answer.case_id,
        schema_valid=True,
        rules=[_rule_to_dict(result) for result in results],
    )


def validate_file(path: Path, index: DatasetIndex, run: RunContext | None = None) -> AnswerReport:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return AnswerReport(
            path=str(path),
            case_id=None,
            schema_valid=False,
            schema_errors=[f"file is not valid JSON: {error}"],
        )

    try:
        answer = CaseAnswer.model_validate(payload)
    except ValidationError as error:
        return AnswerReport(
            path=str(path),
            case_id=payload.get("case_id") if isinstance(payload, dict) else None,
            schema_valid=False,
            schema_errors=_schema_errors(error),
        )

    report = validate_answer(answer, index, run, path=str(path))
    # The filename must be the case id, so a misfiled answer is caught.
    if path.stem != answer.case_id:
        report.schema_errors.append(
            f"filename {path.name!r} does not match case_id {answer.case_id!r}"
        )
        report.schema_valid = False
    return report


def validate_directory(
    cases_dir: Path,
    index: DatasetIndex | None = None,
    runs: dict[str, RunContext] | None = None,
) -> dict:
    """Validate every answer in a directory against the expected case set."""
    index = index or load_dataset_index()
    runs = runs or {}

    files = sorted(cases_dir.glob("*.json"))
    reports = [validate_file(path, index, runs.get(path.stem)) for path in files]

    found_ids = {report.case_id for report in reports if report.case_id}
    expected_ids = set(index.benchmark_case_ids)

    return {
        "cases_dir": str(cases_dir),
        "expected_case_count": len(expected_ids),
        "files_found": len(files),
        "missing_case_ids": sorted(expected_ids - found_ids),
        "unexpected_case_ids": sorted(found_ids - expected_ids),
        "reports": [
            asdict(report)
            | {
                "valid": report.valid,
                "ready_for_submission": report.ready_for_submission,
            }
            for report in reports
        ],
        "all_valid": bool(reports)
        and all(report.valid for report in reports)
        and not (expected_ids - found_ids)
        and not (found_ids - expected_ids)
        and len(files) == len(expected_ids),
        "all_ready_for_submission": bool(reports)
        and all(report.ready_for_submission for report in reports)
        and not (expected_ids - found_ids)
        and not (found_ids - expected_ids)
        and len(files) == len(expected_ids),
    }
