"""agentvcs — Python SDK over the Rust core (protocol ``agentvcs/0.1``).

    import agentvcs as avcs

    with avcs.run("manifest.yaml", store=".") as run:
        run.on_patch(lambda ev: print("now running", ev.to_manifest))

        @avcs.step(agent_id="extractor")
        def extract(doc):
            prompt = run.manifest["extract.prompt"]["template"]
            ...

The SDK is a thin binding (ADR-0001, ADR-0007): canonical JSON, hashing, the
ledger and its invariants live in ``agentvcs._native`` (Rust). The legacy pure
Python implementation that used to own this import name lives in the repository
root's ``src/agentvcs`` until it moves to ``legacy/``.
"""

from . import _native
from ._core import (
    AgentvcsError,
    Manifest,
    NoActiveRun,
    PatchEvent,
    Run,
    StepContext,
    StepRace,
    cli,
    current_run,
    current_run_or_none,
    current_step,
    error_code,
    open_store,
    resolve_manifest,
    resume,
    run,
    step,
)

PROTOCOL: str = _native.PROTOCOL
CORE_VERSION: str = _native.VERSION
__version__ = "0.5.0.dev0"


def hash_json(value) -> str:
    """``hash(x)`` of PROTOCOL §1 (BLAKE3 over RFC 8785 canonical JSON)."""
    from ._core import _dumps

    return _native.hash_json(_dumps(value))


__all__ = [
    "AgentvcsError", "Manifest", "NoActiveRun", "PatchEvent", "Run", "StepContext",
    "StepRace", "cli", "current_run", "current_run_or_none", "current_step",
    "error_code", "hash_json", "open_store", "resolve_manifest", "resume", "run",
    "step", "PROTOCOL", "CORE_VERSION", "__version__",
]
