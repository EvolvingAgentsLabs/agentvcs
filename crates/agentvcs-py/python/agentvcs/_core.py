"""Run, step and patch plumbing for harnesses (ADR-0007).

This module holds no protocol logic: hashing, canonical JSON, validation, the
ledger chain and its writer invariants all live in the Rust core behind
``agentvcs._native``. What lives here is harness ergonomics — a context manager,
a decorator, hooks — and the one policy the SDK adds on top of the protocol:
what to do when a patch lands while a step is running (§3 of the ADR).
"""

from __future__ import annotations

import contextvars
import dataclasses
import datetime as _dt
import functools
import json
import os
import time
from collections.abc import Mapping
from typing import Any, Callable, Iterator, Optional, Sequence, Union

from . import _native

AgentvcsError = _native.AgentvcsError

ManifestRef = Union[str, "os.PathLike[str]", Mapping]

_current_run: contextvars.ContextVar[Optional["Run"]] = contextvars.ContextVar(
    "agentvcs_run", default=None
)
_current_step: contextvars.ContextVar[Optional["StepContext"]] = contextvars.ContextVar(
    "agentvcs_step", default=None
)

# Codes that mean "the ledger moved under this writer" rather than "this step is wrong".
_RACE_CODES = ("E_STEP_MANIFEST", "E_STALE_STATE")


class NoActiveRun(RuntimeError):
    """A step was executed outside ``with agentvcs.run(...)``."""


class StepRace(RuntimeError):
    """A step kept losing races against patches and was not recorded."""


def error_code(e: BaseException) -> Optional[str]:
    """The protocol code (``E_…``) of an :class:`AgentvcsError`, else ``None``."""
    return getattr(e, "code", None)


