# Pine Hills Fantasy Football League Wiki

A static, Markdown‑driven encyclopedia of the Pine Hills Fantasy Football League (est. 2018). The site is generated with **Zensical**, a lightweight static‑site generator that builds clean, SEO‑friendly pages from raw Yahoo data (`raw/*.json`) and a hand‑maintained *league bible* (`raw/bible.yaml`).

## Project layout

- `raw/` – source data: JSON season files from Yahoo and `bible.yaml` for human‑only facts (owners, champions, aliases, lore).  
- `scripts/` – Python generation pipeline (`generate.py`) that:
  - loads raw season JSON and the bible,
  - computes aggregates (win‑pct, points‑for/against, playoff stats),
  - emits Markdown pages under `zensical/.stage/`.
- `zensical/` – Zensical static‑site engine:
  - `transform.py` turns the staged Markdown into the final website (`zensical/docs/`).
  - `stylesheets/` holds the CSS theme (see `stylesheets/zensical.css`).
  - `docs/` is the published site content.
- `tests/` – minimal pytest suite covering core helpers (`build_aggregates`, `champ_fields`, `gen_season`, `gen_root_index`).

## Development workflow

```bash
# Install dependencies (uv is used for deterministic envs)
uv sync               # install python deps (pyyaml, etc.)
# Run the generator – writes staged Markdown
uv run python scripts/generate.py
# Transform staged files into the final site
uv run python zensical/transform.py
# Preview the generated site locally (simple HTTP server)
python -m http.server --directory zensical/docs 8000
```

## Tests

```bash
uv run pytest -q
```

All tests pass, ensuring the generator produces valid Markdown and that the root index table updates correctly.

## Design & style

- **Anti‑slop policy** – no generic variable names, no magic numbers (all are named constants), and all dashes are plain ASCII hyphens (`-`).
- **Typography** – serif body for editorial copy, system‑sans headings for clarity.
- **Colour scheme** – pine‑green accent, dark/ light dual‑scheme, champion gold highlight.
- **CSS tokens** – spacing and border‑radius variables are defined at the top of `zensical.css` for consistency.

## Adding new data

1. **Update the league bible** (`raw/bible.yaml`) with any new owners, champion results, or franchise aliases.
2. **Add new season JSON** (`raw/<year>.json`) – the generator will automatically ingest it.
3. Re‑run the generation pipeline to refresh the site.

## Deploy

The site is hosted on GitHub Pages. After committing changes, push to `main`; the CI workflow (if enabled) builds the site and updates the `gh‑pages` branch automatically.

---

*Built with love for the Pine Hills community – see the source for details and feel free to contribute!*