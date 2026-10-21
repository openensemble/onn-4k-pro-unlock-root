# Project website

The static landing page lives in `site/`. It identifies the supported hardware
as the original **2024 onn. 4K Pro (jarvis / SNA)**. The 2023 non-Pro box and new
2026 Pro are unsupported. Keep its firmware table and claims aligned with
[the tested profile](../firmware/tested-profile.json) and [recorded results](RESULTS.md).

The page uses no framework, external fonts, analytics, or runtime dependencies.
`script.js` only adds a copy button; the content and FAQ work without JavaScript.
The existing Walmart identification photo is copied into `site/assets/` so the
published artifact is self-contained. See [image provenance](../THIRD_PARTY.md#device-identification-photo).

## Local preview

From the repository root:

```sh
python3 -m http.server 5213 --bind 127.0.0.1 --directory site
```

Open `http://127.0.0.1:5213/`. Stop the server when finished. Asset URLs are
relative so the site also works at GitHub Pages' repository subpath.

## Publish

Production URL: [onn. 4K Pro unlock & root](https://openensemble.github.io/onn-4k-pro-unlock-root/).
GitHub Pages uses the GitHub Actions publishing source with HTTPS enforced.

1. In the repository's **Settings → Pages**, choose **GitHub Actions** as the source.
2. Commit and push the reviewed website changes when authorized.
3. The **Deploy project website** workflow uploads only `site/` and deploys it
   to Pages. It also supports manual runs from the Actions tab.
4. After successful deployment, verify the public URL and add it to the
   repository's About website field and README.

If the public URL changes, update the canonical URL, Open Graph and Twitter
image URLs, JSON-LD, and sitemap together. Refresh the social preview image
when the model label or headline changes. Regenerate `MANIFEST.json` with
`python3 tools/make-manifest.py` after reviewed source changes.
