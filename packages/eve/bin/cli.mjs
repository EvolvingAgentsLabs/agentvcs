#!/usr/bin/env node
/**
 * @agentvcs/eve CLI — zero-friction install of the agentvcs trace bridge into a
 * Vercel eve project.
 *
 *   npx @agentvcs/eve init [dir] [--force] [--json]
 *
 * Drops a self-contained copy of the hook at <dir>/agent/hooks/agentvcs.ts and
 * wires an eve-flavored agent.json if one isn't there yet. Idempotent; never
 * overwrites without --force. Pure Node, zero runtime dependencies.
 */
import { readFileSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const HOOK_SRC = join(HERE, "..", "hook.ts");

const AGENT_JSON = `{
  "goal": "Describe what this eve agent does.",
  "models": [{ "provider": "anthropic", "model": "claude-opus-4-8" }],
  "trace": { "provider": "vercel-eve", "auto": true, "model": "claude-opus-4-8" },
  "state": "fluid",
  "metrics": {}
}
`;

function parse(argv) {
  const args = { _: [], force: false, json: false };
  for (const a of argv) {
    if (a === "--force") args.force = true;
    else if (a === "--json") args.json = true;
    else args._.push(a);
  }
  return args;
}

function emit(json, data, human) {
  if (json) process.stdout.write(JSON.stringify({ ok: true, ...data }) + "\n");
  else process.stdout.write(human + "\n");
}

function fail(json, code, message) {
  if (json) process.stdout.write(JSON.stringify({ ok: false, error: { code, message } }) + "\n");
  else process.stderr.write(`error: ${message}\n`);
  process.exit(1);
}

function init(args) {
  const root = resolve(args._[1] || ".");
  if (!existsSync(root)) fail(args.json, "NO_DIR", `directory not found: ${root}`);

  const hookDest = join(root, "agent", "hooks", "agentvcs.ts");
  let hookWritten = false;
  if (existsSync(hookDest) && !args.force) {
    // leave an existing hook untouched (idempotent)
  } else {
    mkdirSync(dirname(hookDest), { recursive: true });
    writeFileSync(hookDest, readFileSync(HOOK_SRC, "utf8"));
    hookWritten = true;
  }

  const manifest = join(root, "agent.json");
  let manifestWritten = false;
  let manifestNote = null;
  if (!existsSync(manifest)) {
    writeFileSync(manifest, AGENT_JSON);
    manifestWritten = true;
  } else {
    try {
      const m = JSON.parse(readFileSync(manifest, "utf8"));
      const t = m.trace;
      const wired = t && typeof t === "object" && t.provider === "vercel-eve";
      if (!wired) {
        manifestNote =
          'agent.json exists but its "trace" is not wired to vercel-eve. Set: ' +
          '"trace": { "provider": "vercel-eve", "auto": true }';
      }
    } catch {
      manifestNote = "agent.json exists but could not be parsed; leaving it untouched.";
    }
  }

  const data = {
    project: root,
    hook: hookDest,
    hook_written: hookWritten,
    manifest_written: manifestWritten,
    manifest_note: manifestNote,
  };
  const lines = [
    `agentvcs trace bridge ${hookWritten ? "installed" : "already present"} at agent/hooks/agentvcs.ts`,
    manifestWritten
      ? "Wrote an eve-wired agent.json."
      : manifestNote
      ? `note: ${manifestNote}`
      : "agent.json already wired to vercel-eve.",
    "",
    "Next:",
    "  1. Run your eve agent — every turn is now captured to .eve/agentvcs/trace.jsonl",
    "  2. agentvcs init --eve        # if you haven't initialized the repo yet",
    "  3. agentvcs commit -m \"...\"   # versions code + goal + models + trace",
    "  4. agentvcs ui                # time-travel debug the session",
    "",
    "Set AGENTVCS_TRACE_OFF=1 to disable capture (e.g. in production).",
  ];
  emit(args.json, data, lines.join("\n"));
}

function main() {
  const argv = process.argv.slice(2);
  const args = parse(argv);
  const cmd = args._[0] || "init";
  if (cmd === "init") return init(args);
  if (cmd === "--help" || cmd === "-h" || cmd === "help") {
    process.stdout.write(
      "@agentvcs/eve — agentvcs trace bridge for Vercel eve\n\n" +
        "Usage:\n  npx @agentvcs/eve init [dir] [--force] [--json]\n"
    );
    return;
  }
  fail(args.json, "UNKNOWN_CMD", `unknown command: ${cmd}`);
}

main();
