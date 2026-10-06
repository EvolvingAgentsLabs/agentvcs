//! The command table (`spec/cli/COMMANDS.md`): one source for the argv parser,
//! `--help` and the MCP tool list.

/// A flag of a command. Names are without the leading `--`.
#[derive(Debug, Clone, Copy)]
pub struct Flag {
    pub name: &'static str,
    /// Takes a value (`--name v` / `--name=v`); otherwise boolean.
    pub value: bool,
    pub required: bool,
    /// May be given more than once (`--metric a --metric b`; an array over MCP).
    pub multi: bool,
    pub help: &'static str,
}

#[derive(Debug, Clone, Copy)]
pub struct Cmd {
    /// Command words, e.g. `["patch", "propose"]`.
    pub words: &'static [&'static str],
    /// MCP tool name.
    pub tool: &'static str,
    /// Positional arguments (all required).
    pub positionals: &'static [(&'static str, &'static str)],
    pub flags: &'static [Flag],
    pub help: &'static str,
    /// Reads a JSON body on stdin (`body` argument over MCP).
    pub stdin: bool,
}

const fn f(name: &'static str, value: bool, required: bool, help: &'static str) -> Flag {
    Flag {
        name,
        value,
        required,
        multi: false,
        help,
    }
}

/// A repeatable flag that takes a value.
const fn many(name: &'static str, help: &'static str) -> Flag {
    Flag {
        name,
        value: true,
        required: false,
        multi: true,
        help,
    }
}

