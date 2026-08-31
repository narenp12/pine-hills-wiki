# Contributing to Pine Hills Wiki

Thank you for considering a contribution! Please follow these guidelines to keep the wiki consistent, high‑quality, and free of generic filler.

## Code & Content Style
- **Anti‑slop**: Avoid placeholder text (`TODO`, `_TBD_`), generic variable names, and em/en dashes. Use plain ASCII hyphens (`-`).
- **Design tokens**: When adding CSS, use the existing `--spacing-*` and `--border-radius` variables instead of hard‑coded values.
- **Documentation**: Update `README.md` and any generated markdown to reflect real data. Keep the establishment year at **2018**.
- **Testing**: Add pytest cases under `tests/` for any new helper functions. Run `uv run pytest -q` before committing.

## Workflow
1. Fork the repository.
2. Create a feature branch (`git checkout -b my‑feature`).
3. Make your changes.
4. Run the generation pipeline:
   ```bash
   uv run python scripts/generate.py
   uv run python zensical/transform.py
   ```
5. Verify the site builds locally (`mkdocs serve` if you use MkDocs) or by opening the generated HTML files.
6. Submit a pull request.

## License
All content is released under the MIT License. See `LICENSE` for details.
