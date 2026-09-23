"""The append-only, hash-chained evidence ledger.

Each record's ``content_hash`` is the SHA-256 of its canonical content plus the
previous record's hash, so a record cannot be edited, dropped or reordered
without breaking every hash after it. The plan calls hash chaining optional
but cheap; what matters is that every claim has a stable id and provenance.

The content hash deliberately excludes the trace id: a rerun issues new trace
ids for identical evidence, and identical evidence must hash identically.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from evidence.models import EvidenceItem

GENESIS_HASH = "0" * 64

#: Fields that identify the call rather than the content.
_UNHASHED = frozenset({"content_hash", "previous_hash", "trace_id"})


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(fields: dict[str, Any], previous_hash: str) -> str:
    body = {key: value for key, value in fields.items() if key not in _UNHASHED}
    return hashlib.sha256((canonical_json(body) + previous_hash).encode("utf-8")).hexdigest()


class EvidenceLedger:
    """Appends items in order, assigning ids and chaining hashes."""

    def __init__(self, case_id: str):
        self.case_id = case_id
        self.items: list[EvidenceItem] = []

    @property
    def last_hash(self) -> str:
        return self.items[-1].content_hash if self.items else GENESIS_HASH

    def next_id(self) -> str:
        return f"EV-{self.case_id}-{len(self.items) + 1:03d}"

    def append(self, **fields: Any) -> EvidenceItem:
        previous = self.last_hash
        draft = EvidenceItem(
            evidence_id=self.next_id(), **fields, content_hash="", previous_hash=previous
        )
        # Hash the validated model, defaults included, so verification sees
        # exactly what was hashed.
        digest = content_hash(draft.model_dump(mode="json"), previous)
        item = draft.model_copy(update={"content_hash": digest})
        self.items.append(item)
        return item


def verify_chain(items: list[EvidenceItem]) -> list[str]:
    """Every break in the chain, or an empty list when it is intact."""
    problems = []
    previous = GENESIS_HASH
    for item in items:
        if item.previous_hash != previous:
            problems.append(f"{item.evidence_id}: previous_hash does not match the prior record")
        fields = item.model_dump(mode="json")
        if content_hash(fields, item.previous_hash) != item.content_hash:
            problems.append(f"{item.evidence_id}: content_hash does not match its content")
        previous = item.content_hash
    return problems
