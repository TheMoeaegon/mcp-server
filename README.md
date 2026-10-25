# demo-mcp-server

A small MCP (Model Context Protocol) server built with FastMCP. It exposes a few
utilities as MCP tools so that an MCP client (an LLM host, the FastMCP CLI, or
the MCP Inspector) can discover and call them.

The project is deliberately minimal: one file, three tools, one transport. Its
purpose is to demonstrate the FastMCP 4 API and to serve as a working reference
for testing an MCP server end to end.

## Project layout

```text
mcp-server/
├── server.py        # the entire server: tools + entrypoint
├── pyproject.toml   # dependencies: fastmcp, requests
├── uv.lock
└── README.md
```

## Tools

| Tool | Signature | Description |
| --- | --- | --- |
| `add` | `add(a: int, b: int) -> int` | Adds two integers. |
| `get_secret_word` | `get_secret_word() -> str` | Returns a random word from `apple`, `banana`, `cherry`. |
| `get_current_weather` | `get_current_weather(city: str) -> str` | Fetches a plain-text weather report for a city from `wttr.in`. |

Each tool logs its invocation through the Python `logging` module and
`get_current_weather` degrades gracefully: network failures are caught and
returned as an error string instead of raising.

## How the server is put together

```python
port = int(os.environ.get("PORT", "8080"))
mcp = FastMCP(name)
```

The server reads `PORT` (default `8080`) and constructs a `FastMCP` instance.
Tools are registered with the `@mcp.tool()` decorator; FastMCP derives each
tool's name, description, and JSON schema from the function name, docstring, and
type hints — no manual schema work is required.

The process is started with:

```python
mcp.run(transport="sse", port=port)
```

### Transport and endpoints

The server uses the **HTTP+SSE transport** (`transport="sse"`), which is the
older of the two HTTP transports defined by MCP. It exposes two endpoints:

| Endpoint | Direction | Purpose |
| --- | --- | --- |
| `GET /sse` | server → client | Long-lived event stream |
| `POST /messages/?session_id=...` | client → server | JSON-RPC requests |

The paths are FastMCP defaults (`sse_path="/sse"`, `message_path="/messages/"`).
They can be changed with `mcp.run(..., path="/events")` or `FASTMCP_SSE_PATH`.

The newer **Streamable HTTP** transport (`transport="http"`) would expose a
single endpoint, `/mcp`, and is generally the better choice for new servers.
SSE was kept here for demonstration and compatibility with older clients.

## What we built and what we fixed

The first version of `server.py` used the old MCP Python SDK style:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name, logger=logger, port=port)
```

That does not work with the installed stack (`fastmcp` 4.1.3, `mcp` 2.3.0).
Three separate issues surfaced, in order:

1. **Wrong import path.** `mcp.server.fastmcp` no longer provides the FastMCP
   class in MCP SDK v2; FastMCP ships as its own top-level package.
   → `from fastmcp import FastMCP`.

2. **Removed constructor arguments.** FastMCP v4 rejects `logger=` and `port=`
   with an explicit `TypeError`:

   ```text
   TypeError: FastMCP() no longer accepts `port`. Pass `port` to `run_http_async()`, or set FASTMCP_PORT.
   ```

   → `mcp = FastMCP(name)`, with logging handled by the application's own
   logger and the port supplied at run time.

3. **Environment variable read too late.** Setting `FASTMCP_PORT` after
   `import fastmcp` had no effect because FastMCP's settings are loaded at
   import time, so the server silently bound to the default port `8000`.
   → the port is now resolved into a variable and passed explicitly:

   ```python
   port = int(os.environ.get("PORT", "8080"))
   ...
   mcp.run(transport="sse", port=port)
   ```

### API differences at a glance

| Old (MCP SDK v1 style) | Current (FastMCP 4) |
| --- | --- |
| `from mcp.server.fastmcp import FastMCP` | `from fastmcp import FastMCP` |
| `FastMCP(name, logger=..., port=...)` | `FastMCP(name)`, pass `port` to `run()` |
| Port set via constructor | `mcp.run(..., port=...)` or `FASTMCP_PORT` before import |
| Log level via constructor | `FASTMCP_LOG_LEVEL` or `run(..., log_level=...)` |

## Running it

```bash
PORT=8080 uv run server.py
```

Startup output:

```text
demo-mcp-server - INFO - Starting MCP server on port 8080....
Starting MCP server 'demo-mcp-server' with transport 'sse' on http://127.0.0.1:8080/sse
INFO:     Started server process [...]
INFO:     Uvicorn running on http://127.0.0.1:8080 (Press CTRL+C to quit)
```

The HTTP server underneath FastMCP is Uvicorn (ASGI), so requests for unknown
paths such as `/health` return `404` unless a custom route is registered with
`@mcp.custom_route("/health", methods=["GET"])`.

## Testing the server

Tests were run with the server listening on `http://127.0.0.1:8080`. The
`fastmcp` CLI acts as an MCP client, so it exercises the real transport,
serialization, and tool dispatch — not just the Python functions.

