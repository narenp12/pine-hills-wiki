# Pine Hills Fantasy Football League Wiki

Wikipedia-inspired history of our Pine Hills fantasy football league (est. 2016).

Built with [Quartz 5](https://quartz.jzhao.xyz/) — a static-site generator for Markdown-based wikis, deployed to GitHub Pages.

## Structure

- `content/` — all wiki pages (Markdown). This is the source of truth.
- `quartz.config.yaml` — site configuration (theme, plugins, navigation).
- `quartz/` — the Quartz engine (don't edit directly).

## Local dev

```bash
npm install
npx quartz build --serve   # preview at http://localhost:8080
```

## Deploy

Push to GitHub and enable GitHub Pages on the `main` branch with the "GitHub Actions" source.
The included `.github/workflows/` workflow builds and deploys automatically.
