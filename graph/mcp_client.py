"""The official TigerGraph MCP server, started with a restricted tool surface.

This is the agent-facing graph path the challenge requires. It starts the
official ``tigergraph-mcp`` server (package ``tigergraph-mcp``) as a stdio
subprocess, holds ONE session for the whole run as the package documentation
recommends, and refuses to proceed unless the server serves exactly the tools
listed in :data:`MCP_SERVED_TOOLS`.

Why exactly these six
---------------------
``tigergraph-mcp`` serves 69 tools by default, including raw GSQL, query
installation, loading, vertex/edge writes and deletion. The server's own
``--allowed-tools`` selector narrows that list, and it is given one tool name
per required capability:

========================================  ====================================
Tool                                      Why the investigation needs it
========================================  ====================================
``tigergraph__list_graphs``               utility: a read-only health check
``tigergraph__get_graph_schema``          discovery: the schema, read-only
``tigergraph__is_query_installed``        discovery: that a query exists
``tigergraph__run_installed_query``       execution of installed read queries
``tigergraph__list_vector_attributes``    vector discovery, read-only
``tigergraph__get_vector_index_status``   vector index readiness, read-only
========================================  ====================================

Excluded on purpose: ``gsql`` and ``run_query`` (free-form query text),
``install_query`` / ``drop_query``, every add/upsert/delete/load/create tool,
and ``search_top_k_similarity``, which CREATES, INSTALLS and DROPS a temporary
query on every call and applies no temporal filter. Vector retrieval runs
through the installed ``find_similar_closed_cases_v1`` and
``find_policy_chunks_v1`` queries instead, which enforce the case cutoff.

``run_installed_query`` takes any query name, and the server itself marks it
destructive because what it does depends on the query named. The allowlist of
installed READ queries is therefore enforced in application code, in
:mod:`graph.tool_port`, before any call reaches this module. In particular
``write_investigation_case_v1`` can never be called through MCP; the only write
path is :func:`graph.case_writer.write_case`.

Secrets reach the subprocess only through its environment, built from the
project's own configuration, and are never logged: every string this module
reports passes through :func:`graph.client.redact`.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import threading
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from graph.client import TigerGraphConfig, redact

#: The complete served surface. The server is started with exactly this list,
#: and startup fails if it serves anything else.
MCP_SERVED_TOOLS: tuple[str, ...] = (
    "tigergraph__list_graphs",
    "tigergraph__get_graph_schema",
    "tigergraph__is_query_installed",
    "tigergraph__run_installed_query",
    "tigergraph__list_vector_attributes",
    "tigergraph__get_vector_index_status",
)

#: Name fragments of tools that mutate the graph or run caller-supplied text.
#: A served tool containing any of these fails startup, whatever the allowlist
#: says, so a future package version cannot widen the surface silently.
FORBIDDEN_TOOL_MARKERS: tuple[str, ...] = (
    "gsql",
    "run_query",
    "install_query",
    "drop_",
    "delete_",
    "clear_",
    "add_",
    "upsert",
    "load_",
    "create_",
    "update_",
    "generate_",
    "authenticate",
    "search_top_k",
)

DEFAULT_CALL_TIMEOUT_S = 60.0
DEFAULT_STARTUP_TIMEOUT_S = 90.0

_FENCED_JSON = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_URL = re.compile(r"https?://[^\s'\"<>]+")


class MCPError(RuntimeError):
    """Base class for MCP session failures."""


class MCPUnavailableError(MCPError):
    """The server could not be started, reached, or answered in time."""


class MCPSurfaceError(MCPError):
    """The server served a tool surface other than the restricted one."""


class MCPToolError(MCPError):
    """A tool ran and reported failure. ``code`` is the server's error_code."""

    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code


def sanitize(text: str, config: TigerGraphConfig | None) -> str:
    """Redact secrets and replace URLs, which can carry the host and tokens."""
    if config is not None:
        text = redact(text, config)
    return _URL.sub("<url-redacted>", text)


def server_command() -> str:
    """The ``tigergraph-mcp`` console script installed beside this interpreter."""
    scripts = Path(sys.executable).parent
    for name in ("tigergraph-mcp.exe", "tigergraph-mcp"):
        candidate = scripts / name
        if candidate.exists():
            return str(candidate)
    raise MCPUnavailableError(
        "the tigergraph-mcp console script is not installed in this environment; "
        "install tigergraph-mcp==1.0.3"
    )


