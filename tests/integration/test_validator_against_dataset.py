"""Run the validator against the real supplied dataset index.

Skipped when ``data/raw/`` is not populated, so the suite still runs on a
clean clone without the (git-ignored) source files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.answer_models import CaseAnswer
from validation.answer_validator import validate_answer, validate_directory
from validation.cross_field_rules import Outcome
from validation.dataset_ids import load_dataset_index

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW = PROJECT_ROOT / "data" / "raw"
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "valid_answer.json"

REQUIRED = ("transactions.csv", "identity.csv", "closed_cases_history.csv", "case_pack.csv")

pytestmark = pytest.mark.skipif(
    not all((RAW / name).exists() for name in REQUIRED),
    reason="supplied dataset not present in data/raw/",
)


@pytest.fixture(scope="module")
def index():
    return load_dataset_index()


def test_index_matches_the_dataset_readme_counts(index):
    assert len(index.transaction_amounts) == 590742
    assert len(index.closed_case_ids) == 5565
    assert len(index.benchmark_case_ids) == 20
    assert len(index.customer_ids) == 13553
    assert len(index.card_ids) == 14317


def test_every_benchmark_case_has_an_anchor_time(index):
    assert len(index.benchmark_anchor_ts) == 20
    assert all(value for value in index.benchmark_anchor_ts.values())


def test_fixture_identifiers_all_exist_in_the_real_dataset(index):
    """The contract fixture must use real IDs, not invented ones."""
    answer = CaseAnswer.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    report = validate_answer(answer, index)
    id_rule = next(rule for rule in report.rules if rule["rule_id"] == "R02")
    assert id_rule["outcome"] == Outcome.PASSED, id_rule["failures"]


def test_fixture_exposure_recomputes_against_the_real_amounts(index):
    answer = CaseAnswer.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    report = validate_answer(answer, index)
    exposure_rule = next(rule for rule in report.rules if rule["rule_id"] == "R07")
    assert exposure_rule["outcome"] == Outcome.PASSED, exposure_rule["failures"]

    recomputed, unknown = index.exposure_of(answer.case.affected_txn_ids)
    assert unknown == []
    assert recomputed == pytest.approx(answer.case.exposure_usd, abs=0.01)


def test_empty_cases_directory_reports_all_twenty_missing(index, tmp_path):
    report = validate_directory(tmp_path, index)
    assert report["files_found"] == 0
    assert len(report["missing_case_ids"]) == 20
    assert report["all_valid"] is False
