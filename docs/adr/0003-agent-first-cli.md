# ADR-0003 — Agent-first CLI

- Status: accepted (2026-10-06)

## Decision

The CLI is used by humans and, mostly, by the system agent. Therefore:

- every command accepts `--json` and prints exactly one JSON object on stdout,
  carrying `"ok": true|false` and, on failure, `"error": {"code", "message"}`;
  consumers branch on `code`, never on `message`;
- the JSON output of each command has a documented shape (`spec/cli/`), versioned
  with the protocol;
- exit codes are documented (`spec/cli/EXIT_CODES.md`) and stable;
- no command ever prompts; destructive operations require `--yes`;
- `agentvcs mcp` exposes the same commands as MCP tools with the same JSON.

## Consequences

The conformance runner only ever talks to the CLI through argv, exit code and
stdout JSON, which keeps it language-agnostic.
