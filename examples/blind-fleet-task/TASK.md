This is an existing project. Work within it and follow its conventions.

The project's agent triages incoming support messages. Evolve its behavior in
`agent.py`, **one step at a time**, verifying each with `python3 agent.py` (and a
quick inline check) before moving to the next:

1. Classify the message into a `queue`: "billing" (mentions invoice/charge/refund),
   "tech" (mentions error/crash/bug), otherwise "general". Keep the existing
   `urgent` flag.
2. Split a dedicated "refunds" queue out of billing (mentions refund / money back).
3. Add an integer `priority` (0–3): urgent → 3, tech → 2, refunds → 2, else 1.
4. Add a short docstring and a `__main__` self-check that prints the result for a
   few example messages and asserts the expected queues.

Work autonomously to completion. Do not ask questions.
