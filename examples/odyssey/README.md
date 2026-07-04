# odyssey trace provider

Version a robotics **mission run** with agentvcs. The `odyssey` trace provider reads
[lovell-odyssey](https://github.com/lovellai-dev/odyssey)'s native SQLite store
(`~/.odyssey/missions.db`) and normalizes a run into a commit's trace dimension: the
objective as the user turn, each task's `result_summary` as an assistant turn, and a closing
status + `overall_grade`.

The result: a commit versions not just the agent's code and goal, but **what its mission
actually produced** (success_rate, per-checkpoint metrics, grade), pinned to the exact code
that produced it.

## Run it

```bash
python demo.py
```

The demo is self-contained (it fabricates an odyssey-shaped `missions.db`, so you do not need
odyssey installed), then commits and prints the captured trace:

```
committed a1b2c3d4e5f6 with an odyssey trace of 4 messages:

  [     user] Patrol the facility: visit every checkpoint and report it clear.
  [assistant] [training] warmup -> COMPLETED
  [assistant] [evaluation] patrol-eval -> COMPLETED
  [assistant] mission COMPLETED overall_grade=1.0
```

## Wire it into your own agent

Point `agent.json`'s `trace` at the provider:

```json
{
  "goal": "Patrol the facility and report each checkpoint clear.",
  "models": [{"provider": "google", "model": "gemma-4-26b-a4b-it"}],
  "trace": {"provider": "odyssey", "db": "~/.odyssey/missions.db", "mission": "<id>"}
}
```

- `db` — optional, defaults to `~/.odyssey/missions.db`; relative paths resolve against the
  repo workdir.
- `mission` — optional, defaults to the most recent mission.

Then every `agentvcs commit` captures the latest (or named) mission run. The provider uses
only the standard library (`sqlite3` + `json`), so agentvcs stays dependency-free and never
imports odyssey.

## Where it came from

This provider was built while developing
[**evolving-robot**](https://github.com/EvolvingAgentsLabs/evolving-robot) — a 2D robot that
evolves its own skills, versioned by agentvcs, orchestrated by odyssey, and gated by
[skill-map](https://github.com/crystian/skill-map). Dogfooding that loop is what surfaced the
need to version mission outcomes alongside code.
