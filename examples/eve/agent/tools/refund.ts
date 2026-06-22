import { defineTool } from "eve/tools";
import { z } from "zod";

// The good, committed version of the refund tool (state at HEAD~1 in the demo).
// The agent's next turn hallucinates an idempotency layer on top of this; the
// demo rolls back to exactly this file and resumes from here.
export default defineTool({
  description: "Issue a refund for a payment request.",
  inputSchema: z.object({
    requestId: z.string(),
    amountCents: z.number().int().positive(),
  }),
  async execute({ requestId, amountCents }) {
    // TODO(turn 2): make idempotent on requestId so retries don't double-refund.
    return { requestId, amountCents, status: "refunded" };
  },
});
