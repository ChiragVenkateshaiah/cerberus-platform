# agents

The read-only tools of the AI operations agents (ADR 0025, plan
`docs/plans/2026-11-21-agent-review-core.md`).

- `review.py`, `evidence.py`, `baselines.py`: the model-free review core (14.2a).
- `registry.py`, `tools.py`: the tool registry (14.2b).
- `mcp_server.py`: a local stdio MCP server over that registry (14.2c).

## The server

A newline-delimited JSON-RPC 2.0 server over stdin and stdout. Stdlib only, no
network, no write. Tools take named input only. A refused call is a normal tool
result with `isError` true. Errors have fixed text and never echo the request.
One input line is at most 64 KiB.

The nine tools: `status`, `runs`, `run`, `cost`, `dq`, `slo`, `review`,
`queries_list`, `query`.

It is offline by default. It reads the committed run records in
`observability/scale/runs` (change it with `--runs-dir`). `status` and `run`
show their AWS sections as "unavailable", and `query` answers "unavailable"
because no reader is wired. `--aws` is not available yet (IAM step): the flag
exits 2.

Run it by hand: `make mcp`. It waits silently on stdin for JSON lines. The
server stops answering tools after 100 calls per process (`CALL_BUDGET`, a
deliberate cap for a local review session), so the client must restart it.

## Register it in Claude Code

From the repo root:

```
claude mcp add cerberus-review -e PYTHONPATH=agents:console -- uv run --no-project --python 3.12 python -m cerberus_agents.mcp_server
```

The paths in `PYTHONPATH` are repo-relative, so the client must start the
command with the repo root as its working directory. The `claude mcp add` syntax
was checked against `claude mcp add --help`. A live session with the client was
not run (unverified), and the protocol version string is unverified against it.

## Known limit

Output text is allowlisted by shape, not by meaning. A short token that fits an
allowed shape (an execution name, a known check name) can still carry words.
This is accepted: the tools are read-only and take named input, and a human
approves each action. 14.4 builds the model loop and the validator on top.
