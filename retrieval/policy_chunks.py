"""Split the local knowledge documents into retrievable policy chunks.

One chunk per anchored section, so a retrieved chunk always resolves to a real
document section. ``chunk_id`` is the same anchor an evidence ``ref`` cites --
``policy:R2``, ``pattern:card_testing`` -- which is what lets validator rule
R21 check a citation instead of trusting the model's word for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"

#: Files carrying anchored sections, and the anchor prefix each one uses.
CHUNK_SOURCES = {
    "fraud_policy.md": "policy",
    "fraud_patterns.md": "pattern",
}

_SECTION = re.compile(r"^## ([a-z]+):([a-zA-Z0-9_-]+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class PolicyChunk:
    chunk_id: str
    source_document: str
    anchor: str
    title: str
    body: str

    @property
    def embedding_text(self) -> str:
        return f"{self.title}\n{self.body}"


def _title_of(body: str, anchor: str) -> str:
    """First bolded phrase or first sentence, else the anchor itself."""
    bold = re.search(r"\*\*(.+?)\*\*", body)
    if bold:
        return bold.group(1).strip().rstrip(".")
    first_line = next((line.strip() for line in body.splitlines() if line.strip()), "")
    if first_line:
        return first_line[:80].rstrip(".")
    return anchor


def chunks_from(path: Path, expected_prefix: str) -> list[PolicyChunk]:
    text = path.read_text(encoding="utf-8")
    matches = list(_SECTION.finditer(text))
    chunks: list[PolicyChunk] = []
    for position, match in enumerate(matches):
        prefix, anchor = match.group(1), match.group(2)
        if prefix != expected_prefix:
            continue
        start = match.end()
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        chunks.append(
            PolicyChunk(
                chunk_id=f"{prefix}:{anchor}",
                source_document=path.name,
                anchor=anchor,
                title=_title_of(body, anchor),
                body=body,
            )
        )
    return chunks


def all_chunks(knowledge_dir: Path | None = None) -> list[PolicyChunk]:
    knowledge_dir = knowledge_dir or KNOWLEDGE_DIR
    chunks: list[PolicyChunk] = []
    for filename, prefix in CHUNK_SOURCES.items():
        path = knowledge_dir / filename
        if path.exists():
            chunks.extend(chunks_from(path, prefix))
    return sorted(chunks, key=lambda chunk: chunk.chunk_id)