def _now() -> str:
    t = _dt.datetime.now(_dt.timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _dumps(v: Any) -> str:
    return json.dumps(v, allow_nan=False, ensure_ascii=False, separators=(",", ":"))


def current_run() -> "Run":
    """The run entered with ``with agentvcs.run(...)`` in this context."""
    r = _current_run.get()
    if r is None:
        raise NoActiveRun("no active agentvcs run (use `with agentvcs.run(...)`)")
    return r


def current_run_or_none() -> Optional["Run"]:
    return _current_run.get()


def current_step() -> Optional["StepContext"]:
    """The step being executed in this context, or ``None``."""
    return _current_step.get()


# --------------------------------------------------------------------- manifest


class Manifest(Mapping):
    """A stored manifest, read-only: ``m["extract.prompt"]`` is that dimension's
    ``content``. ``m.id`` is its manifest id, ``m.value`` the normalized JSON."""

    def __init__(self, value: Mapping):
        self.value = value
        self.id: str = value["manifest_id"]
        self.name: Optional[str] = value.get("name")
        self._dims: Mapping = value.get("dimensions", {})

    def __getitem__(self, name: str) -> Any:
        return self._dims[name]["content"]

    def __iter__(self) -> Iterator[str]:
        return iter(self._dims)

    def __len__(self) -> int:
        return len(self._dims)

    def kind(self, name: str) -> str:
        return self._dims[name]["kind"]

    def content_hash(self, name: str) -> str:
        return self._dims[name]["content_hash"]

    def __repr__(self) -> str:
        return f"Manifest({self.id[:15]}…, {len(self)} dimensions)"


@dataclasses.dataclass(frozen=True)
class PatchEvent:
    """A patch entry the harness has just observed in its run's ledger."""

    patch_id: str
    from_manifest: str
    to_manifest: str
    applied_at_step: int
    rationale: str
    author: Mapping
    semantic_diff: Sequence[Mapping]
    rollback_of: Optional[str]
    seq: int
    manifest: Manifest  # the manifest now active (``to_manifest``)

    @property
    def changed_dimensions(self) -> list[str]:
        return [c.get("dimension") for c in self.semantic_diff if c.get("dimension")]


class StepContext:
    """What a step accumulates while it runs. Inside a ``@step`` function,
    ``agentvcs.current_step()`` returns it."""

    def __init__(self, run: "Run", agent_id: str, step_index: int, manifest: Manifest):
        self.run = run
        self.agent_id = agent_id
        self.step_index = step_index
        self.manifest = manifest
        self.tokens_in = 0
        self.tokens_out = 0
        self.metrics: dict[str, float] = {}
        self.extra_inputs: list[str] = []
        self.extra_outputs: list[str] = []
        self.attempt = 0

    def add_tokens(self, tokens_in: int = 0, tokens_out: int = 0) -> None:
        self.tokens_in += int(tokens_in)
        self.tokens_out += int(tokens_out)

    def metric(self, name: str, value: float) -> None:
        self.metrics[name] = value

    def add_input(self, value: Any) -> str:
        """Hash ``value`` into the store and list it among the step's inputs."""
        h = self.run.put(value)
        self.extra_inputs.append(h)
        return h

    def add_output(self, value: Any) -> str:
        h = self.run.put(value)
        self.extra_outputs.append(h)
        return h


# --------------------------------------------------------------------- run


class Run:
    """One run's ledger, seen from the harness. Create with :func:`run` or
    :func:`resume`; use as a context manager."""

    def __init__(
        self,
        store: "_native.NativeStore",
        *,
        manifest: Optional[ManifestRef] = None,
        run_id: Optional[str] = None,
        started: bool = False,
        parent: Optional[Mapping] = None,
    ):
        self._store = store
        self._manifest_ref = manifest
        self.run_id: Optional[str] = run_id
        self._started = started
        self.parent = parent
        self.checkpoint_ref: Optional[str] = (parent or {}).get("checkpoint_ref")
        self._on_patch: list[Callable[[PatchEvent], Any]] = []
        self._checkpoint_fn: Optional[Callable[[StepContext], Optional[str]]] = None
        self._restore_fn: Optional[Callable[[Optional[str]], Any]] = None
        self._restored = parent is None
        self._entered = False
        self._token: Optional[contextvars.Token] = None
        self._seen_seq = 0
        self._next_step = 0
        self._manifest: Optional[Manifest] = None
        self.ended = False
        self.patches: list[PatchEvent] = []
        self.stats = {"steps": 0, "reruns": 0, "stale_retries": 0}
        if started:
            self._load_state()

    # ------------------------------------------------------------ properties

    @property
    def store_dir(self) -> str:
        return self._store.dir

    @property
    def manifest(self) -> Manifest:
        """The manifest the harness should run its next step under. Refreshed at
        every step boundary (and by :meth:`sync`)."""
        if self._manifest is None:
            raise NoActiveRun("run not started")
        return self._manifest

    @property
    def next_step(self) -> int:
        return self._next_step

    # ------------------------------------------------------------ lifecycle

    def start(self) -> "Run":
        if self._started:
            return self
        mid = resolve_manifest(self._store, self._manifest_ref)
        args = ["run", "start", "--manifest", mid]
        if self.run_id:
            args += ["--run-id", self.run_id]
        out = _cli_ok(args, self._store.dir)
        self.run_id = out["run_id"]
        self._started = True
        self._load_state()
        return self

    def _load_state(self) -> None:
        st = self._store.run_state(self.run_id)
        self._seen_seq = st["next_seq"]
        self._next_step = st["next_step"]
        self.ended = st["ended"]
        if st["active"]:
            self._manifest = Manifest(self._store.get_manifest(st["active"]))

    def __enter__(self) -> "Run":
        self.start()
        self._entered = True
        self._token = _current_run.set(self)
        self._maybe_restore()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None:
                status = "completed"
            elif issubclass(exc_type, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                status = "aborted"
            else:
                status = "failed"
            self.end(status)
        finally:
            if self._token is not None:
                _current_run.reset(self._token)
                self._token = None
            self._entered = False
        return False

    def end(self, status: str = "completed") -> None:
        """Append ``run_end`` (idempotent; a run ended by someone else is left alone)."""
        if not self._started:
            return
        if self._store.run_state(self.run_id)["ended"]:
            self.ended = True
            return
        _cli_ok(["run", "end", self.run_id, "--status", status], self._store.dir)
        self.ended = True

    # ------------------------------------------------------------ hooks

    def on_patch(self, callback: Callable[[PatchEvent], Any]) -> Callable:
        """Call ``callback(event)`` when a patch entry appears in this run's
        ledger — applied in-process or by another process through the CLI. The
        harness learns about it by polling the ledger tail at every step boundary
        (ADR-0007 §3), so the callback runs before the first step under the new
        manifest. Usable as a decorator."""
        self._on_patch.append(callback)
        return callback

    def checkpoint(self, fn: Callable[[StepContext], Optional[str]]) -> Callable:
        """``fn(step) -> checkpoint_ref`` runs after each step; its string is stored
        as that step's ``checkpoint_ref`` (opaque to agentvcs). Usable as a decorator."""
        self._checkpoint_fn = fn
        return fn

    def restore(self, fn: Callable[[Optional[str]], Any]) -> Callable:
        """``fn(checkpoint_ref)`` runs once when a resumed run is entered (or right
        away, if it already was). Usable as a decorator."""
        self._restore_fn = fn
        self._maybe_restore()
        return fn

    def _maybe_restore(self) -> None:
        if self._restored or not self._entered or self._restore_fn is None:
            return
        self._restored = True
        self._restore_fn(self.checkpoint_ref)

    # ------------------------------------------------------------ ledger polling

    def sync(self) -> list[PatchEvent]:
        """Read the ledger tail; fire ``on_patch`` for every new patch entry.
        Returns the new events. Cheap when nothing changed (one tail read)."""
        st = self._store.run_state(self.run_id)
        self._next_step = st["next_step"]
        self.ended = st["ended"]
        if st["next_seq"] == self._seen_seq:
            return []
        events = []
        for e in self._store.ledger(self.run_id, self._seen_seq):
            self._seen_seq = e["seq"] + 1
            if e["kind"] != "patch":
                continue
            b = e["body"]
            m = Manifest(self._store.get_manifest(b["to_manifest"]))
            self._manifest = m
            ev = PatchEvent(
                patch_id=b["patch_id"],
                from_manifest=b["from_manifest"],
                to_manifest=b["to_manifest"],
                applied_at_step=b["applied_at_step"],
                rationale=b["rationale"],
                author=b["author"],
                semantic_diff=b["semantic_diff"],
                rollback_of=b["rollback_of"],
                seq=e["seq"],
                manifest=m,
            )
            self.patches.append(ev)
            events.append(ev)
            for cb in list(self._on_patch):
                cb(ev)
        if st["active"] and (self._manifest is None or self._manifest.id != st["active"]):
            self._manifest = Manifest(self._store.get_manifest(st["active"]))
        return events

    # ------------------------------------------------------------ store helpers

    def put(self, value: Any) -> str:
        """Hash a value into the store: bytes raw, str as UTF-8, anything else as
        canonical JSON. Returns its ``b3:`` id."""
        if isinstance(value, (bytes, bytearray, memoryview)):
            return self._store.put_blob(bytes(value))
        if isinstance(value, str):
            return self._store.put_blob(value.encode("utf-8"))
        try:
            text = _dumps(value)
        except (TypeError, ValueError) as e:
            raise TypeError(
                f"cannot hash {type(value).__name__} into the store ({e}); pass "
                "inputs=/outputs= to @agentvcs.step to choose what is recorded"
            ) from None
        return self._store.put_json(text)

    def get(self, object_id: str) -> bytes:
        return self._store.get_object(object_id)

    def log(self) -> list:
        return self._store.ledger(self.run_id, 0)

    # ------------------------------------------------------------ steps

    def call_step(
        self,
        agent_id: str,
        fn: Callable,
        args: Sequence = (),
        kwargs: Optional[Mapping] = None,
        *,
        inputs: Optional[Callable[..., Sequence]] = None,
        outputs: Optional[Callable[[Any], Sequence]] = None,
        metrics: Optional[Callable[..., Mapping]] = None,
        on_race: str = "rerun",
        max_reruns: int = 3,
    ) -> Any:
        """Execute ``fn(*args, **kwargs)`` as one step of this run and record it.

        If a patch lands while ``fn`` runs, the step ran under a manifest that is
        no longer active and the core refuses to record it (``E_STEP_MANIFEST``).
        With ``on_race="rerun"`` (default) the SDK fires ``on_patch`` and executes
        ``fn`` again under the new manifest, so the ledger never claims a step ran
        under a manifest it did not run under. ``on_race="raise"`` raises instead
        (for steps with side effects that must not repeat)."""
        if _current_step.get() is not None:
            raise RuntimeError("agentvcs steps do not nest")
        kwargs = dict(kwargs or {})
        if not self._started:
            raise NoActiveRun("run not started")
        for attempt in range(max_reruns + 1):
            self.sync()
            if self.ended:
                _raise({"error": {"code": "E_AFTER_RUN_END", "message": f"run {self.run_id} has ended"}})
            ctx = StepContext(self, agent_id, self._next_step, self.manifest)
            ctx.attempt = attempt
            token = _current_step.set(ctx)
            started_at = _now()
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
            finally:
                _current_step.reset(token)
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            ended_at = _now()
            if metrics is not None:
                ctx.metrics.update(metrics(result, *args, **kwargs))
            ins = list(inputs(*args, **kwargs)) if inputs else list(args) + ([kwargs] if kwargs else [])
            outs = list(outputs(result)) if outputs else ([] if result is None else [result])
            body = {
                "step_index": ctx.step_index,
                "manifest_id": ctx.manifest.id,
                "agent_id": agent_id,
                "inputs": [self.put(v) for v in ins] + ctx.extra_inputs,
                "outputs": [self.put(v) for v in outs] + ctx.extra_outputs,
                "started_at": started_at,
                "ended_at": ended_at,
                "tokens": {"in": ctx.tokens_in, "out": ctx.tokens_out},
                "latency_ms": latency_ms,
                "checkpoint_ref": self._checkpoint_fn(ctx) if self._checkpoint_fn else None,
            }
            if ctx.metrics:
                body["metrics"] = ctx.metrics
            out = self._record(body)
            if out is not None:
                self._after_record(out)
                return result
            if on_race != "rerun":
                raise StepRace(
                    f"a patch landed while step {ctx.step_index} ({agent_id}) ran; not recorded"
                )
            self.stats["reruns"] += 1
        raise StepRace(f"step {agent_id} lost {max_reruns + 1} races against patches")

    def _record(self, body: Mapping) -> Optional[dict]:
        """Append a step. ``None`` means the active manifest changed under it."""
        text = _dumps(body)
        for _ in range(20):
            try:
                return self._store.step_record(self.run_id, text)
            except AgentvcsError as e:
                code = error_code(e)
                if code == "E_STEP_MANIFEST":
                    return None
                if code == "E_STALE_STATE":  # another writer appended mid-call
                    self.stats["stale_retries"] += 1
                    continue
                raise
        raise StepRace("ledger kept moving under the writer (E_STALE_STATE x20)")

    def _after_record(self, out: Mapping) -> None:
        self.stats["steps"] += 1
        self._next_step = out["step_index"] + 1
        if out["seq"] == self._seen_seq:  # nothing unseen before our own entry
            self._seen_seq += 1

    def record_step(self, body: Mapping) -> dict:
        """Low-level: append a StepRecord body as given (the core fills
        ``step_index``/``manifest_id``/``checkpoint_ref`` when absent)."""
        out = self._store.step_record(self.run_id, _dumps(body))
        self._after_record(out)
        return out

    # ------------------------------------------------------------ patches in-process

    def propose_patch(
        self,
        to: ManifestRef,
        rationale: str,
        evidence: Sequence[int] = (),
        author: str = "agent:sdk",
    ) -> str:
        """``patch propose`` from the active manifest to ``to``; returns the patch id."""
        to_id = resolve_manifest(self._store, to)
        st = self._store.run_state(self.run_id)
        out = _cli_ok(
            [
                "patch", "propose", self.run_id, "--from", st["active"], "--to", to_id,
                "--rationale", rationale, "--evidence", ",".join(map(str, evidence)),
                "--author", author,
            ],
            self._store.dir,
        )
        return out["patch_id"]

    def gate(self, patch_id: str, suite: Union[str, os.PathLike]) -> dict:
        """``gate run``; returns the GateResult (``passed`` may be false)."""
        code, out = _native.cli(["gate", "run", patch_id, "--suite", os.fspath(suite)], None, self._store.dir)
        if not out.get("ok"):
            _raise(out)
        return out["gate_result"]

    def apply_patch(self, patch_id: str) -> list[PatchEvent]:
        """Apply a gated patch to this run now and fire ``on_patch`` (in-process)."""
        self._store.patch_apply(patch_id, None)
        return self.sync()

    def rollback(self, patch_id: str, rationale: Optional[str] = None) -> list[PatchEvent]:
        args = ["patch", "rollback", patch_id]
        if rationale:
            args += ["--rationale", rationale]
        _cli_ok(args, self._store.dir)
        return self.sync()

    # ------------------------------------------------------------ resume

    def resume(
        self,
        from_step: int,
        manifest: Optional[ManifestRef] = None,
        run_id: Optional[str] = None,
    ) -> "Run":
        """Create the child run that re-executes from ``from_step`` (default
        manifest: the current one). Hooks are inherited; entering the child calls
        the ``restore`` hook with the parent's ``checkpoint_ref`` for step
        ``from_step - 1``."""
        child = resume(self.run_id, from_step, manifest or self.manifest.id, store=self._store, run_id=run_id)
        child._on_patch = list(self._on_patch)
        child._checkpoint_fn = self._checkpoint_fn
        if child._restore_fn is None:
            child._restore_fn = self._restore_fn
        return child

    def __repr__(self) -> str:
        return f"Run({self.run_id!r}, next_step={self._next_step})"


# --------------------------------------------------------------------- functions


def _raise(out: Mapping) -> None:
    err = out.get("error", {})
    e = AgentvcsError(f"{err.get('code', 'E_UNKNOWN')}: {err.get('message', '')}")
    e.code = err.get("code")
    raise e


def _cli_ok(args: Sequence[str], dir: str) -> dict:
    code, out = _native.cli(list(args), None, dir)
    if not out.get("ok"):
        _raise(out)
    return out


def cli(*args: str, stdin: Optional[str] = None, store: Union[str, os.PathLike] = ".") -> dict:
    """Any CLI command, in-process: ``cli("blame", "r1", "--metric", "f1")``.
    Raises :class:`AgentvcsError` on ``ok: false``."""
    code, out = _native.cli(list(args), stdin, os.fspath(store))
    if not out.get("ok"):
        _raise(out)
    return out


PathOrId = Union[str, "os.PathLike[str]"]


def _manifest_arg(ref: PathOrId) -> str:
    """A manifest id passes through; a path is made absolute (the CLI resolves
    relative paths against the store directory, not the caller's cwd)."""
    s = os.fspath(ref)
    return s if s.startswith("b3:") and not os.path.exists(s) else os.path.abspath(s)


def merge_prepare(
    base: PathOrId,
    ours: PathOrId,
    theirs: PathOrId,
    *,
    ours_run: Optional[PathOrId] = None,
    theirs_run: Optional[PathOrId] = None,
    metrics: Sequence[str] = (),
    store: Union[str, os.PathLike] = ".",
) -> dict:
    """``agentvcs merge prepare`` (spec/MERGE.md §2, v0.2 draft): mechanical
    results and every conflict with both sides, diffs and run evidence. Manifests
    and runs are ids in the store or files (audit bundles for runs)."""
    args = ["merge", "prepare", "--base", _manifest_arg(base), "--ours", _manifest_arg(ours),
            "--theirs", _manifest_arg(theirs)]
    for flag, r in (("--ours-run", ours_run), ("--theirs-run", theirs_run)):
        if r is not None:
            s = os.fspath(r)
            args += [flag, os.path.abspath(s) if os.path.exists(s) else s]
    for m in metrics:
        args += ["--metric", m]
    return _cli_ok(args, os.fspath(store))


def merge_commit(
    base: PathOrId,
    ours: PathOrId,
    theirs: PathOrId,
    resolution: Union[str, "os.PathLike[str]"],
    *,
    suite: Optional[Union[str, "os.PathLike[str]"]] = None,
    store: Union[str, os.PathLike] = ".",
) -> dict:
    """``agentvcs merge commit`` (spec/MERGE.md §4, v0.2 draft): checks the
    resolution file, stores the merged manifest and the merge record, and gates it
    with ``suite`` when given. A failed gate is not an exception: the record is
    stored and ``out["gate"]["passed"]`` is ``False`` (CLI exit 1)."""
    args = ["merge", "commit", "--base", _manifest_arg(base), "--ours", _manifest_arg(ours),
            "--theirs", _manifest_arg(theirs), "--resolution", os.path.abspath(os.fspath(resolution))]
    if suite is not None:
        args += ["--suite", os.path.abspath(os.fspath(suite))]
    return _cli_ok(args, os.fspath(store))


def open_store(store: Union[str, os.PathLike, "_native.NativeStore"] = ".", init: bool = True):
    if isinstance(store, _native.NativeStore):
        return store
    return _native.NativeStore(os.fspath(store), init)


def resolve_manifest(store: "_native.NativeStore", ref: Optional[ManifestRef]) -> str:
    """A manifest id for ``ref``: a mapping (authoring form), a JSON/YAML file, or
    an id already in the store. Mappings and files are snapshotted."""
    if ref is None:
        raise ValueError("a manifest is required")
    if isinstance(ref, Manifest):
        return ref.id
    if isinstance(ref, Mapping):
        return store.snapshot_json(_dumps(dict(ref)))["manifest_id"]
    s = os.fspath(ref)
    if os.path.isfile(s):
        return _cli_ok(["snapshot", os.path.abspath(s)], store.dir)["manifest_id"]
    if s.startswith("b3:"):
        store.get_manifest(s)  # raises E_NOT_FOUND if absent
        return s
    raise AgentvcsError(f"E_NOT_FOUND: {s!r} is neither a manifest file nor a manifest id")


def run(
    manifest: ManifestRef,
    store: Union[str, os.PathLike, "_native.NativeStore"] = ".",
    run_id: Optional[str] = None,
) -> Run:
    """A new run under ``manifest``; ``run_start`` is written on ``__enter__``
    (or :meth:`Run.start`). The store is created if missing."""
    return Run(open_store(store), manifest=manifest, run_id=run_id)


def resume(
    parent_run_id: str,
    from_step: int,
    manifest: ManifestRef,
    store: Union[str, os.PathLike, "_native.NativeStore"] = ".",
    run_id: Optional[str] = None,
    restore: Optional[Callable[[Optional[str]], Any]] = None,
) -> Run:
    """Create a child run of ``parent_run_id`` from ``from_step`` (CLI ``resume``)
    and return it, already started. ``restore`` (or a hook registered later)
    receives the parent's ``checkpoint_ref`` when the child is entered."""
    s = open_store(store, init=False)
    mid = resolve_manifest(s, manifest)
    args = ["resume", parent_run_id, "--from-step", str(from_step), "--manifest", mid]
    if run_id:
        args += ["--run-id", run_id]
    out = _cli_ok(args, s.dir)
    child = Run(s, manifest=mid, run_id=out["run_id"], started=True, parent=out["parent"])
    child._restore_fn = restore
    return child


def step(
    agent_id: Optional[str] = None,
    *,
    inputs: Optional[Callable[..., Sequence]] = None,
    outputs: Optional[Callable[[Any], Sequence]] = None,
    metrics: Optional[Callable[..., Mapping]] = None,
    on_race: str = "rerun",
    max_reruns: int = 3,
) -> Callable:
    """Decorator: each call of the function is one StepRecord of the active run.

    Inputs default to the positional arguments (plus the keyword arguments as one
    object), outputs to the return value; each is hashed into the store. Tokens
    and metrics come from ``agentvcs.current_step()`` inside the function (the
    model integrations add tokens there) and from ``metrics(result, *args,
    **kwargs)``. Calling a step outside a run raises :class:`NoActiveRun`."""

    def deco(fn: Callable) -> Callable:
        aid = agent_id or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return current_run().call_step(
                aid, fn, args, kwargs, inputs=inputs, outputs=outputs, metrics=metrics,
                on_race=on_race, max_reruns=max_reruns,
            )

        wrapper.agent_id = aid  # type: ignore[attr-defined]
        return wrapper

    return deco
