"""Write the normalized vertex and edge files to data/prepared/.

Read-only against data/raw/. Regenerable and deterministic: the same inputs
always produce byte-identical outputs, so a reload cannot silently change the
graph.

    .venv/Scripts/python scripts/prepare_graph_files.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.identifiers import build_card_table  # noqa: E402
from ingestion.prepare_graph_files import (  # noqa: E402
    build_billing_region_vertices,
    build_card_vertices,
    build_cardholder_vertices,
    build_closed_case_vertices,
    build_device_vertices,
    build_edges,
    build_email_domain_vertices,
    build_transaction_vertices,
    load_identity,
    load_transactions,
)
from retrieval.embeddings import EMBEDDING_DIMENSION, embed, to_csv_field  # noqa: E402
from retrieval.policy_chunks import all_chunks  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW = PROJECT_ROOT / "data" / "raw"
PREPARED = PROJECT_ROOT / "data" / "prepared"
REPORT_PATH = PROJECT_ROOT / "runs" / "prepared_files.json"


def _one_line(text: str) -> str:
    """Collapse a block of markdown to a single whitespace-separated line."""
    return " ".join(text.split())


def write(
    frame: pl.DataFrame, name: str, separator: str = ",", include_header: bool = False
) -> dict:
    """Write one prepared file.

    Loading-job files are written WITHOUT a header row. HEADER="true" does not
    stop TigerGraph creating a vertex whose primary id is the column name, which
    inflated every count by exactly one. No header row, no phantom vertex.

    Embedding files keep their header and use "|" between columns, because the
    vector is itself a comma-separated list and they are read by Python, not by
    a loading job.
    """
    path = PREPARED / name
    frame.write_csv(path, separator=separator, include_header=include_header)
    size = path.stat().st_size
    print(f"  {name:32s} {frame.height:>8,} rows  {size / 1e6:>7.1f} MB")
    return {"file": name, "rows": frame.height, "bytes": size}


def main() -> int:
    PREPARED.mkdir(parents=True, exist_ok=True)

    print("loading supplied files ...")
    transactions = load_transactions(RAW)
    identity = load_identity(RAW)
    cards = build_card_table(transactions)

    written: list[dict] = []

    print("\nvertices:")
    written.append(write(build_cardholder_vertices(transactions, cards), "cardholders.csv"))
    written.append(write(build_card_vertices(transactions, cards), "payment_cards.csv"))
    written.append(write(build_transaction_vertices(transactions), "transactions.csv"))
    written.append(write(build_device_vertices(identity, transactions), "device_profiles.csv"))
    written.append(write(build_email_domain_vertices(transactions), "email_domains.csv"))
    written.append(write(build_billing_region_vertices(transactions), "billing_regions.csv"))

    closed_cases = build_closed_case_vertices(RAW)
    written.append(write(closed_cases, "closed_cases.csv"))

    chunks = all_chunks()
    policy_frame = pl.DataFrame(
        {
            "chunk_id": [chunk.chunk_id for chunk in chunks],
            "source_document": [chunk.source_document for chunk in chunks],
            "anchor": [chunk.anchor for chunk in chunks],
            # A loading job treats a newline as the end of a record, so the
            # markdown body is flattened to one line. Retrieval reads it as
            # prose, and the anchor still points at the real section.
            "title": [_one_line(chunk.title) for chunk in chunks],
            "body": [_one_line(chunk.body) for chunk in chunks],
            "n_chars": [len(chunk.body) for chunk in chunks],
        }
    )
    written.append(write(policy_frame, "policy_chunks.csv"))

    print("\nedges:")
    for name, frame in build_edges(transactions, identity, RAW).items():
        written.append(write(frame, f"edge_{name}.csv"))

    print(f"\nembeddings ({EMBEDDING_DIMENSION} dimensions, deterministic):")
    case_vectors = pl.DataFrame(
        {
            "case_id": closed_cases["case_id"],
            "vector": [to_csv_field(embed(text)) for text in closed_cases["memory_text"]],
        }
    )
    written.append(
        write(case_vectors, "closed_case_embeddings.csv", separator="|", include_header=True)
    )

    chunk_vectors = pl.DataFrame(
        {
            "chunk_id": [chunk.chunk_id for chunk in chunks],
            "vector": [to_csv_field(embed(chunk.embedding_text)) for chunk in chunks],
        }
    )
    written.append(
        write(chunk_vectors, "policy_chunk_embeddings.csv", separator="|", include_header=True)
    )

    report = {
        "prepared_dir": str(PREPARED),
        "embedding_dimension": EMBEDDING_DIMENSION,
        "files": written,
        "total_bytes": sum(item["bytes"] for item in written),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\ntotal {report['total_bytes'] / 1e6:.1f} MB across {len(written)} files")
    print(f"wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
