# agentvcs — Python SDK

Python binding for the agentvcs protocol `agentvcs/0.1`: the Rust core does the
hashing, the ledger and every invariant; this package gives a harness a run
context manager, a step decorator, live-patch hooks, checkpoint/restore hooks and
model wrappers. Design: `docs/adr/0007-python-sdk-layout.md`.

```bash
./dev.sh test     # venv in .venv, maturin develop --release, pytest (SDK + toy pipeline)
```

## API

```python
import agentvcs as avcs

with avcs.run(manifest, store=".", run_id=None) as run:   # dict, JSON/YAML path, or b3: id
    run.manifest["extract.prompt"]          # content of the active manifest's dimension
    run.on_patch(lambda ev: ...)            # PatchEvent: patch_id, from/to, semantic_diff, manifest
    run.checkpoint(lambda step: "ref")      # -> the step's checkpoint_ref
    run.restore(lambda ref: ...)            # called when a resumed run is entered

    @avcs.step(agent_id="extractor", inputs=None, outputs=None, metrics=None, on_race="rerun")
    def extract(doc):
        s = avcs.current_step()             # StepContext
        s.add_tokens(812, 133); s.metric("f1", 0.5)
        return {...}

    child = run.resume(from_step=18, manifest=other)   # a new run from a checkpoint
```

- An exception inside `with` ends the run `failed` (`KeyboardInterrupt`: `aborted`)
  and propagates; a normal exit ends it `completed`.
- Inputs/outputs are hashed into the store (bytes raw, `str` as UTF-8, anything
  else as canonical JSON); `inputs=`/`outputs=` choose what is recorded.
- Patches applied by another process (`agentvcs patch apply`) are seen at the next
  step boundary: the step decorator polls the ledger tail. A patch that lands
  mid-step makes the step re-run under the new manifest (`on_race="rerun"`) or
  raise `StepRace` (`on_race="raise"`).
- `run.propose_patch`, `run.gate`, `run.apply_patch`, `run.rollback` do the same
  in-process; `avcs.cli("blame", run_id, "--metric", "f1", store=".")` runs any
  CLI command in-process; `python -m agentvcs` is the CLI.
- Errors raise `avcs.AgentvcsError` with `.code` (`E_…`, `spec/cli/EXIT_CODES.md`).

## Integrations

```python
from agentvcs.integrations.openai_compat import OpenAICompatClient   # llama.cpp, vLLM, Ollama
from agentvcs.integrations.anthropic import AnthropicClient          # pip install anthropic

client = OpenAICompatClient("http://127.0.0.1:8080/v1")
client.complete("extract", {"document": text})   # model/sampling/prompt from the manifest
```

`agentvcs.testing` has local fakes of both servers (`FakeOpenAIServer`,
`FakeAnthropicServer`) for tests and offline examples.

## Name clash with the legacy package

The legacy pure-Python implementation in the repository root (`src/agentvcs`)
also imports as `agentvcs`. Install one or the other per virtualenv (ADR-0007 §2).
