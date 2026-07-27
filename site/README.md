# Landing page

Dependency-free static HTML (dark / terminal aesthetic) deployed to GitHub Pages by
[`.github/workflows/pages.yml`](../.github/workflows/pages.yml). The whole `site/`
directory is published, so anything added under it ships automatically.

Default URL once Pages is enabled (Settings → Pages → Source: **GitHub Actions**):
**https://evolvingagentslabs.github.io/agentvcs/**

## Pages

- `index.html` — the landing page.
- `demos/index.html` — the demos hub (linked from the landing nav and hero).
- `demos/business-cases.html` — the five diagnostics as plain-English business stories.
- `demos/evolution-diagnostics.html` — the technical companion (the math, asserted).

The demo pages mirror the runnable examples under [`../examples/`](../examples/); the
reproduction guide is [`../docs/DEMOS.md`](../docs/DEMOS.md).

## Before it captures emails

The waitlist form posts to a placeholder. Edit the `<form action="...">` in
`index.html` and replace `REPLACE_ME` with your form id from
[Formspree](https://formspree.io), [Buttondown](https://buttondown.email), or
[Tally](https://tally.so). Until then the form submits to a no-op endpoint.

## Custom domain

Add a `site/CNAME` file containing your domain (e.g. `agentvcs.dev`) and point a
DNS `CNAME` at `evolvingagentslabs.github.io`. Update the `<link rel="canonical">`
and `og:url` and the `/agentvcs/` link prefixes in `index.html` to the root path.

## llms.txt

`llms.txt` is the single source of truth at the repo root; the Pages workflow
copies it into the site so it’s served at `/agentvcs/llms.txt`.

## Preview locally

```bash
cp ../llms.txt llms.txt && python3 -m http.server -d . 8000
# open http://localhost:8000
```
