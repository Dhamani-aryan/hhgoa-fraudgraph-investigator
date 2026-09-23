"""GraphToolPort: the one narrow interface the evidence builder reads the graph through.

Three adapters implement it and return the same canonical structure:

* :class:`MCPGraphToolPort` -- the primary runtime path, through the official
  TigerGraph MCP server (:mod:`graph.mcp_client`).
* :class:`DirectGraphToolPort` -- an emergency/development fallback that calls
  the same installed queries through pyTigerGraph.
* :class:`FallbackGraphToolPort` -- MCP first, falling back to direct only when
  MCP is unavailable, and saying so.

The port exposes ONE operation, :meth:`GraphToolPort.run_query`, over a fixed
allowlist of installed READ queries (:data:`READ_QUERIES`). There is no way to
send GSQL text, name an arbitrary query, or reach the write path:
``write_investigation_case_v1`` is refused by name, and the only write in the
project remains :func:`graph.case_writer.write_case`.

Every call, on either path:

* is checked against the allowlist, its required parameters, its parameter
  caps and its temporal parameters before anything is sent;
* consumes one unit of a shared :class:`CallBudget` (12 per evidence package,
  from the plan), including a call that fails and a fallback retry;
* runs under a timeout;
* is normalized through :func:`graph.result_normalizers.normalize_result`, so
  both adapters hand back identical structures;
* leaves a :class:`CallRecord` with the tool, redacted parameters, duration,
  outcome, result size and a trace id. A query vector is logged as its
  dimension and SHA-256, never as values.

Fallback classification
-----------------------
Only :class:`GraphUnavailableError` -- transport failure, timeout, a server that
cannot start, a workspace that is resuming -- triggers the direct fallback.
Invalid or over-cap parameters, a forbidden query, a query's own refusal
(``refused=true`` is data, not an error), a semantic query failure and a
temporal-parameter failure never fall back: the direct path would receive the
same request and deserve the same answer, and retrying it elsewhere would only
hide the problem.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from graph.client import TigerGraphConfig, looks_like_cold_start
from graph.mcp_client import (
    MCPError,
    MCPSession,
    MCPSurfaceError,
    MCPToolError,
    MCPUnavailableError,
    sanitize,
)
from graph.result_normalizers import evidence_values, normalize_result

#: Every installed query in this bundle carries this version suffix.
QUERY_BUNDLE_VERSION = "v1"

#: The plan's per-case graph/MCP call budget.
MAX_GRAPH_CALLS = 12

DEFAULT_TIMEOUT_S = 60.0

#: Six decimals keep a 1536-float vector short enough for the GET request the
#: MCP run_installed_query tool sends (full precision returned HTTP 414), and
#: move a cosine by less than 1e-5.
VECTOR_DECIMALS = 6
VECTOR_DIMENSION = 1536

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Refused by name, whatever else changes: the one write query.
FORBIDDEN_QUERIES = frozenset({"write_investigation_case_v1"})


@dataclass(frozen=True)
class QuerySpec:
    """What the port will send to one installed read query."""

    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    #: Parameters that are timestamps and must parse as TIMESTAMP_FORMAT.
    temporal: tuple[str, ...] = ()
    #: Parameters that are embeddings.
    vectors: tuple[str, ...] = ()
    #: Upper bounds on numeric parameters. Exceeding one is refused, never
    #: clamped, so a caller cannot believe it received what it asked for.
    caps: dict[str, int] = field(default_factory=dict)


READ_QUERIES: dict[str, QuerySpec] = {
    "get_case_context_v1": QuerySpec(
        required=("flagged_txn_id", "as_of_ts"),
        optional=("max_adjacent", "max_scan_rows"),
        temporal=("as_of_ts",),
        caps={"max_adjacent": 50, "max_scan_rows": 20000},
    ),
    "get_card_baseline_v1": QuerySpec(
        required=("card_id", "as_of_ts"),
        optional=("max_scan_rows",),
        temporal=("as_of_ts",),
        caps={"max_scan_rows": 20000},
    ),
    "get_transaction_window_v1": QuerySpec(
        required=("card_id", "anchor_ts", "as_of_ts"),
        optional=("hours_before", "hours_after", "max_rows"),
        temporal=("anchor_ts", "as_of_ts"),
        caps={"hours_before": 720, "hours_after": 720, "max_rows": 300},
    ),
    "extract_temporal_graph_features_v1": QuerySpec(
        required=("flagged_txn_id", "as_of_ts"),
        optional=("shared_window_hours", "burst_gap_seconds", "max_scan_rows"),
        temporal=("as_of_ts",),
        caps={"shared_window_hours": 336, "burst_gap_seconds": 86400, "max_scan_rows": 20000},
    ),
    "find_shared_origin_activity_v1": QuerySpec(
        required=("entity_kind", "entity_id", "anchor_ts", "as_of_ts"),
        optional=(
            "exclude_card_id",
            "window_hours",
            "max_entity_cards",
            "max_rows",
            "max_scan_rows",
        ),
        temporal=("anchor_ts", "as_of_ts"),
        caps={
            "window_hours": 336,
            "max_entity_cards": 100,
            "max_rows": 400,
            "max_scan_rows": 20000,
        },
    ),
    "find_region_anomalies_v1": QuerySpec(
        required=("card_id", "flagged_txn_id", "as_of_ts"),
        optional=("home_window_hours", "max_rows"),
        temporal=("as_of_ts",),
        caps={"home_window_hours": 336, "max_rows": 200},
    ),
    "calculate_case_exposure_v1": QuerySpec(
        required=("txn_ids", "as_of_ts"),
        temporal=("as_of_ts",),
    ),
    "wcc_shared_origin_v1": QuerySpec(
        required=("seed_card_id", "anchor_ts", "as_of_ts"),
        optional=(
            "window_hours",
            "max_hops",
            "stop_expanding_above",
            "max_device_cards",
            "max_device_rows",
            "max_path_segments",
        ),
        temporal=("anchor_ts", "as_of_ts"),
        caps={
            "window_hours": 336,
            "max_hops": 3,
            "stop_expanding_above": 200,
            "max_device_cards": 10,
            "max_device_rows": 20000,
            "max_path_segments": 500,
        },
    ),
    "find_similar_closed_cases_v1": QuerySpec(
        required=("query_vector", "as_of_ts", "related_card_ids"),
        optional=("k", "exclude_case_id", "min_exposure", "max_exposure"),
        temporal=("as_of_ts",),
        vectors=("query_vector",),
        caps={"k": 20},
    ),
    "find_policy_chunks_v1": QuerySpec(
        required=("query_vector",),
        optional=("k",),
        vectors=("query_vector",),
        caps={"k": 10},
    ),
    "read_investigation_case_v1": QuerySpec(required=("case_id",)),
}


# --- errors ------------------------------------------------------------------


class GraphToolError(RuntimeError):
    """Base class. ``fallback_eligible`` says whether direct may retry it."""

    fallback_eligible = False


class ForbiddenQueryError(GraphToolError):
    """The query is not an allowlisted installed read query."""


class InvalidParametersError(GraphToolError):
    """Missing, unknown, malformed or over-cap parameters."""


class TemporalParameterError(InvalidParametersError):
    """A temporal parameter is missing or does not parse."""


class CallBudgetExceeded(GraphToolError):
    """The evidence package has used its graph/MCP call budget."""


class GraphQueryError(GraphToolError):
    """The query ran and failed: a semantic or runtime error in TigerGraph."""


class GraphUnavailableError(GraphToolError):
    """Transport, timeout or availability. The only fallback-eligible failure."""

    fallback_eligible = True


# --- call accounting ----------------------------------------------------------


class CallBudget:
    """A hard per-package cap on graph calls, shared across adapters."""

    def __init__(self, max_calls: int = MAX_GRAPH_CALLS):
        self.max_calls = max_calls
        self.used = 0

    def consume(self, what: str) -> None:
        if self.used >= self.max_calls:
            raise CallBudgetExceeded(
                f"graph call budget of {self.max_calls} exhausted before {what}"
            )
        self.used += 1

    @property
    def remaining(self) -> int:
        return self.max_calls - self.used


@dataclass
class CallRecord:
    """The sanitized record of one graph call."""

    trace_id: str
    adapter: str
    tool: str
    query_name: str
    parameters: dict[str, Any]
    started_at: str
    duration_ms: float = 0.0
    ok: bool = False
    error_class: str = ""
    error: str = ""
    result_bytes: int = 0
    result_blocks: int = 0
    refused: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class CallLog:
    """Every call record of a run, optionally appended to a JSONL file."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self.records: list[CallRecord] = []

    def add(self, record: CallRecord) -> None:
        self.records.append(record)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record.as_dict(), sort_keys=True) + "\n")


