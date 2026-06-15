# nanoLoop-powered merge reconciliation

A reference reconciler for `agentvcs merge --reconcile`. When two agent branches
diverge, agentvcs merges the **code** deterministically and hands the
**reasoning** (goals + traces + diffs + conflicts) to this process, which uses
[nanoLoop](https://github.com/ismaelfaro/nanoLoop)'s model layer to synthesize a
single *Consolidated Knowledge Trace* for the merge commit.

See **[ARTICLE.md](./ARTICLE.md)** for the write-up and a worked SQL-vs-NoSQL example.

## How it fits

agentvcs core never calls an LLM. The `--reconcile CMD` seam (mirroring
`replay --exec`) pipes a JSON bundle to `CMD` on stdin and reads back
`{goal, trace, notes}` on stdout.

```
bundle (stdin)                         reconciler                response (stdout)
{base, ours, theirs, conflicts}  ──►   nanoLoop / OpenRouter  ──►  {goal, trace, notes}
```

## Run it (built-in command)

nanoLoop ships a first-class `nanoloop reconcile` subcommand. The `.env` path is
passed because the merge runs from the agentvcs repo, not nanoLoop's dir, so the
OpenRouter key may not be on the ambient environment:

```bash
agentvcs merge <branch> --force --reconcile "nanoloop reconcile /path/to/nanoLoop/.env"
```

Without `--reconcile`, merge uses a deterministic fallback (a mechanical merge
marker; both parent traces remain reachable via the commit's two parents).

## Files

- `reconcile.py` — a self-contained **reference** reconciler (no nanoLoop CLI
  needed), in case you want to wire a different brain. The built-in
  `nanoloop reconcile` does the same thing.
- `ARTICLE.md` — the story + the real reconciled output.
