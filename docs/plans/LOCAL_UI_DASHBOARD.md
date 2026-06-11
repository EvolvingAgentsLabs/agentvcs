# Plan — `agentvcs ui`: the local "Dashboard del Tiempo"

Status: **proposed** · Branch: `feat/local-ui-dashboard` · Target: v0.2 (alpha)

## 1. Why

Today every bit of agentvcs value lives in the terminal (`agentvcs show --trace`
prints a 400-line conversation). A human can't *see* the mind of the agent evolve.
The single highest-leverage next step is a **local visual dashboard**: a split view
with the commit tree on the left and, on the right, the commit's diff plus a
chat-style render of the agent's internal monologue (the `trace` dimension), its
`goal`, and the `models` that ran.

This is the marketing artifact: click a commit → watch the exact `[thinking]` /
`[tool_use]` / `[tool_result]` blocks that produced those lines of code. The concept
clicks instantly. It is also a dogfooding target (Option B in the brief: build the
UI *with* agentvcs, versioning itself).

## 2. Non-negotiable constraints (inherited from the project)

These are load-bearing and the plan is shaped around them:

1. **Zero runtime dependencies.** `pyproject.toml` declares `dependencies = []`
   ("stdlib only, auditable by anyone"). The MCP server already proves the pattern:
   a full JSON-RPC transport on `http.server`/stdlib alone. **The UI must not add a
   single dependency** — no Flask, no FastAPI, no React build step, no npm. Server =
   `http.server`; frontend = one self-contained `index.html` with vanilla JS/CSS.
2. **`--json` everywhere.** `agentvcs ui --json` emits one object (the URL it bound)
   and the standard `{ok, command, ...}` envelope. Errors keep stable `error.code`s.
3. **Read-only in v1.** The dashboard *visualizes*; it never mutates the store.
   (Write actions — rollback/checkout from the UI — are a deliberate v0.3 stretch,
   §9.) This keeps the first cut safe and small.
4. **Reuse, don't reimplement.** `Repository.log()`, `diff_commits()`, the trace
   message shape, and the existing `_render_content` semantics already produce
   everything the API needs. The API is a thin JSON projection of methods that exist.

## 3. Architecture

```
agentvcs ui  ──► cli.cmd_ui ──► ui.server.serve(repo, host, port)
                                   │
                                   ├─ ThreadingHTTPServer + BaseHTTPRequestHandler
                                   │     GET /            → static index.html
                                   │     GET /api/...     → ui.api.handle(repo, path, query)  (pure, testable)
                                   │
                                   └─ ui/index.html  (vanilla JS single file, polls /api/log)
```

Split into a **pure API layer** and a **thin transport**, mirroring how
`diff.py`/`repository.py` are pure and `cli.py`/`mcp_server.py` are the I/O shells.
This is what makes the API unit-testable without binding a socket.

### New files
- `src/agentvcs/ui/__init__.py` — exports `serve`.
- `src/agentvcs/ui/api.py` — `handle(repo, route, query) -> (status:int, dict)`.
  Pure functions; no sockets. One function per endpoint.
- `src/agentvcs/ui/server.py` — `ThreadingHTTPServer` + request handler; routes
  `/api/*` to `api.handle`, serves `index.html` for everything else, optionally
  opens the browser. Binds `127.0.0.1` by default.
- `src/agentvcs/ui/index.html` — the entire frontend (HTML + `<style>` + `<script>`),
  shipped as a package data file and read via `importlib.resources`.

### Changed files
- `src/agentvcs/cli.py` — add `cmd_ui` + the `ui` subparser (`--port`, `--host`,
  `--no-open`). Update the module docstring command list.
- `pyproject.toml` — ensure `index.html` ships in the wheel (§7).
- `docs/AGENT_MODE.md` — document the `ui` command's `--json` output + any new
  error code (`PORT_IN_USE`).
- `README.md` — add a "Visualize the evolution" section + the GIF later.
- `tests/test_ui.py` — new.

## 4. The read-only JSON API

All responses reuse the **exact shapes the CLI already emits**, so the contract is
already specified in `docs/AGENT_MODE.md` and there is one source of truth.

