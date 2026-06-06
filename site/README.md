# Landing page

A single, dependency-free `index.html` (dark / terminal aesthetic) deployed to
GitHub Pages by [`.github/workflows/pages.yml`](../.github/workflows/pages.yml).

Default URL once Pages is enabled (Settings → Pages → Source: **GitHub Actions**):
**https://evolvingagentslabs.github.io/agentvcs/**

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
