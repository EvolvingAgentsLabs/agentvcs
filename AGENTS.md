# Contributing to agentvcs (for coding agents & humans)

agentvcs is the open-source core of an "agent-first" VCS. If you are an autonomous
agent, you are a first-class user here — keep the project agent-drivable.

## Project map
- `src/agentvcs/objects.py` — content-addressed SHA-256 object store (git-style)
- `src/agentvcs/repository.py` — repo ops: init/commit/log/branch/checkout/rollback,
  ref resolution, the four-dimension snapshot
- `src/agentvcs/diff.py` — dimensional diff (code / goal / models / trace)
- `src/agentvcs/crystallize.py` — fluid → crystallized (pin temperature 0 + recipe)
- `src/agentvcs/cli.py` — the `agentvcs`/`avcs` CLI (human + `--json` agent mode)
- `src/agentvcs/mcp_server.py` — zero-dep stdio MCP server
- `docs/SPEC.md` — on-disk format (the proposed standard; update it when the format changes)
- `docs/AGENT_MODE.md` — the agent contract: `--json` shape + stable error codes

## Run the tests
```bash
PYTHONPATH=src python3.12 -m pytest tests/ -q
```

## Non-negotiable invariants (do not regress these)
1. **Zero runtime dependencies.** Standard library only. It is a core selling point
   (auditability). Test-only deps go under `[project.optional-dependencies].dev`.
2. **Agent contract is stable.** Every command keeps working with `--json`, emitting
   one JSON object. Never print prose/spinners/color to stdout in `--json` mode.
3. **Error codes are stable.** Add new `RepoError` codes; never rename existing ones.
   Document every code in `docs/AGENT_MODE.md`.
4. **Format changes are spec changes.** Any change to stored object shapes must be
   reflected in `docs/SPEC.md` and bump the format version.
5. **Reversibility.** Destructive ops must be recoverable (objects are never deleted;
   `rollback` records `ROLLBACK_HEAD`).

## When you add a command
Wire it in `cli.py` (with `--json` via the shared `_out` helper) **and** expose it as
an MCP tool in `mcp_server.py`, then add a test in `tests/`.
