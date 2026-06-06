# Releasing agentvcs to PyPI

Publishing is automated by [`.github/workflows/release.yml`](../.github/workflows/release.yml):
push a `vX.Y.Z` tag and it builds, `twine check`s, and publishes to PyPI via
**trusted publishing** (OIDC — no API token is ever stored).

## One-time setup (required before the first release)

Do this once on PyPI; it takes ~2 minutes and needs your PyPI login.

1. Sign in at https://pypi.org and go to **Your projects → Publishing** (or
   https://pypi.org/manage/account/publishing/).
2. Add a **pending publisher** (so you can claim the name without uploading first):
   - **PyPI project name**: `agentvcs`
   - **Owner**: `EvolvingAgentsLabs`
   - **Repository name**: `agentvcs`
   - **Workflow name**: `release.yml`
   - **Environment name**: `pypi`
3. In the GitHub repo: **Settings → Environments → New environment** named
   `pypi` (the workflow references it; add reviewers there if you want a manual
   approval gate before every publish).

That's it — no secrets to paste. The `pypi` name in the workflow's
`environment:` and the trusted-publisher config must match.

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

## Alternative: API token instead of trusted publishing

If you'd rather not configure OIDC, create a PyPI API token, add it as the repo
secret `PYPI_API_TOKEN`, and replace the publish step's action invocation with:

```yaml
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          password: ${{ secrets.PYPI_API_TOKEN }}
```

(Trusted publishing is preferred — nothing to rotate or leak.)

## Test it first (optional)

Point a run at TestPyPI by adding `with: { repository-url: https://test.pypi.org/legacy/ }`
to the publish step and configuring a matching trusted publisher on test.pypi.org.
