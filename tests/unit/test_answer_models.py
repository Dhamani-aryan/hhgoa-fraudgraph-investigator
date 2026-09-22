"""Schema tests for the exact answer contract.

Every invalid fixture in ``tests/fixtures/invalid/`` must be rejected, and the
valid contract fixture must parse and round-trip unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from domain.answer_models import CaseAnswer, count_sentences
from domain.enums import Action, ApprovalRoute, required_route

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
VALID = FIXTURES / "valid_answer.json"
INVALID_DIR = FIXTURES / "invalid"

INVALID_FILES = sorted(INVALID_DIR.glob("*.json"))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_valid_fixture_parses():
    answer = CaseAnswer.model_validate(load(VALID))
    assert answer.case_id == "HHG-017"
    assert answer.case.exposure_usd == pytest.approx(300.14)
    assert answer.sar.file is False
    assert len(answer.case.evidence) == 3


def test_valid_fixture_round_trips():
    """Dumping and re-parsing must not change any field."""
    original = load(VALID)
    answer = CaseAnswer.model_validate(original)
    reparsed = CaseAnswer.model_validate(answer.model_dump(mode="json"))
    assert reparsed == answer


@pytest.mark.parametrize("path", INVALID_FILES, ids=[p.stem for p in INVALID_FILES])
def test_invalid_fixture_is_rejected(path: Path):
    with pytest.raises(ValidationError):
        CaseAnswer.model_validate(load(path))


def test_invalid_fixture_set_is_not_empty():
    """Guards against the parametrised test silently passing on zero cases."""
    assert len(INVALID_FILES) >= 25


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0),
        ("One sentence.", 1),
        ("One sentence without a stop", 1),
        ("First. Second. Third.", 3),
        ("Question? Yes! Done.", 3),
    ],
)
def test_count_sentences(text: str, expected: int):
    assert count_sentences(text) == expected


@pytest.mark.parametrize(
    ("action", "exposure", "expected"),
    [
        (Action.CREATE_CASE, 0.0, ApprovalRoute.AUTO),
        (Action.VERIFY_WITH_CUSTOMER, 99999.0, ApprovalRoute.AUTO),
        (Action.CLOSE_NO_FRAUD, 0.0, ApprovalRoute.AUTO),
        (Action.DECLINE_TRANSACTION, 0.0, ApprovalRoute.L1),
        (Action.DECLINE_TRANSACTION, 99999.0, ApprovalRoute.L1),
        (Action.BLOCK_CARD, 0.0, ApprovalRoute.L1),
        (Action.BLOCK_CARD, 2500.0, ApprovalRoute.L1),
        (Action.BLOCK_CARD, 2500.01, ApprovalRoute.L2),
        (Action.BLOCK_ALL_CARDS, 0.0, ApprovalRoute.L2),
        (Action.FILE_REPORT, 0.0, ApprovalRoute.L2),
    ],
)
def test_required_route(action: Action, exposure: float, expected: ApprovalRoute):
    assert required_route(action, exposure) is expected


def test_every_action_has_a_route():
    for action in Action:
        assert required_route(action, 0.0) in set(ApprovalRoute)