def vector_fingerprint(values: list[float]) -> dict[str, Any]:
    """What a log may say about an embedding: its size and a hash, never values."""
    digest = hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()
    return {"vector_dims": len(values), "sha256": digest}


def redact_parameters(
    params: dict[str, Any], spec: QuerySpec, config: TigerGraphConfig | None
) -> dict[str, Any]:
    """Parameters as they may be logged."""
    safe: dict[str, Any] = {}
    for name in sorted(params):
        value = params[name]
        if name in spec.vectors:
            safe[name] = vector_fingerprint(value)
        elif isinstance(value, str):
            safe[name] = sanitize(value, config)
        elif isinstance(value, list | tuple | set):
            items = sorted(str(item) for item in value)
            safe[name] = items[:50] + ([f"... {len(items) - 50} more"] if len(items) > 50 else [])
        else:
            safe[name] = value
    return safe


# --- validation --------------------------------------------------------------


def prepare_parameters(name: str, params: dict[str, Any]) -> tuple[QuerySpec, dict[str, Any]]:
    """Validate a request against the allowlist and return what will be sent."""
    if name in FORBIDDEN_QUERIES:
        raise ForbiddenQueryError(
            f"{name} is the write path and is never callable through the graph tool port; "
            "use graph.case_writer.write_case"
        )
    spec = READ_QUERIES.get(name)
    if spec is None:
        raise ForbiddenQueryError(f"{name} is not an allowlisted installed read query")

    missing = [key for key in spec.required if key not in params]
    if missing:
        kind = (
            TemporalParameterError if set(missing) & set(spec.temporal) else InvalidParametersError
        )
        raise kind(f"{name} is missing required parameters {missing}")
    unknown = sorted(set(params) - set(spec.required) - set(spec.optional))
    if unknown:
        raise InvalidParametersError(f"{name} does not accept parameters {unknown}")

    prepared: dict[str, Any] = {}
    for key, value in params.items():
        if key in spec.temporal:
            if not isinstance(value, str):
                raise TemporalParameterError(f"{name}.{key} must be a timestamp string")
            try:
                datetime.strptime(value, TIMESTAMP_FORMAT)
            except ValueError:
                raise TemporalParameterError(
                    f"{name}.{key}={value!r} is not a {TIMESTAMP_FORMAT} timestamp"
                ) from None
            prepared[key] = value
        elif key in spec.vectors:
            prepared[key] = _prepare_vector(name, key, value)
        elif key in spec.caps:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise InvalidParametersError(f"{name}.{key} must be numeric")
            if value > spec.caps[key]:
                raise InvalidParametersError(
                    f"{name}.{key}={value} exceeds the port cap of {spec.caps[key]}"
                )
            prepared[key] = value
        elif isinstance(value, set | tuple):
            prepared[key] = sorted(value)
        else:
            prepared[key] = value
    return spec, prepared


