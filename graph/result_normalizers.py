"""Turn TigerGraph query results into plain Python.

Every adapter -- MCP or the direct client -- returns results through here, so
both produce the same shape and the investigation code never depends on which
path fetched the evidence.

Two TigerGraph conventions make raw results awkward:

* ``PRINT acc[acc.attr]`` names each attribute after the *accumulator*, not the
  PRINT alias, so keys arrive as ``window.txn_id`` even when the block is named
  ``window_transactions``. The prefix is stripped.
* A result is a list of blocks, each a dict of one or more named values, and a
  vertex set arrives as ``{"v_id": ..., "attributes": {...}}``.
"""

from __future__ import annotations

from typing import Any


def strip_prefix(key: str) -> str:
    """``window.txn_id`` -> ``txn_id``. A key with no prefix is unchanged."""
    return key.split(".", 1)[-1]


def normalize_row(item: Any) -> Any:
    """Flatten one vertex row to a plain dict.

    Only a row shaped ``{"v_id": ..., "attributes": {...}}`` is rewritten.
    Every other value is returned untouched, and that restraint is deliberate:
    a MapAccum printed by a query is a plain dict whose KEYS are data, not
    aliased attribute names. Stripping prefixes from it turned the region
    histogram {"327.0": 1, "325.0": 10, ...} into {"0": 7}, because every key
    was split on its first dot and then collapsed.
    """
    if not isinstance(item, dict):
        return item
    attributes = item.get("attributes")
    if not isinstance(attributes, dict):
        return item
    row = {strip_prefix(key): value for key, value in attributes.items()}
    # Keep the vertex id, which is often the only place the primary key appears
    # when a query prints a subset of attributes.
    if "v_id" in item and "v_id" not in row:
        row["v_id"] = item["v_id"]
    return row


def normalize_block(value: Any) -> Any:
    if isinstance(value, list):
        return [normalize_row(item) for item in value]
    return normalize_row(value) if isinstance(value, dict) else value


def normalize_result(result: Any) -> dict[str, Any]:
    """Merge a query's blocks into one dict of named results.

    A query printing several blocks returns several dicts. They are merged in
    order; a later block with the same name wins, which does not happen in this
    project's queries because every PRINT alias is distinct.
    """
    merged: dict[str, Any] = {}
    if not result:
        return merged
    blocks = result if isinstance(result, list) else [result]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        for name, value in block.items():
            merged[name] = normalize_block(value)
    return merged


def rows(result: Any, block: str | None = None) -> list[dict]:
    """Rows of one named block, or of the first list-valued block."""
    merged = normalize_result(result)
    if block is not None:
        value = merged.get(block, [])
        return value if isinstance(value, list) else [value]
    for value in merged.values():
        if isinstance(value, list):
            return value
    return []


def first(result: Any, block: str) -> dict | None:
    """The first row of a named block, or None when the block is empty."""
    found = rows(result, block)
    return found[0] if found else None


def scalar(result: Any, name: str, default: Any = None) -> Any:
    """A scalar printed by a query, such as a count or a total."""
    return normalize_result(result).get(name, default)
