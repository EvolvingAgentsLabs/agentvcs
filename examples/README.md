# agentvcs examples

Each folder is a self-contained, runnable example. They progress from "what is
this" to "version a real agent in your stack".

## Start here

| Example | What it shows | Run |
| --- | --- | --- |
| [`refund-agent/`](refund-agent/) | The smallest thing: a fluid agent you `commit`, `eval`, and `crystallize` into a deterministic recipe. | see its README |
| [`agent-loop-demo/`](agent-loop-demo/) | The "fire test" — a simulated autonomous coding agent driving agentvcs end-to-end (commit → eval → rollback → freeze). | `bash run.sh` |
| [`business-cases/`](business-cases/) | **The same power, in plain English** — five everyday situations (a bot that quietly gets worse, a fork nobody merged, wasted context, a poisoned shared memory) that each end in a one-line recommendation, with no math on screen. Start here for the "why". | `bash run.sh` |
| [`evolution-diagnostics/`](evolution-diagnostics/) | **Is the self-modification actually working?** The technical companion to `business-cases/`: five self-asserting acts over real evals — `price` catches an error catastrophe git can't see, branch-and-select cures it, `branch` flags Muller's ratchet, `infobits` bounds the value of context, `contain` sizes a poisoned-memory's verification rate. | `bash run.sh` |

## Zero-friction trace capture (passive providers)

The agent just works; `commit` vacuums its native session log. One module per
runtime, one on-disk format.

| Example | Provider | What it shows |
| --- | --- | --- |
| [`claude-code-trace/`](claude-code-trace/) | `claude-code` | Commit captures the live Claude Code session — no trace file to maintain. |
| [`claude-code-task/`](claude-code-task/) | `claude-code` | Validation harness putting a **real** Claude Code agent under agentvcs (the PMF test). |
| [`eve/`](eve/) | `vercel-eve` | **Time-Travel Debugging for [Vercel eve](https://eve.dev):** a bridge hook captures eve's stream events; `rollback` undoes a hallucinated turn (code + trace together) and the session resumes. Runnable offline: `bash eve/demo.sh`. |

## Multidimensional features

| Example | Feature | What it shows |
| --- | --- | --- |
| [`eve-evolve-merge/`](eve-evolve-merge/) | `merge` + `swarm` | **The core scenario, end-to-end on [Vercel eve](https://vercel.com/eve):** a self-evolving agent rewrites its own skill and spawns a sub-agent at run-time, the team evolves the same files in git, and `merge` fuses both — skill conflict synthesized (`resolved_files`), sub-agent swarm merged node-by-node. Runnable offline: `bash eve-evolve-merge/demo.sh`. |
| [`nanoloop-reconcile/`](nanoloop-reconcile/) | `merge --reconcile` | A reference reconciler for merging two agent branches — reconciles goal + trace **and** synthesizes the conflict-free code (`resolved_files`), with a worked write-up in [`ARTICLE.md`](nanoloop-reconcile/ARTICLE.md). |
| [`blind-fleet-task/`](blind-fleet-task/) | fleet / blind eval | A fair blind A/B test — does agentvcs actually change agent outcomes? |
| [`skillopt-soul/`](skillopt-soul/) | Soul (opt-in crypto) | The evolution seam of *Souls of Silicon*: signed traces ⇆ skill optimization. Requires `--with-soul`. |

## Assets

| Example | What it is |
| --- | --- |
| [`recording/`](recording/) | Screencast/recording assets for the landing page. |

---

**Crypto is opt-in.** Every example above is a pure multidimensional VCS by
default — no keys, no signatures. Only `skillopt-soul/` (and any repo created with
`agentvcs init --with-soul`) touches the Ed25519 Soul / DeSoc layer.