def _prepare_vector(name: str, key: str, value: Any) -> list[float]:
    if not isinstance(value, list | tuple) or len(value) != VECTOR_DIMENSION:
        raise InvalidParametersError(f"{name}.{key} must be a {VECTOR_DIMENSION}-float vector")
    rounded = []
    for item in value:
        number = float(item)
        if not math.isfinite(number):
            raise InvalidParametersError(f"{name}.{key} contains a non-finite value")
        rounded.append(round(number, VECTOR_DECIMALS))
    return rounded


# --- results -------------------------------------------------------------------


@dataclass(frozen=True)
class QueryResult:
    """A normalized result, identical in shape whichever adapter fetched it."""

    query_name: str
    values: dict[str, Any]
    record: CallRecord

    @property
    def refused(self) -> bool:
        return self.values.get("refused") is True

    def evidence(self) -> dict[str, Any]:
        """The values with every resource-only lifetime precheck removed."""
        return evidence_values([self.values])


def canonical(value: Any) -> Any:
    """An order-insensitive form for comparing results across adapters.

    GSQL set accumulators and vertex sets come back in arbitrary order, so two
    correct answers can differ only in ordering. Lists are sorted by their JSON
    rendering and floats rounded, recursively.
    """
    if isinstance(value, dict):
        return {key: canonical(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        items = [canonical(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if isinstance(value, float):
        return round(value, 9)
    return value


# --- the port -----------------------------------------------------------------


class GraphToolPort(Protocol):
    mode: str
    budget: CallBudget
    log: CallLog

    def run_query(self, name: str, params: dict[str, Any]) -> QueryResult: ...


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class _BasePort:
    adapter = "base"
    tool = ""

    def __init__(
        self,
        *,
        config: TigerGraphConfig | None = None,
        budget: CallBudget | None = None,
        log: CallLog | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ):
        self.config = config
        self.budget = budget or CallBudget()
        self.log = log or CallLog()
        self.timeout_s = timeout_s

    @property
    def mode(self) -> str:
        return self.adapter

    def run_query(self, name: str, params: dict[str, Any]) -> QueryResult:
        try:
            spec, prepared = prepare_parameters(name, params)
        except GraphToolError as error:
            # Refused before sending: recorded, but no budget is spent.
            self.log.add(
                CallRecord(
                    trace_id=uuid.uuid4().hex[:16],
                    adapter=self.adapter,
                    tool=self.tool,
                    query_name=name,
                    parameters={"keys": sorted(params)},
                    started_at=_now(),
                    error_class=type(error).__name__,
                    error=sanitize(str(error), self.config)[:500],
                )
            )
            raise
        self.budget.consume(name)
        record = CallRecord(
            trace_id=uuid.uuid4().hex[:16],
            adapter=self.adapter,
            tool=self.tool,
            query_name=name,
            parameters=redact_parameters(prepared, spec, self.config),
            started_at=_now(),
        )
        started = time.perf_counter()
        try:
            raw = self._execute(name, prepared)
            values = normalize_result(raw)
            record.ok = True
            record.result_bytes = len(json.dumps(raw, default=str))
            record.result_blocks = len(raw) if isinstance(raw, list) else 1
            record.refused = values.get("refused") if "refused" in values else None
            return QueryResult(query_name=name, values=values, record=record)
        except GraphToolError as error:
            record.error_class = type(error).__name__
            record.error = sanitize(str(error), self.config)[:500]
            raise
        finally:
            record.duration_ms = round((time.perf_counter() - started) * 1000, 1)
            self.log.add(record)

    def _execute(self, name: str, params: dict[str, Any]) -> Any:  # pragma: no cover
        raise NotImplementedError


class MCPGraphToolPort(_BasePort):
    """Installed read queries through the official TigerGraph MCP server."""

    adapter = "mcp"
    tool = "tigergraph__run_installed_query"

    def __init__(self, session: MCPSession, **kwargs):
        kwargs.setdefault("config", session.config)
        super().__init__(**kwargs)
        self.session = session

    def _execute(self, name: str, params: dict[str, Any]) -> Any:
        try:
            response = self.session.call_tool(
                self.tool, {"query_name": name, "params": params}, timeout_s=self.timeout_s
            )
        except MCPUnavailableError as error:
            raise GraphUnavailableError(sanitize(str(error), self.config)) from None
        except MCPSurfaceError as error:
            raise ForbiddenQueryError(str(error)) from None
        except MCPToolError as error:
            raise classify_tool_error(str(error), error.code) from None
        except MCPError as error:
            raise GraphUnavailableError(sanitize(str(error), self.config)) from None
        data = response.get("data") or {}
        if "result" not in data:
            raise GraphQueryError(f"{name}: MCP response carried no result")
        return data["result"]


class DirectGraphToolPort(_BasePort):
    """The same installed read queries through pyTigerGraph. Fallback only."""

    adapter = "direct"
    tool = "pyTigerGraph.runInstalledQuery"

    def __init__(self, connection, **kwargs):
        super().__init__(**kwargs)
        self.connection = connection
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="direct-graph")

    def _execute(self, name: str, params: dict[str, Any]) -> Any:
        # GET, like the MCP tool, so both paths send an identical request.
        future = self._pool.submit(self.connection.runInstalledQuery, name, params)
        try:
            return future.result(timeout=self.timeout_s)
        except FutureTimeout:
            raise GraphUnavailableError(f"{name} timed out after {self.timeout_s:.0f}s") from None
        except GraphToolError:
            raise
        except Exception as error:  # noqa: BLE001 - classified below
            raise classify_direct_error(error, self.config) from None


#: Error codes and message fragments meaning the graph was not reachable.
_UNAVAILABLE_CODES = frozenset({"CONNECTION_ERROR"})
_UNAVAILABLE_FRAGMENTS = (
    "timed out",
    "timeout",
    "connection refused",
    "connection error",
    "failed to establish",
    "temporarily unavailable",
    "name or service not known",
    "getaddrinfo",
)


def _looks_unavailable(message: str) -> bool:
    lowered = message.lower()
    return looks_like_cold_start(lowered) or any(item in lowered for item in _UNAVAILABLE_FRAGMENTS)


def classify_tool_error(message: str, code: str = "") -> GraphToolError:
    """An MCP tool-reported failure, as a fallback-eligible error or not."""
    if code in _UNAVAILABLE_CODES or _looks_unavailable(message):
        return GraphUnavailableError(message)
    if "parameter" in message.lower():
        return InvalidParametersError(message)
    return GraphQueryError(message)


def classify_direct_error(error: Exception, config: TigerGraphConfig | None) -> GraphToolError:
    """A pyTigerGraph exception, as a fallback-eligible error or not."""
    import requests

    message = sanitize(str(error), config)
    if isinstance(error, requests.exceptions.Timeout | requests.exceptions.ConnectionError):
        return GraphUnavailableError(message)
    if _looks_unavailable(message):
        return GraphUnavailableError(message)
    if "414" in message or "parameter" in message.lower():
        return InvalidParametersError(message)
    return GraphQueryError(message)


@dataclass
class FallbackEvent:
    query_name: str
    primary_trace_id: str
    fallback_trace_id: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class FallbackGraphToolPort:
    """MCP first; direct only when MCP is unavailable, and visibly so."""

    def __init__(self, primary: _BasePort, fallback: _BasePort):
        # One budget and one log, so a fallback retry is counted and recorded.
        fallback.budget = primary.budget
        fallback.log = primary.log
        self.primary = primary
        self.fallback = fallback
        self.budget = primary.budget
        self.log = primary.log
        self.fallback_events: list[FallbackEvent] = []

    @property
    def mode(self) -> str:
        return f"{self.primary.adapter}_primary_with_{self.fallback.adapter}_fallback"

    @property
    def fallback_occurred(self) -> bool:
        return bool(self.fallback_events)

    def run_query(self, name: str, params: dict[str, Any]) -> QueryResult:
        try:
            return self.primary.run_query(name, params)
        except GraphToolError as error:
            if not error.fallback_eligible:
                raise
            primary_trace = self.log.records[-1].trace_id if self.log.records else ""
            result = self.fallback.run_query(name, params)
            self.fallback_events.append(
                FallbackEvent(
                    query_name=name,
                    primary_trace_id=primary_trace,
                    fallback_trace_id=result.record.trace_id,
                    reason=f"{type(error).__name__}: {str(error)[:300]}",
                )
            )
            return result


def paths_used(log: CallLog) -> dict[str, int]:
    """How many successful calls each adapter served."""
    counts: dict[str, int] = {}
    for record in log.records:
        if record.ok:
            counts[record.adapter] = counts.get(record.adapter, 0) + 1
    return counts


def open_mcp_port(
    config: TigerGraphConfig,
    *,
    runs_dir: Path | None = None,
    budget: CallBudget | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    session_factory: Callable[..., MCPSession] = MCPSession,
) -> MCPGraphToolPort:
    """Start the restricted MCP session and wrap it in the primary port."""
    stderr = runs_dir / "mcp_server_stderr.log" if runs_dir else None
    log = CallLog(runs_dir / "mcp_calls.jsonl" if runs_dir else None)
    session = session_factory(config, stderr_path=stderr).start()
    return MCPGraphToolPort(session, budget=budget, log=log, timeout_s=timeout_s)