pub const COMMANDS: &[Cmd] = &[
    Cmd {
        words: &["init"],
        tool: "init",
        positionals: &[],
        flags: &[],
        help: "Create the .agentvcs store in the project (idempotent).",
        stdin: false,
    },
    Cmd {
        words: &["hash"],
        tool: "hash",
        positionals: &[("file", "file to hash")],
        flags: &[f(
            "canonical",
            false,
            false,
            "parse the file as JSON and hash its RFC 8785 form (returned as `canonical`)",
        )],
        help: "BLAKE3 of a file's bytes, or of its canonical JSON.",
        stdin: false,
    },
    Cmd {
        words: &["snapshot"],
        tool: "snapshot",
        positionals: &[("manifest", "manifest file (.json, .yaml or .yml)")],
        flags: &[],
        help: "Validate a harness manifest (authoring form allowed), fill its hashes and store it.",
        stdin: false,
    },
    Cmd {
        words: &["run", "start"],
        tool: "run_start",
        positionals: &[],
        flags: &[
            f("manifest", true, true, "manifest id in the store, or a manifest file"),
            f("run-id", true, false, "run id (default: generated)"),
        ],
        help: "Start a run: writes its run_start entry.",
        stdin: false,
    },
    Cmd {
        words: &["run", "end"],
        tool: "run_end",
        positionals: &[("run", "run id")],
        flags: &[f("status", true, false, "completed (default), aborted or failed")],
        help: "End a run: writes its run_end entry.",
        stdin: false,
    },
    Cmd {
        words: &["step", "record"],
        tool: "step_record",
        positionals: &[("run", "run id")],
        flags: &[],
        help: "Append a StepRecord read from stdin (step_index, manifest_id and checkpoint_ref are filled in when absent).",
        stdin: true,
    },
    Cmd {
        words: &["diff"],
        tool: "diff",
        positionals: &[
            ("a", "manifest id in the store, or a manifest file"),
            ("b", "manifest id in the store, or a manifest file"),
        ],
        flags: &[],
        help: "Semantic diff of two manifests (spec/SEMANTIC_DIFF.md).",
        stdin: false,
    },
    Cmd {
        words: &["patch", "propose"],
        tool: "patch_propose",
        positionals: &[("run", "run id")],
        flags: &[
            f("from", true, true, "manifest id the patch starts from"),
            f("to", true, true, "target manifest: id in the store, or a manifest file"),
            f("rationale", true, true, "why"),
            f("evidence", true, false, "comma-separated step indexes of this run"),
            f("author", true, false, "type:id, type human or agent (default human:cli)"),
        ],
        help: "Propose a patch; prints its id and semantic diff.",
        stdin: false,
    },
    Cmd {
        words: &["gate", "run"],
        tool: "gate_run",
        positionals: &[("patch_id", "patch id")],
        flags: &[f(
            "suite",
            true,
            true,
            "suite file (YAML/JSON) with `command` and `thresholds`",
        )],
        help: "Run a suite's command against a proposed patch and record the gate result (exit 1 when it does not pass).",
        stdin: false,
    },
    Cmd {
        words: &["patch", "apply"],
        tool: "patch_apply",
        positionals: &[("patch_id", "patch id")],
        flags: &[f(
            "at-step",
            true,
            false,
            "step index the patch applies at (must be the run's next step; default: it)",
        )],
        help: "Apply a gated patch to its run (refuses ungated patches, exit 5).",
        stdin: false,
    },
    Cmd {
        words: &["patch", "rollback"],
        tool: "patch_rollback",
        positionals: &[("patch_id", "the applied patch to revert")],
        flags: &[
            f("rationale", true, false, "why (default: rollback of <id>)"),
            f("evidence", true, false, "comma-separated step indexes"),
            f("author", true, false, "type:id (default human:cli)"),
        ],
        help: "Revert an applied patch (no gate needed).",
        stdin: false,
    },
    Cmd {
        words: &["resume"],
        tool: "resume",
        positionals: &[("run", "parent run id")],
        flags: &[
            f("from-step", true, true, "first step index the child re-executes"),
            f("manifest", true, true, "manifest id (or file) the child runs under"),
            f("run-id", true, false, "child run id (default: generated)"),
        ],
        help: "Create a child run from a parent's step; the harness restores the returned checkpoint_ref.",
        stdin: false,
    },
    Cmd {
        words: &["log"],
        tool: "log",
        positionals: &[("run", "run id")],
        flags: &[],
        help: "Every ledger entry of a run.",
        stdin: false,
    },
    Cmd {
        words: &["blame"],
        tool: "blame",
        positionals: &[("target", "run id or audit bundle file")],
        flags: &[f("metric", true, true, "metric name")],
        help: "Segment a run by manifest and attribute metric deltas to patches (spec/BLAME.md).",
        stdin: false,
    },
    Cmd {
        words: &["bisect"],
        tool: "bisect",
        positionals: &[("run", "run id")],
        flags: &[
            f("metric", true, true, "metric name"),
            f("bad", true, true, "when the metric is bad, e.g. '<0.5'"),
            f("exec", true, true, "shell command that re-executes one candidate and prints the metric as JSON"),
        ],
        help: "Binary search over the run's patches for the first one under which the metric is bad.",
        stdin: false,
    },
    Cmd {
        words: &["freeze"],
        tool: "freeze",
        positionals: &[("manifest_id", "manifest id")],
        flags: &[],
        help: "Freeze a manifest; requires a passed gate naming it (exit 5 otherwise).",
        stdin: false,
    },
    Cmd {
        words: &["export", "audit"],
        tool: "export_audit",
        positionals: &[("run", "run id")],
        flags: &[f(
            "output",
            true,
            false,
            "write the bundle to this file (-o); without it the bundle is in the output",
        )],
        help: "Export a run's audit bundle (spec/PROTOCOL.md §4). Overwriting a file needs --yes.",
        stdin: false,
    },
    Cmd {
        words: &["verify"],
        tool: "verify",
        positionals: &[("target", "run id or audit bundle file")],
        flags: &[],
        help: "Verify a ledger (spec/LEDGER.md); exit 1 when it has violations.",
        stdin: false,
    },
    Cmd {
        words: &["merge", "prepare"],
        tool: "merge_prepare",
        positionals: &[],
        flags: &[
            f("base", true, true, "common ancestor: manifest id in the store, or a manifest file"),
            f("ours", true, true, "our side: manifest id or file"),
            f("theirs", true, true, "their side: manifest id or file"),
            f("ours-run", true, false, "run id or audit bundle file whose patches are our evidence"),
            f("theirs-run", true, false, "run id or audit bundle file whose patches are their evidence"),
            many("metric", "metric whose blame delta each evidence patch carries (repeatable)"),
        ],
        help: "Three-way merge, mechanical part: auto results and every conflict with both sides, diffs and run evidence (spec/MERGE.md §2, v0.2 draft).",
        stdin: false,
    },
    Cmd {
        words: &["merge", "commit"],
        tool: "merge_commit",
        positionals: &[],
        flags: &[
            f("base", true, true, "common ancestor: manifest id in the store, or a manifest file"),
            f("ours", true, true, "our side: manifest id or file"),
            f("theirs", true, true, "their side: manifest id or file"),
            f("resolution", true, true, "merge_resolution file (spec/MERGE.md §3)"),
            f("suite", true, false, "gate the merged manifest with this suite, as `gate run` does (exit 1 when it does not pass)"),
        ],
        help: "Check a merge resolution, store the merged manifest (parent_ids [ours, theirs]) and the merge record, optionally gate it (spec/MERGE.md §4, v0.2 draft).",
        stdin: false,
    },
];

/// Find the command named by the leading words of `args`.
pub fn lookup(args: &[String]) -> Option<&'static Cmd> {
    COMMANDS
        .iter()
        .filter(|c| {
            c.words.len() <= args.len() && c.words.iter().zip(args).all(|(w, a)| *w == a.as_str())
        })
        .max_by_key(|c| c.words.len())
}
