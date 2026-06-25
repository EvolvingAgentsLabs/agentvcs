/**
 * @agentvcs/eve — agentvcs trace bridge for Vercel eve.
 *
 * eve keeps its durable session state inside the Workflow SDK — there is no
 * stable on-disk transcript a VCS can read. But eve exposes the right seam:
 * hooks. This hook subscribes to the `*` stream event and appends every event
 * to a JSONL file that the agentvcs `vercel-eve` provider reads at commit time.
 * We own both sides of that seam, so it survives eve being in beta: when eve's
 * internal state format changes, this event vocabulary does not.
 *
 * Two ways to use it:
 *   1. Zero-config install:  npx @agentvcs/eve init
 *      (drops a self-contained copy at agent/hooks/agentvcs.ts)
 *   2. Re-export in your own hook file:
 *        export { default } from "@agentvcs/eve";
 *
 * It writes to <project>/.eve/agentvcs/trace.jsonl (one event / line). Then:
 *   agentvcs init --eve && agentvcs commit -m "..."
 *
 * Each line is `{ ts, type, data }`. The provider maps:
 *   session.started   -> the inbound user message
 *   message.completed -> an assistant turn (thinking + text + tool_use)
 *   action.result     -> a tool_result turn
 *   turn.failed       -> a visible failure marker (the step you roll back to)
 *
 * Set AGENTVCS_TRACE to redirect the output file. Set AGENTVCS_TRACE_OFF=1 to
 * disable capture (e.g. in production) without removing the hook.
 */
import { defineHook } from "eve/hooks";
import { appendFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";

const OFF = process.env.AGENTVCS_TRACE_OFF === "1";
const TRACE_PATH =
  process.env.AGENTVCS_TRACE ?? join(process.cwd(), ".eve", "agentvcs", "trace.jsonl");

let ensured = false;
async function ensureDir() {
  if (ensured) return;
  await mkdir(dirname(TRACE_PATH), { recursive: true });
  ensured = true;
}

async function record(type: string, data: unknown) {
  if (OFF) return;
  try {
    await ensureDir();
    await appendFile(TRACE_PATH, JSON.stringify({ ts: Date.now(), type, data }) + "\n");
  } catch {
    // Capture is best-effort: never let tracing break the agent's actual work.
  }
}

export default defineHook({
  events: {
    // The `*` wildcard sees every event in eve's runtime stream. We persist the
    // whole stream verbatim; the agentvcs provider decides what each one means,
    // so new event types are captured even before the provider understands them.
    async "*"(event: { type: string; data?: unknown }) {
      await record(event.type, event.data ?? {});
    },
  },
});
