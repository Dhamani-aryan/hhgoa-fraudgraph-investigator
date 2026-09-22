"""Deterministic local text embeddings for the TigerGraph vector index.

TigerGraph is the vector store and the retrieval path, which is what the
challenge requires. This module only produces the vectors that go into it.

The embedder is a hashing vectorizer with sublinear term weighting, projected
to 1536 dimensions and L2 normalized so cosine similarity is a dot product. It
is chosen for three reasons:

* Deterministic. The same text always yields the same vector, on any machine
  and with no network call, so a frozen batch is reproducible.
* No API key and no rate limit, so the twenty-case batch cannot be blocked by
  an embedding service.
* 1536 dimensions match text-embedding-3-small, so swapping in an API model
  later needs no schema migration.

It is weaker than a learned model at capturing paraphrase. That is acceptable
here because prior-case retrieval is a two-stage pipeline: structured filters
and graph features generate the candidates, and the vector score only reranks
them. Retrieval never rests on the embedding alone.
"""

from __future__ import annotations

import math
import re
from collections import Counter

EMBEDDING_DIMENSION = 1536

#: Lowercase alphanumeric runs. Keeps identifiers such as cc-0141 and c00377-k1
#: intact rather than splitting them on the hyphen.
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]*")

#: Words too common in this corpus to carry signal. Every closed-case narrative
#: contains "case" and "transaction", so they separate nothing.
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "for",
        "from",
        "had",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "there",
        "this",
        "to",
        "was",
        "were",
        "when",
        "which",
        "with",
        "case",
        "transaction",
        "transactions",
    }
)


#: Suffixes collapsed so inflections of the same word share a bucket. Without
#: this, "the customer denied the transaction" misses policy R2, which is
#: written as "Customer denies the transaction", and ranks R3 (customer
#: confirms) first -- the opposite rule.
_SUFFIXES = ("ies", "ing", "ed", "es", "s")


def stem(token: str) -> str:
    """Collapse a few English inflections.

    Only applied to plain alphabetic words longer than four characters, so
    dataset identifiers such as cc-0141 and c00377-k1 are never altered.
    """
    if len(token) <= 4 or not token.isalpha():
        return token
    # "denied" and "denies" must land on the same stem, or policy R2 (customer
    # denies) is ranked below R3 (customer confirms) for a query saying denied.
    if token.endswith("ied"):
        return token[:-3] + "y"
    if token.endswith("ies"):
        return token[:-3] + "y"
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    return [
        stem(token)
        for token in _TOKEN.findall(text.lower())
        if token not in _STOPWORDS and len(token) > 1
    ]


def _bucket(token: str, dimension: int) -> tuple[int, int]:
    """Return the bucket and the sign for a token.

    The signed hash lets collisions cancel rather than always accumulate, which
    keeps unrelated documents from drifting together.
    """
    digest = hash_token(token)
    return digest % dimension, 1 if (digest >> 32) & 1 else -1


def hash_token(token: str) -> int:
    """Stable hash. Python's hash() is salted per process, so it cannot be used."""
    import hashlib

    return int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big")


def embed(text: str, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    """Embed one document as an L2-normalized vector."""
    vector = [0.0] * dimension
    tokens = tokenize(text)
    if not tokens:
        return vector

    # Sublinear term frequency: a word repeated ten times is not ten times as
    # informative, and long analyst notes should not dominate on length alone.
    for token, count in Counter(tokens).items():
        index, sign = _bucket(token, dimension)
        vector[index] += sign * (1.0 + math.log(count))

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    """Cosine similarity of two embeddings. Both are already normalized."""
    return sum(a * b for a, b in zip(left, right, strict=True))


def to_csv_field(vector: list[float], precision: int = 6) -> str:
    """Render a vector for a TigerGraph loading job.

    The loading job splits this field on commas, so the separator must not
    appear anywhere else in the value.
    """
    return ",".join(f"{value:.{precision}f}" for value in vector)