| Route | Returns | Backed by |
|-------|---------|-----------|
| `GET /api/repo` | `{branches:[{name,commit}], current, head, manifest_goal}` | `repo.branches()`, `current_branch()`, `head_commit()` |
| `GET /api/log` | `{commits:[{commit,state,timestamp,message,goal,parents}]}` | `repo.log()` + `_commit_summary` |
| `GET /api/commit/<oid>` | the `show` summary: `{…, models[], trace_messages, metrics, crystal}` | `cmd_show` logic |
| `GET /api/commit/<oid>/trace` | `{trace:[…messages…]}` (raw blocks, for the chat view) | `read_obj(commit["trace"])` |
| `GET /api/diff?a=&b=` | `{a,b,diff}` (defaults parent..oid like the CLI) | `diff_commits` |

Implementation notes:
- Resolve refs with `repo._resolve(oid, expect="commit")`; map `RepoError` →
  `{ok:false, error:{code,message}}` with HTTP 400/404, never a stack trace.
- **Refactor for reuse:** lift the dict-building bodies of `cmd_show`/`cmd_log`/
  `cmd_diff` into small pure helpers (e.g. `commit_view(repo, oid)`) that *both*
  the CLI and `api.py` call. Avoids drift between terminal and UI. Low risk — the
  dicts already exist inline; this only moves them.
- The trace endpoint returns the unmodified message blocks; rendering (turning a
  `thinking`/`tool_use`/`tool_result` block into a styled bubble) happens client-side,
  porting the logic that lives in `cli._render_content`.

## 5. The frontend (single `index.html`, vanilla)

Layout — two panes:

```
┌────────────────────────┬─────────────────────────────────────────────┐
│  branch ▸ main         │  commit 7830e79   ● fluid    claude-opus-4-8 │
│                        │  goal: "Add a resilient web scraper"         │
│  ● 7830e79  Add tr…    │  ┌── Overview ──┬── Conversation ──┐          │
│  ● 5539855  Templa…    │  │ diff vs parent: + scraper.py … │          │
│  ● 323d59e  Add fa…    │  │ models: anthropic/claude-opus… │          │
│  │  (selected)         │  │ metrics: {tokens: 1820, …}     │          │
│  ● 474f16c  Add `ne…   │  └────────────────────────────────┘          │
│                        │  ── Conversation (trace) ──                  │
│                        │   user:    scrape this URL…                  │
│                        │   asst:    [thinking] the price is in…       │
│                        │            [tool_use Bash] curl …            │
│                        │            [tool_result] <html>…             │
└────────────────────────┴─────────────────────────────────────────────┘
```

- **Left — commit graph.** Render `GET /api/log` as a vertical list; draw parent
  edges (the format already carries `parents[]`, so a real DAG is possible — v1 can
  draw the first-parent spine and dot-mark merges/branches, full graph later).
  A `fluid`/`crystallized` badge per node (cyan/green, matching the CLI colors).
  Clicking a node loads the right pane.
- **Right — two tabs:**
  - *Overview*: goal, model pins, state, metrics, and the dimensional diff vs parent
    (color the four dimensions so "which dimension moved" is obvious — the whole
    point of `diff_commits`).
  - *Conversation*: the trace rendered as a chat. Port `_render_content`:
    `text`→bubble, `thinking`→dimmed italic "thinking" bubble, `tool_use`→a
    cyan tool-call card with the input JSON, `tool_result`→a green result card
    (collapsible; results get long). Show the per-message `model` tag. **This is the
    "blow their minds" view** — make it look like a real chat with a visible inner
    monologue.
- **Live mode.** Poll `GET /api/log` every ~2s; if HEAD moved, prepend new commits.
  So during a demo you `agentvcs commit` in the terminal and the dashboard grows in
  real time — the "Dashboard del Tiempo" feel.
- No framework, no bundler. One file. CSS in a `<style>` block; a dark theme that
  matches the terminal aesthetic. ~400–600 lines total.

## 6. CLI surface

```
agentvcs ui [--host 127.0.0.1] [--port 8080] [--no-open] [--json]
```

- Default: bind `127.0.0.1:8080`, print the URL, open the default browser
  (`webbrowser.open`, stdlib), block serving until Ctrl-C.
- `--no-open`: don't launch a browser (CI / headless / "just give me the URL").
- `--json`: emit `{"ok":true,"command":"ui","url":"http://127.0.0.1:8080","host":…,"port":…}`
  then keep serving (or, for scripted use, a `--print-url-only` could exit — decide
  during impl; default keeps serving).
- Port already taken → `RepoError("port 8080 in use", code="PORT_IN_USE")`, or
  auto-increment to the next free port and report which one (preferred; friendlier).
- Reuses `Repository.open()`, so it inherits `-C/--repo` and the `NOT_A_REPO` error
  for free.

## 7. Packaging (the one real gotcha)

The wheel target is `packages = ["src/agentvcs"]`. Hatchling includes non-Python
files under the package, but to be safe and explicit, add `index.html` as a forced
artifact so the dashboard can't ship broken:

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/agentvcs/ui/index.html" = "agentvcs/ui/index.html"
```

