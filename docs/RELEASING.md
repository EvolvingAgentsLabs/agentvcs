# Releasing agentvcs to PyPI

Publishing is automated by [`.github/workflows/release.yml`](../.github/workflows/release.yml):
push a `vX.Y.Z` tag and it builds, `twine check`s, and publishes to PyPI via
**trusted publishing (OIDC)** — no stored secret to manage or rotate.

## One-time setup (required before the first publish)

Do this once; it takes ~2 minutes and needs your PyPI login. PyPI must already
know to trust this workflow, or the publish job fails with `invalid-publisher`.

1. Sign in at https://pypi.org → **Account → Publishing → Add a new pending
   publisher** (the project doesn't exist yet, so it's a *pending* publisher).
2. Enter claims that match this repo **exactly** — any mismatch is rejected:
   - **PyPI Project Name:** `agentvcs`
   - **Owner:** `EvolvingAgentsLabs`
   - **Repository name:** `agentvcs`
   - **Workflow name:** `release.yml`
   - **Environment name:** `pypi`

The workflow already grants the publish job `permissions: id-token: write` and
runs in the `pypi` environment, which is what the OIDC exchange needs. (Add
reviewers to that environment in GitHub if you want a manual approval gate.)

> Prefer an API token instead? Add a `PYPI_API_TOKEN` repo secret and put
> `password: ${{ secrets.PYPI_API_TOKEN }}` back on the publish step (and drop
> the `id-token: write` permission). Trusted publishing is preferred because
> there's no long-lived credential to leak or rotate.

## Cut a release

```bash
# bump the version in pyproject.toml and src/agentvcs/__init__.py (keep them equal)
git commit -am "Release v0.1.1"
git tag v0.1.1
git push origin main --tags
```

Watch the run under the repo's **Actions → Release to PyPI**. On success the
version appears at https://pypi.org/project/agentvcs/ and `pip install agentvcs`
works.

## Test it first (optional)

Point a run at TestPyPI by adding `with: { repository-url: https://test.pypi.org/legacy/ }`
to the publish step and configuring a matching trusted publisher on test.pypi.org.
