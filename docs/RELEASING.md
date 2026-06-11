# Releasing agentvcs to PyPI

Publishing is automated by [`.github/workflows/release.yml`](../.github/workflows/release.yml):
push a `vX.Y.Z` tag and it builds, `twine check`s, and publishes to PyPI using a
PyPI **API token** stored as the repo secret `PYPI_API_TOKEN`.

## One-time setup (required before the first release)

Do this once; it takes ~2 minutes and needs your PyPI login.

1. Sign in at https://pypi.org → **Account settings → API tokens → Add API token**.
   For the *first* publish the project doesn't exist yet, so scope the token to
   **Entire account**. (After the first release you can replace it with a token
   scoped to just the `agentvcs` project.)
2. In the GitHub repo: **Settings → Secrets and variables → Actions → New
   repository secret**, named `PYPI_API_TOKEN`, value = the `pypi-...` token.

That's it. The `pypi` GitHub environment in the workflow's `environment:` just
groups the deployment (add reviewers there if you want a manual approval gate).

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

## Alternative: trusted publishing (OIDC) instead of a token

If you'd rather store no secret, PyPI supports trusted publishing via OIDC. Add a
publisher at https://pypi.org/manage/account/publishing/ whose claims match this
repo exactly — **Owner** `EvolvingAgentsLabs`, **Repository** `agentvcs`,
**Workflow name** `release.yml`, **Environment** `pypi` — then drop the `password:`
line and add `permissions: { id-token: write }` to the publish job. The claim
fields must match precisely or PyPI rejects with `invalid-publisher`.

## Test it first (optional)

Point a run at TestPyPI by adding `with: { repository-url: https://test.pypi.org/legacy/ }`
to the publish step and configuring a matching trusted publisher on test.pypi.org.
