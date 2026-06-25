import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const CLI = join(dirname(fileURLToPath(import.meta.url)), "..", "bin", "cli.mjs");

function run(dir, args = []) {
  return execFileSync("node", [CLI, "init", dir, "--json", ...args], { encoding: "utf8" });
}

function tmp() {
  return mkdtempSync(join(tmpdir(), "agentvcs-eve-"));
}

test("init installs the hook and an eve-wired agent.json", () => {
  const dir = tmp();
  const out = JSON.parse(run(dir));
  assert.equal(out.ok, true);
  assert.equal(out.hook_written, true);
  assert.equal(out.manifest_written, true);

  const hook = readFileSync(join(dir, "agent", "hooks", "agentvcs.ts"), "utf8");
  assert.match(hook, /defineHook/);
  assert.match(hook, /\.eve.*agentvcs.*trace\.jsonl|join\(process\.cwd\(\)/);

  const manifest = JSON.parse(readFileSync(join(dir, "agent.json"), "utf8"));
  assert.equal(manifest.trace.provider, "vercel-eve");
});

test("init is idempotent (no overwrite without --force)", () => {
  const dir = tmp();
  run(dir);
  const second = JSON.parse(run(dir));
  assert.equal(second.hook_written, false);     // left the existing hook alone
  assert.equal(second.manifest_written, false);
});

test("--force rewrites the hook", () => {
  const dir = tmp();
  run(dir);
  writeFileSync(join(dir, "agent", "hooks", "agentvcs.ts"), "// stale\n");
  const forced = JSON.parse(run(dir, ["--force"]));
  assert.equal(forced.hook_written, true);
  assert.match(readFileSync(join(dir, "agent", "hooks", "agentvcs.ts"), "utf8"), /defineHook/);
});

test("flags an existing agent.json not wired to vercel-eve", () => {
  const dir = tmp();
  writeFileSync(join(dir, "agent.json"),
    JSON.stringify({ goal: "x", trace: "traces/run.jsonl" }));
  const out = JSON.parse(run(dir));
  assert.equal(out.manifest_written, false);
  assert.match(out.manifest_note, /vercel-eve/);
});
