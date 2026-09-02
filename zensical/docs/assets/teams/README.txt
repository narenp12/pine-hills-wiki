Drop team images here.

Reference one from raw/bible.yaml:

    team_images:
      "Roger That": roger-that.png

The file name is enough - generate.py resolves it to assets/teams/<file>.
A docs-relative path or an absolute https:// URL works too.

Any web format Zensical copies verbatim is fine (png, jpg, webp, svg).
Square-ish crops read best: the image is capped at 12rem tall in the team
infobox and rendered as a 1.6rem square thumbnail in the Teams and Owners
tables.