def server_environment(config: TigerGraphConfig) -> dict[str, str]:
    """The TG_* variables the server needs, taken from the project config.

    The MCP SDK's stdio client does not pass the parent environment to the
    subprocess, so credentials must be given explicitly. Only the variables the
    server reads are passed, and tool-call logging is switched on without
    caller identity, as the build plan's security section asks.
    """
    env = {
        "TG_HOST": config.host,
        "TG_GRAPHNAME": config.graphname,
        "TG_TGCLOUD": "true" if config.tg_cloud else "false",
        "TG_LOG_TOOL_CALLS": "true",
        "TG_LOG_CALLER_IDENTITY": "none",
    }
    if config.secret:
        env["TG_SECRET"] = config.secret
    if config.api_token:
        env["TG_API_TOKEN"] = config.api_token
    if not config.tg_cloud:
        env["TG_USERNAME"] = config.username
        env["TG_PASSWORD"] = config.password
    return env


def server_arguments(tools: tuple[str, ...] = MCP_SERVED_TOOLS) -> list[str]:
    """The exact startup arguments: the restricted surface and call logging."""
    return ["--allowed-tools", ",".join(tools), "--log-tool-calls"]


def describe_startup(tools: tuple[str, ...] = MCP_SERVED_TOOLS) -> str:
    """The startup command as it can be documented: no secrets, no host."""
    return "tigergraph-mcp " + " ".join(server_arguments(tools))


def parse_tool_text(text: str) -> dict[str, Any]:
    """The structured response inside a tool's text content.

    ``tigergraph-mcp`` returns a fenced ```json block followed by a human
    readable rendering; only the JSON block is authoritative.
    """
    match = _FENCED_JSON.search(text)
    payload = match.group(1) if match else text
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as error:
        raise MCPToolError(f"unparseable tool response: {error}", "UNPARSEABLE") from None
    if not isinstance(parsed, dict):
        raise MCPToolError("tool response is not a JSON object", "UNPARSEABLE")
    return parsed


def check_surface(served: list[str], allowed: tuple[str, ...] = MCP_SERVED_TOOLS) -> None:
    """Fail closed unless the served surface is exactly the allowed one."""
    served_set, allowed_set = set(served), set(allowed)
    unexpected = sorted(served_set - allowed_set)
    missing = sorted(allowed_set - served_set)
    forbidden = sorted(
        name
        for name in served_set
        if any(marker in name.removeprefix("tigergraph__") for marker in FORBIDDEN_TOOL_MARKERS)
    )
    problems = []
    if unexpected:
        problems.append(f"unexpected tools served: {unexpected}")
    if missing:
        problems.append(f"required tools not served: {missing}")
    if forbidden:
        problems.append(f"mutating or free-form tools served: {forbidden}")
    if problems:
        raise MCPSurfaceError("; ".join(problems))


@dataclass(frozen=True)
class ServedTool:
    """One entry of the sanitized served-tool inventory."""

    name: str
    read_only_hint: bool | None
    destructive_hint: bool | None
    parameters: tuple[str, ...]
    description: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "read_only_hint": self.read_only_hint,
            "destructive_hint": self.destructive_hint,
            "parameters": list(self.parameters),
            "description": self.description,
        }