Load it at runtime with `importlib.resources.files("agentvcs.ui") / "index.html"`
(works installed or from source; no `__file__` path math). Add a test that the
resource resolves and is non-empty so a packaging regression fails CI, not a user.

## 8. Tests (`tests/test_ui.py`, stdlib only)

- **API unit tests** (no socket): call `ui.api.handle(repo, route, query)` directly
  against a temp repo built like `test_repository.py` does. Assert:
  - `/api/log` returns commits newest-first with the documented fields.
  - `/api/commit/<oid>` matches the `show` summary; `/trace` returns the messages.
  - `/api/diff` isolates a goal-only change to the `goal` dimension (mirrors
    `test_dimensional_diff_isolates_changes`).
  - bad ref → `(404/400, {ok:false, error:{code:"BAD_REF"}})`.
- **One smoke test through the socket**: start `serve` on port 0 in a thread, hit it
  with `http.client`, assert `/` returns HTML and `/api/log` returns JSON. Tear down.
- **Packaging test**: the `index.html` resource resolves and is non-empty.

## 9. Out of scope for v1 (explicit, with a path forward)

- **Write actions in the UI** (rollback/checkout/freeze buttons, "Mala idea, volvamos
  atrás" on camera). Deferred to v0.3 — needs a confirm step and a CSRF/loopback
  guard since it mutates the store. The read-only API is the foundation it builds on.
- **Full DAG rendering** with lane assignment across many branches (v1 draws the
  first-parent spine + branch tips).
- **Auth / remote exposure.** v1 is loopback-only by design.
- **Cloud sync / git-under-the-hood** (v0.5 per the roadmap) — unrelated to this UI.

## 10. Step-by-step build order

1. `ui/api.py` + refactor `commit_view`/`log_view` helpers shared with `cli.py`;
   land the API unit tests first (TDD against shapes that already exist).
2. `ui/server.py` — routing + static serve + browser open + port handling.
3. `cli.cmd_ui` + subparser + docstring; wire `--json`/`-C`.
4. `ui/index.html` — left graph, right Overview tab, then the Conversation chat
   render (port `_render_content`), then live polling.
5. Packaging (`force-include`) + packaging test + socket smoke test.
6. Docs: `AGENT_MODE.md` (`ui` output + `PORT_IN_USE`), `README.md` section.
7. **Dogfood:** drive steps 1–6 through `agentvcs commit` on this branch so the
   dashboard's own history becomes the first demo dataset (Option B from the brief).

## 11. Definition of done

- `agentvcs ui` opens a browser showing this repo's real history.
- Clicking any commit shows its diff, goal, models, and a readable chat render of the
  captured Claude Code trace (`[thinking]`/`[tool_use]`/`[tool_result]`).
- `agentvcs commit` in a second terminal makes a new node appear within ~2s.
- `agentvcs ui --json --no-open` prints the URL and serves headless.
- `pytest` green; zero new runtime dependencies; `index.html` ships in the wheel.
