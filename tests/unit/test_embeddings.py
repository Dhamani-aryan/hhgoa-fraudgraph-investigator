"""Tests for the deterministic embedder and the policy chunker.

Determinism is the property that matters: a frozen batch must reproduce, so the
same text has to give the same vector on any machine and in any process.
"""

from __future__ import annotations

import math
import subprocess
import sys

import pytest

from retrieval.embeddings import (
    EMBEDDING_DIMENSION,
    cosine,
    embed,
    to_csv_field,
    tokenize,
)
from retrieval.policy_chunks import all_chunks

CARD_TESTING = (
    "three small online authorizations under five dollars within an hour "
    "followed by a larger purchase, card testing on a stolen number"
)
TRAVEL = (
    "cardholder used the card in person in a new billing region for several "
    "consecutive days while no activity continued at home, consistent with travel"
)


def test_dimension_and_normalization():
    vector = embed(CARD_TESTING)
    assert len(vector) == EMBEDDING_DIMENSION
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, abs_tol=1e-9)


def test_same_text_gives_the_same_vector():
    assert embed(CARD_TESTING) == embed(CARD_TESTING)


def test_deterministic_across_processes():
    """Python's hash() is salted per process; the embedder must not use it."""
    code = (
        "import sys; sys.path.insert(0, '.');"
        "from retrieval.embeddings import embed;"
        f"print(round(sum(embed({CARD_TESTING!r})), 10))"
    )
    first = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    second = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert first == second


def test_empty_text_gives_a_zero_vector():
    vector = embed("")
    assert len(vector) == EMBEDDING_DIMENSION
    assert not any(vector)


def test_related_text_scores_above_unrelated():
    query = embed("card testing small authorizations then a larger purchase")
    assert cosine(query, embed(CARD_TESTING)) > cosine(query, embed(TRAVEL))


def test_self_similarity_is_one():
    vector = embed(CARD_TESTING)
    assert math.isclose(cosine(vector, vector), 1.0, abs_tol=1e-9)


def test_tokenizer_keeps_dataset_identifiers_intact():
    tokens = tokenize("Case CC-0141 on card C00377-K1 involved 3450629")
    assert "cc-0141" in tokens
    assert "c00377-k1" in tokens
    assert "3450629" in tokens


def test_tokenizer_drops_corpus_stopwords():
    """Every narrative says 'case' and 'transaction', so they separate nothing."""
    tokens = tokenize("the case and the transaction were on a card")
    assert "case" not in tokens
    assert "transaction" not in tokens
    assert "card" in tokens


def test_csv_field_has_one_value_per_dimension():
    field = to_csv_field(embed(CARD_TESTING))
    assert len(field.split(",")) == EMBEDDING_DIMENSION


# --- policy chunks ---------------------------------------------------------


def test_every_policy_rule_becomes_a_chunk():
    ids = {chunk.chunk_id for chunk in all_chunks()}
    for number in range(1, 11):
        assert f"policy:R{number}" in ids


def test_pattern_chunks_exist():
    ids = {chunk.chunk_id for chunk in all_chunks()}
    assert "pattern:card_testing" in ids
    assert "pattern:account_takeover" in ids


def test_chunk_ids_are_unique():
    ids = [chunk.chunk_id for chunk in all_chunks()]
    assert len(ids) == len(set(ids))


def test_chunks_carry_a_body_and_a_title():
    for chunk in all_chunks():
        assert chunk.body.strip(), f"{chunk.chunk_id} has an empty body"
        assert chunk.title.strip(), f"{chunk.chunk_id} has an empty title"


@pytest.mark.parametrize(
    ("query", "expected_chunk"),
    [
        ("three tiny online authorizations then a bigger purchase", "pattern:card_testing"),
        ("the customer denied making the transaction", "policy:R2"),
        ("never block every card the customer holds", "policy:R10"),
    ],
)
def test_policy_retrieval_ranks_the_right_chunk_first(query: str, expected_chunk: str):
    """The same scoring TigerGraph applies, checked locally without a server."""
    query_vector = embed(query)
    ranked = sorted(
        all_chunks(),
        key=lambda chunk: cosine(query_vector, embed(chunk.embedding_text)),
        reverse=True,
    )
    assert ranked[0].chunk_id == expected_chunk