class MCPSession:
    """One live session with the official server, usable from synchronous code.

    The MCP SDK is async and its stdio transport opens anyio task groups that
    must be entered and exited in the same task. A dedicated thread therefore
    runs one owner coroutine that opens the transport and the session, serves
    tool calls from a queue, and closes both when asked. Callers submit calls
    and wait on a future with a timeout.
    """

    def __init__(
        self,
        config: TigerGraphConfig,
        *,
        tools: tuple[str, ...] = MCP_SERVED_TOOLS,
        stderr_path: Path | None = None,
        startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
    ):
        self.config = config
        self.tools = tools
        self.stderr_path = stderr_path
        self.startup_timeout_s = startup_timeout_s
        self.inventory: list[ServedTool] = []
        self.server_info: dict[str, Any] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._thread: threading.Thread | None = None
        self._ready: Future = Future()
        self._closed: Future = Future()

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> MCPSession:
        if self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._run, name="tigergraph-mcp", daemon=True)
        self._thread.start()
        try:
            self._ready.result(timeout=self.startup_timeout_s)
        except FutureTimeout:
            self.close()
            raise MCPUnavailableError(
                f"the MCP server did not initialise within {self.startup_timeout_s:.0f}s"
            ) from None
        except MCPError:
            self.close()
            raise
        except Exception as error:  # noqa: BLE001
            self.close()
            raise MCPUnavailableError(
                f"the MCP server could not start: {sanitize(str(error), self.config)}"
            ) from None
        return self

    def close(self) -> None:
        if self._loop is not None and self._queue is not None and not self._closed.done():
            self._loop.call_soon_threadsafe(self._queue.put_nowait, None)
            try:
                self._closed.result(timeout=30)
            except Exception:  # noqa: BLE001 - closing is best effort
                pass
        if self._thread is not None:
            self._thread.join(timeout=30)

    def __enter__(self) -> MCPSession:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def alive(self) -> bool:
        return self._ready.done() and not self._closed.done() and self._ready.exception() is None

    # -- calls --------------------------------------------------------------

    def call_tool(
        self, name: str, arguments: dict[str, Any], *, timeout_s: float = DEFAULT_CALL_TIMEOUT_S
    ) -> dict[str, Any]:
        """Run one served tool and return its parsed structured response."""
        if name not in self.tools:
            raise MCPSurfaceError(f"{name} is not on the restricted MCP surface")
        if not self.alive:
            raise MCPUnavailableError("the MCP session is not running")
        future: Future = Future()
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait, (name, arguments, timeout_s, future)
        )
        try:
            return future.result(timeout=timeout_s + 5)
        except FutureTimeout:
            raise MCPUnavailableError(f"{name} did not answer within {timeout_s:.0f}s") from None

    # -- the owner thread ---------------------------------------------------

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            loop.run_until_complete(self._owner())
        except BaseException as error:  # noqa: BLE001
            if not self._ready.done():
                self._ready.set_exception(error)
        finally:
            if not self._closed.done():
                self._closed.set_result(True)
            loop.close()

    async def _owner(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import get_default_environment, stdio_client

        self._queue = asyncio.Queue()
        params = StdioServerParameters(
            command=server_command(),
            args=server_arguments(self.tools),
            env={**get_default_environment(), **server_environment(self.config)},
        )
        if self.stderr_path is not None:
            self.stderr_path.parent.mkdir(parents=True, exist_ok=True)
        errlog = (
            open(self.stderr_path, "a", encoding="utf-8")  # noqa: SIM115
            if self.stderr_path is not None
            else open("nul" if sys.platform == "win32" else "/dev/null", "w")  # noqa: SIM115
        )
        try:
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    info = getattr(init, "server_info", None) or getattr(init, "serverInfo", None)
                    self.server_info = {
                        "name": getattr(info, "name", ""),
                        "version": getattr(info, "version", ""),
                    }
                    listed = await session.list_tools()
                    self.inventory = [_served_tool(tool) for tool in listed.tools]
                    try:
                        check_surface([tool.name for tool in self.inventory], self.tools)
                    except MCPSurfaceError as error:
                        self._ready.set_exception(error)
                        return
                    self._ready.set_result(True)
                    await self._serve(session)
        finally:
            errlog.close()

    async def _serve(self, session) -> None:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            name, arguments, timeout_s, future = item
            try:
                result = await asyncio.wait_for(
                    session.call_tool(name, arguments, read_timeout_seconds=timeout_s),
                    timeout=timeout_s,
                )
                future.set_result(self._decode(name, result))
            except TimeoutError:
                future.set_exception(
                    MCPUnavailableError(f"{name} timed out after {timeout_s:.0f}s")
                )
            except MCPError as error:
                future.set_exception(error)
            except Exception as error:  # noqa: BLE001 - transport failure
                future.set_exception(
                    MCPUnavailableError(
                        f"{name} failed in transport: {sanitize(str(error), self.config)}"
                    )
                )

    def _decode(self, name: str, result) -> dict[str, Any]:
        texts = [getattr(item, "text", "") for item in (result.content or [])]
        parsed = parse_tool_text("\n".join(texts))
        if getattr(result, "is_error", False) or parsed.get("success") is False:
            message = sanitize(str(parsed.get("error") or parsed.get("summary") or ""), self.config)
            raise MCPToolError(message or f"{name} reported failure", parsed.get("error_code", ""))
        return parsed


def _served_tool(tool) -> ServedTool:
    annotations = getattr(tool, "annotations", None)
    schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}
    description = (getattr(tool, "description", "") or "").strip().splitlines()
    return ServedTool(
        name=tool.name,
        read_only_hint=getattr(annotations, "read_only_hint", None) if annotations else None,
        destructive_hint=getattr(annotations, "destructive_hint", None) if annotations else None,
        parameters=tuple(sorted((schema.get("properties") or {}).keys())),
        description=description[0][:200] if description else "",
    )