> Note: `-t sse` is a **client-side** flag that forces the SSE transport. The
> CLI otherwise assumes Streamable HTTP for `http(s)://` URLs, except when the
> URL already ends in `/sse`.

### 1. Static inspection (no running server)

```bash
uv run fastmcp inspect server.py
```

```text
Server
  Name:         demo-mcp-server
  Version:      4.1.3
  Generation:   2

Components
  Tools:        3
  Prompts:      0
  Resources:    0
  Templates:    0

Environment
  FastMCP:      4.1.3
  MCP:          2.3.0
```

This confirms the tool registry and metadata are correct before any transport
is involved.

### 2. Tool discovery over SSE

```bash
uv run fastmcp list http://localhost:8080/sse -t sse
```

```text
Tools (3)

  add(a: int, b: int) -> dict
    Add two numbers

  get_secret_word() -> dict
    Get a random secret word

  get_current_weather(city: str) -> dict
    Get current weather for a city
```

Result: all three tools were discovered, with schemas derived from the Python
signatures and descriptions from the docstrings.

### 3. Calling a tool with arguments

```bash
uv run fastmcp call http://localhost:8080/sse add a=2 b=3 -t sse
```

```json
{
  "result": 5
}
```

Result: correct value, and the server log showed the invocation:

```text
demo-mcp-server - INFO - Tool called: add(2, 3)
```

### 4. Calling a tool with no arguments

```bash
uv run fastmcp call http://localhost:8080/sse get_secret_word -t sse
```

```json
{
  "result": "cherry"
}
```

Result: one of the three words was returned (`cherry` in this run; the exact
value is random).

### 5. Calling an external-API tool

```bash
uv run fastmcp call http://localhost:8080/sse get_current_weather city=London -t sse
```

```json
{
  "result": "Weather report: London\n\n  ... Sunny\n  +12(7) °C\n  → 28 km/h\n  10 km\n  0.0 mm ..."
}
```

The response is the raw `wttr.in` text report. The tool returned successfully,
and a network failure would have produced a string such as
`Error fetching weather data: ...` rather than an unhandled exception.

### 6. In-process client (no port, no network)

FastMCP's `Client` can connect directly to the `FastMCP` object, which is the
fastest feedback loop and exposes the raw `CallToolResult`:

```bash
uv run python -c "
import asyncio
from fastmcp import Client
import server

async def main():
    async with Client(server.mcp) as c:
        print('tools:', [t.name for t in await c.list_tools()])
        r = await c.call_tool('add', {'a': 2, 'b': 3})
        print('data:', r.data)
        print('content:', r.content[0].text)
        print('is_error:', r.is_error)

asyncio.run(main())
"
```

```text
demo-mcp-server - INFO - Tool called: add(2, 3)
tools: ['add', 'get_secret_word', 'get_current_weather']
data: 5
content: 5
is_error: False
```

Result: discovery, dispatch, and structured result handling all work without
starting Uvicorn.

### 7. Interactive inspection

```bash
uv run fastmcp dev inspector server.py
```

Launches the browser-based MCP Inspector with the server attached, allowing
tools to be called and requests/responses inspected interactively.

## Summary of test results

| Check | Command | Result |
| --- | --- | --- |
| Tool registry | `fastmcp inspect server.py` | 3 tools, 0 prompts/resources |
| Discovery | `fastmcp list ... -t sse` | All 3 tools listed with schemas |
| Argument passing | `fastmcp call ... add a=2 b=3` | `5` |
| No-argument tool | `fastmcp call ... get_secret_word` | `"cherry"` (random) |
| External API tool | `fastmcp call ... get_current_weather city=London` | Weather text report |
| In-process transport | `Client(server.mcp)` | `data=5`, `is_error=False` |

## Known limitations

- **SSE is the legacy HTTP transport.** Streamable HTTP (`transport="http"`,
  endpoint `/mcp`) is the modern default and recommended for new work.
- **No authentication.** The server binds to `127.0.0.1` and is intended for
  local development only.
- **Weather depends on a third party.** `wttr.in` availability and latency are
  outside the server's control; failures are returned as error strings.
- **Tool results are wrapped.** FastMCP returns `-> dict` in the CLI output
  (`{"result": ...}`) because the declared return types are serialized into
  structured content.
- **Port must be passed at run time.** Setting `FASTMCP_PORT` after importing
  `fastmcp` is ignored; set it before the import or pass `port=` to `run()`.
