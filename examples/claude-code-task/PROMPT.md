# Task: build a tiny URL shortener library

Build a small, dependency-free Python library `shortener.py` in this directory.

Requirements (implement them **one at a time**, iterating):

1. `Shortener.encode(url) -> code` and `Shortener.decode(code) -> url`, in-memory.
   Codes should be short base62 strings.
2. Encoding the **same URL twice returns the same code** (dedupe).
3. Add `stats()` returning how many times each code has been `decode`d.
4. Add a `Shortener(seed=...)` option so generated codes are deterministic for a
   given seed (useful for tests).

Write a quick check at the bottom under `if __name__ == "__main__":` that
exercises each feature, and run it after each step.

## Working agreement

This project is versioned with **agentvcs** (see the `agentvcs` skill, or run
`agentvcs --help`). Please:

- Keep `agent.json`'s `goal` updated to reflect what you're currently building.
- `agentvcs commit` after each requirement that works.
- If a change makes things worse, use `agentvcs rollback` instead of hand-reverting.
- When all four requirements pass, `agentvcs freeze` the final solution.

> For a **blind** product-market-fit test, delete this "Working agreement" section
> before giving the task to the agent, and see whether it discovers and adopts
> agentvcs on its own (the `agentvcs` skill advertises itself).
