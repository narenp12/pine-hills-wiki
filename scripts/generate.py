"""
Generate Wikipedia-style Markdown wiki pages for the Pine Hills Fantasy
Football League from raw/ JSON (produced by extract.py) plus a hand-maintained
raw/bible.yaml of human-only facts.

Design principle — NEVER FABRICATE:
  * Facts derivable from captured Yahoo data (standings + draft) are computed.
  * Facts that are NOT in the data (owners, champions, playoff results, lore)
    come ONLY from raw/bible.yaml. If absent there, the page shows "_TBD_".
  * The regular-season #1 is NOT assumed to be the champion (this is a playoff
    league). Champion is a bible-only field.

Builds / rewrites:
  src/content/docs/seasons/<year>-season.md     (standings, playoffs stub, awards)
  src/content/docs/teams/<slug>.md              (franchise page + season log)
  src/content/docs/records/index.md             (all-time + single-season leaders)
  src/content/docs/teams/index.md               (franchise table)
  src/content/docs/seasons/index.md             (champions-by-year table)
  src/content/docs/index.md                     (root champions table)
  src/content/docs/champions.md                 (NBA-style "List of champions")
  src/content/docs/playoffs.md                  (NBA-style "Playoffs / Finals")

Run:  python scripts/generate.py
"""

import json
import os
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # CI may run without PyYAML installed
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
# Allow callers (e.g. the Zensical pipeline) to redirect generated Markdown to a
# different content directory without editing this file. Defaults to the
# Starlight content tree so existing `npm run build` is unchanged. Resolved to
# an absolute path so downstream relative_to() calls are stable.
_content_env = os.environ.get("WIKI_CONTENT_DIR")
CONTENT = Path(_content_env).resolve() if _content_env else ROOT / "src" / "content" / "docs"
BIBLE_PATH = RAW / "bible.yaml"

TBD = "_TBD_"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s or "team"


def load_raw():
    seasons = {}
    for f in sorted(RAW.glob("*.json")):
        if f.name == "bible.yaml":
            continue
        try:
            d = json.loads(f.read_text())
            seasons[int(d["season"])] = d
        except Exception as e:  # noqa: BLE001
            print(f"  ! skipping {f.name}: {e}")
    return seasons


def load_bible():
    if not BIBLE_PATH.exists():
        return {}
    if yaml is None:
        print(
            "  ! PyYAML not installed — skipping league bible "
            "(owners/champions will be _TBD_). Install pyyaml for full data.",
            file=sys.stderr,
        )
        return {}
    return yaml.safe_load(BIBLE_PATH.read_text()) or {}


def wikilink(title: str, label=None) -> str:
    return f"[[{title}]]" if label is None else f"[[{title}|{label}]]"


def standings_teams(d):
    st = d.get("standings", {}) or {}
    st = st.get("standings", st) if isinstance(st, dict) else st
    tl = st.get("teams", []) if isinstance(st, dict) else []
    return tl


# --------------------------------------------------------------------------- #
# aggregate: cross-year franchise stats (data-derivable only)
# --------------------------------------------------------------------------- #
def build_aggregates(seasons):
    """Return {canonical_name: stats}. Stats are purely data-derived."""
    # alias map: every known name -> canonical
    bible = load_bible()
    aliases = bible.get("aliases", {}) or {}
    name2canon = {}
    for canon, names in (aliases or {}).items():
        name2canon[canon] = canon
        for n in names:
            name2canon[n] = canon

    franchises = {}  # canon -> dict

    for year in sorted(seasons):
        d = seasons[year]
        for t in standings_teams(d):
            name = t.get("name", "Unknown")
            canon = name2canon.get(name, name)
            f = franchises.setdefault(
                canon,
                {
                    "names": set(),
                    "years": [],
                    "wins": 0,
                    "losses": 0,
                    "pf": 0.0,
                    "pa": 0.0,
                    "playoff_appears": 0,
                    "seasons_count": 0,
                    "best_pf_season": (0.0, year),
                    "worst_pf_season": (1e9, year),
                    "best_wpct_season": (0.0, year, 0, 0),
                    "finishes": [],  # (rank, year)
                },
            )
            f["names"].add(name)
            f["years"].append(year)
            f["seasons_count"] += 1
            w = int(t.get("wins", 0))
            l = int(t.get("losses", 0))
            pf = float(t.get("points_for", 0) or 0)
            pa = float(t.get("points_against", 0) or 0)
            f["wins"] += w
            f["losses"] += l
            f["pf"] += pf
            f["pa"] += pa
            rank = int(t.get("rank", 99))
            f["finishes"].append((rank, year))
            # playoff seed = top 4 (Yahoo rank 1..4)
            if rank <= 4:
                f["playoff_appears"] += 1
            # best/worst single-season PF
            if pf > f["best_pf_season"][0]:
                f["best_pf_season"] = (pf, year)
            if 0 < pf < f["worst_pf_season"][0]:
                f["worst_pf_season"] = (pf, year)
            gp = w + l
            pct = (w / gp) if gp else 0.0
            if pct > f["best_wpct_season"][0]:
                f["best_wpct_season"] = (pct, year, w, l)

    # finalize
    out = {}
    for canon, f in franchises.items():
        gp = f["wins"] + f["losses"]
        out[canon] = {
            "names": sorted(f["names"]),
            "years": sorted(f["years"]),
            "seasons_count": f["seasons_count"],
            "wins": f["wins"],
            "losses": f["losses"],
            "gp": gp,
            "wpct": (f["wins"] / gp) if gp else 0.0,
            "pf": round(f["pf"], 2),
            "pa": round(f["pa"], 2),
            "playoff_appears": f["playoff_appears"],
            "best_pf_season": f["best_pf_season"],
            "worst_pf_season": f["worst_pf_season"],
            "best_wpct_season": f["best_wpct_season"],
            "finishes": sorted(f["finishes"]),
        }
    return out


# --------------------------------------------------------------------------- #
# bible accessors
# --------------------------------------------------------------------------- #
def get_owners(bible):
    return bible.get("owners", {}) or {}


def get_champions(bible):
    return bible.get("champions", {}) or {}


def champ_year(bible, year):
    """Return the champion dict for a year, tolerant of str/int keys.
    bibles use integer years; be defensive about string keys too."""
    champs = get_champions(bible)
    return champs.get(int(year), champs.get(str(year), {})) or {}


def champ_fields(bible, year):
    """Return (champion, runner_up, top_seed, toilet_winner) for a year,
    defaulting each missing field to TBD."""
    c = champ_year(bible, year)
    return (
        c.get("champion") or TBD,
        c.get("runner_up") or TBD,
        c.get("top_seed") or TBD,
        c.get("toilet_winner") or TBD,
    )


# --------------------------------------------------------------------------- #
# page generators
# --------------------------------------------------------------------------- #
def gen_season(year, d, bible, aggregates):
    teams = standings_teams(d)
    owners = get_owners(bible)
    champ, runner, top_seed, toilet = champ_fields(bible, year)

    rows = []
    for i, t in enumerate(sorted(teams, key=lambda x: int(x.get("rank", 99))), 1):
        rank = int(t.get("rank", i))
        name = t.get("name", "?")
        owner = owners.get(name, "") or TBD
        w = t.get("wins", 0)
        l = t.get("losses", 0)
        pf = t.get("points_for", "?")
        pa = t.get("points_against", "?")
        seed = i if i <= 4 else "—"
        rows.append(
            f"| {rank} | {name} | {owner} | {w}–{l} | {pf} | {pa} | {seed} |"
        )

    md = f"""---
title: "{year} Season"
description: "Pine Hills Fantasy Football League — {year} season."
season: {year}
year: {year}
---

# 🏈 {year} Season

**Champion:** {champ}
**Runner-Up:** {runner}
**Regular Season Top Seed:** {top_seed}
**Toilet Bowl Winner:** {toilet}

## Final Standings

> Auto-generated from Yahoo standings. Owners and playoff results are filled from the league bible (`raw/bible.yaml`); `_TBD_` means not yet recorded.

| Rank | Team | Owner | W–L | PF | PA | Playoff Seed |
|------|------|-------|-----|----|----|--------------|
{chr(10).join(rows)}

## Playoff Bracket

> Playoff results are recorded in the league bible. Add `champions: {{ {year}: {{ champion: ..., runner_up: ... }} }}` to `raw/bible.yaml` to populate this section.

```mermaid
flowchart LR
    S1[Seed 1] --> W1
    S4[Seed 4] --> W1
    S2[Seed 2] --> W2
    S3[Seed 3] --> W2
    W1 --> Champ[🏆 Champion]
    W2 --> Champ
```

## Team Rosters

| Team | Post-Draft Roster | End-of-Season Roster |
|------|-------------------|----------------------|

## Awards

- 🏆 **League Champion:** {champ}
- 💥 **Highest Single-Week Score:** {TBD}
- 📉 **Lowest Single-Week Score:** {TBD}
- 🔥 **Biggest Bust:** {TBD}
- 🎯 **Best Draft Pick:** {TBD}
- 🍗 **"Poultry Controversy" Nominee:** {TBD}

## The Story of the Year

_TBD — add the defining moments._

## Related

- {wikilink('Seasons')} · {wikilink(f'{year} Draft')} · {wikilink('Teams')} · {wikilink('Records')} · {wikilink('Lore')} · {wikilink('Playoffs')}
"""
    return md


def gen_team_page(name, years_data, bible, aggregates):
    """years_data: list of (year, w, l, rank, playoff_seed_bool, owner)."""
    owners = get_owners(bible)
    notes = (bible.get("franchise_notes", {}) or {}).get(name, {})
    joined = notes.get("joined", TBD) if isinstance(notes, dict) else TBD
    status = notes.get("status", "Active") if isinstance(notes, dict) else "Active"
    owner = owners.get(name, "") or TBD

    agg = aggregates.get(name)
    if agg:
        titles = sum(1 for (r, y) in agg["finishes"] if r == 1)  # regular-season #1 (not champion)
        runner_ups = sum(1 for (r, y) in agg["finishes"] if r == 2)
        pf_str = f"{agg['pf']:.2f}"
        pa_str = f"{agg['pa']:.2f}"
        wpct = f"{agg['wpct']*100:.1f}%"
    else:
        titles = runner_ups = 0
        pf_str = pa_str = wpct = TBD

    rows = []
    for (year, w, l, rank, po, owner_o) in sorted(years_data, key=lambda x: x[0]):
        pd = wikilink(f"{year} {slug(name)} Post-Draft", "Post-Draft")
        eo = wikilink(f"{year} {slug(name)} End-of-Season", "End-of-Season")
        rows.append(
            f"| {year} | {w}–{l} | {rank} | {'Yes' if po else 'No'} | {pd} | {eo} | {TBD} |"
        )

    md = f"""---
title: "{name}"
description: "Franchise history for {name} in the Pine Hills Fantasy Football League."
---

# 🏈 {name}

**Owner:** {owner}
**Joined:** {joined}
**Status:** {status}

## Franchise Summary

- **Championships:** {TBD} _(playoff titles — record in `raw/bible.yaml`)_
- **Regular-Season 1-Seeds:** {titles}
- **Runner-Up Finishes (regular season):** {runner_ups}
- **Playoff Appearances:** {agg['playoff_appears'] if agg else TBD} / {agg['seasons_count'] if agg else TBD} seasons
- **All-Time Record:** {agg['wins'] if agg else TBD}–{agg['losses'] if agg else TBD} ({wpct})
- **All-Time Points For / Against:** {pf_str} / {pa_str}

## Season Log

| Year | W–L | Finish | Playoffs? | Post-Draft Roster | End-of-Season Roster | Note |
|------|-----|--------|-----------|-------------------|----------------------|------|
{chr(10).join(rows)}

## Rivalries

| Opponent | H2H Record | Notable Meeting |
|----------|-----------|-----------------|
| {TBD} | {TBD}–{TBD} | {TBD} |

## Signature Moments

_TBD._

## Related

- {wikilink('Teams')} · {wikilink('Seasons')} · {wikilink('Records')} · {wikilink('Lore')}
"""
    return md


def gen_records_index(seasons, aggregates, bible):
    champs = get_champions(bible)
    # all-time championship tally (from bible only)
    title_holders = {}
    for yr, c in champs.items():
        if isinstance(c, dict) and c.get("champion"):
            title_holders.setdefault(c["champion"], []).append(yr)

    champ_rows = []
    if title_holders:
        for team, yrs in sorted(title_holders.items(), key=lambda x: -len(x[1])):
            champ_rows.append(
                f"| {team} | {len(yrs)} | {', '.join(str(y) for y in sorted(yrs))} |"
            )
    else:
        champ_rows.append(f"| {TBD} | 0 | — |")

    # single-season PF leaders (data-derived) — build the full list first
    pf_sorted = sorted(aggregates.items(), key=lambda x: -x[1]["best_pf_season"][0])
    pf_all = []
    for canon, a in pf_sorted:
        pf, yr = a["best_pf_season"]
        pf_all.append(f"| Most Points For (season) | {canon} | {pf:.2f} | {yr} |")
    # pad to a stable length so downstream indexing into pf_all[0] is safe
    while len(pf_all) < 6:
        pf_all.append(f"| _TBD_ | _TBD_ | _TBD_ | _TBD_ |")
    pf_rows = pf_all

    # career leaders
    by_wins = sorted(aggregates.items(), key=lambda x: -x[1]["wins"])[:1]
    by_po = sorted(aggregates.items(), key=lambda x: -x[1]["playoff_appears"])[:1]
    by_streak = sorted(aggregates.items(), key=lambda x: -x[1]["best_wpct_season"][0])[:1]

    md = f"""---
title: Records
description: All-time records, single-season feats, and dubious achievements of the Pine Hills Fantasy Football League.
---

# 📊 Records

The ledger of greatness and shame. Standings-driven records are computed automatically from captured Yahoo data; playoff-era records (championships, awards) are recorded in the league bible (`raw/bible.yaml`).

## All-Time Championships

| Owner / Team | Titles | Years |
|--------------|--------|-------|
{chr(10).join(champ_rows)}

## Single-Season Records

| Record | Holder | Value | Year |
|--------|--------|-------|------|
{pf_rows[0]}
| Fewest Points For (season) | {TBD} | {TBD} | {TBD} |
| Highest Single-Week Score | {TBD} | {TBD} | {TBD} |
| Lowest Single-Week Score | {TBD} | {TBD} | {TBD} |
| Best Regular-Season Record | {by_streak[0][0] if by_streak else TBD} | {f"{by_streak[0][1]['best_wpct_season'][0]*100:.1f}%" if by_streak else TBD} | {by_streak[0][1]['best_wpct_season'][1] if by_streak else TBD} |
| Worst Regular-Season Record | {TBD} | {TBD} | {TBD} |

## Career Records

| Record | Holder | Value |
|--------|--------|-------|
| Most Career Wins | {by_wins[0][0] if by_wins else TBD} | {by_wins[0][1]['wins'] if by_wins else TBD} |
| Most Playoff Appearances | {by_po[0][0] if by_po else TBD} | {by_po[0][1]['playoff_appears'] if by_po else TBD} |
| Longest Win Streak | {TBD} | {TBD} |

## 🍗 The "Poultry Controversy" Board

A hall of fame for the league's most infamous moments — bad beats, vetoed trades, and questionable lineup decisions.

| Year | Incident | Accused |
|------|----------|---------|
| {TBD} | {TBD} | {TBD} |

## Related

- {wikilink('Seasons')} · {wikilink('Teams')} · {wikilink('Draft History')} · {wikilink('Lore')} · {wikilink('Champions')}
"""
    return md


def gen_teams_index(aggregates, bible):
    owners = get_owners(bible)
    champs = get_champions(bible)
    title_holders = {}
    for yr, c in champs.items():
        if isinstance(c, dict) and c.get("champion"):
            title_holders.setdefault(c["champion"], 0)
            title_holders[c["champion"]] += 1

    rows = []
    for canon, a in sorted(aggregates.items(), key=lambda x: x[0].lower()):
        # pick a representative name (prefer the one that appears latest)
        rep = a["names"][-1]
        owner = owners.get(rep, "") or TBD
        yr_range = f"{a['years'][0]}–"
        titles = title_holders.get(rep, 0)
        link = wikilink(rep)
        rows.append(f"| {rep} | {owner} | {yr_range} | {titles} | {link} |")

    md = f"""---
title: Teams
description: Franchise histories and owners of the Pine Hills Fantasy Football League.
---

# 👥 Teams

Every franchise in Pine Hills history. Each team page tracks the owner, season-by-season results, championships, and head-to-head records. Standings-derived stats are computed automatically; owners and titles come from the league bible.

## Active & Historical Franchises

| Team | Owner | Seasons | Titles | Page |
|------|-------|---------|--------|------|
{chr(10).join(rows)}

## Team Pages Should Include

- **Owner & tenure** — who runs it, what years.
- **Championships** — years won, runner-up finishes.
- **Season log** — W–L and finish per year.
- **Rivalries** — head-to-head record vs. nemesis teams.
- **Signature moments** — the trade that defined them, the meltdown, the heater.

> Building a new team page? Start from {wikilink('Team Template')}.
"""
    return md


def gen_seasons_index(champs_years, bible):
    rows = []
    for yr in sorted(champs_years, reverse=True):
        champ = champ_year(bible, yr).get("champion") or TBD
        rows.append(f"| {yr} | {champ} | {TBD} | {wikilink(f'{yr} Season')} |")
    # include 2016/2017 placeholders if referenced
    md = f"""---
title: Seasons
description: Year-by-year history of the Pine Hills Fantasy Football League.
---

# 📅 Seasons

Every completed season of the Pine Hills Fantasy Football League. Click a year for the full breakdown — standings, playoff bracket, draft, awards, and the story of the year.

## Season Index

| Year | Champion | Notable Story | Page |
|------|----------|---------------|------|
{chr(10).join(rows)}

## How Seasons Are Documented

Each season page follows a standard template:

1. **Final Standings** — regular season record, points for/against, playoff seed.
2. **Playoff Results** — bracket, champion, consolation winner.
3. **Draft Recap** — link to that year's {wikilink('Draft History')} page.
4. **Awards** — champion, top scorer, biggest bust, "Poultry Controversy" nominee.
5. **Lore** — the defining moments worth remembering.

> Want to fill one in? Copy the template from {wikilink('Season Template')} and edit away.
"""
    return md


def gen_root_index(champs_years, bible):
    rows = []
    for yr in sorted(champs_years, reverse=True):
        champ, ru, ts, _ = champ_fields(bible, yr)
        rows.append(f"| {yr} | {champ} | {ru} | {ts} |")
    return rows


def gen_champions_page(champs_years, bible):
    rows = []
    for yr in sorted(champs_years, reverse=True):
        champ, ru, ts, _ = champ_fields(bible, yr)
        rows.append(f"| {yr} | {champ} | {ru} | {ts} | {wikilink(f'{yr} Season')} |")

    md = f"""---
title: Champions
description: List of Pine Hills Fantasy Football League champions by season.
---

# 🏆 Champions

The complete list of Pine Hills Fantasy Football League champions, year by year. The champion is the playoff winner (not the regular-season top seed). Records are maintained in the league bible (`raw/bible.yaml`).

| Year | Champion | Runner-Up | Regular Season Top Seed | Season |
|------|----------|-----------|-------------------------|--------|
{chr(10).join(rows)}

## Most Titles

| Team | Titles | Years |
|------|--------|-------|
"""
    # tally
    tally = {}
    for yr in champs_years:
        c = champ_year(bible, yr)
        if c.get("champion"):
            tally.setdefault(c["champion"], []).append(yr)
    if tally:
        for team, yrs in sorted(tally.items(), key=lambda x: (-len(x[1]), x[0])):
            md += f"| {team} | {len(yrs)} | {', '.join(str(y) for y in sorted(yrs))} |\n"
    else:
        md += f"| {TBD} | 0 | — |\n"

    md += f"""
## Related

- {wikilink('Seasons')} · {wikilink('Playoffs')} · {wikilink('Records')} · {wikilink('Teams')}
"""
    return md


def gen_draft_index(all_years, bible):
    rows = []
    for yr in sorted(all_years, reverse=True):
        rows.append(f"| {yr} | {wikilink(f'{yr} Draft')} | {TBD} |")
    md = f"""---
title: Draft History
description: Every draft in Pine Hills history, pick by pick.
---

# 🎯 Draft History

The annual rite. Every pick, every reach, every steal. Each draft page lists the full board plus notable reaches and values.

## Drafts by Year

| Year | Draft Page | Notable Pick |
|------|-----------|--------------|
{chr(10).join(rows)}

## What a Draft Page Includes

- **Full pick-by-pick board** — round, overall pick, team, player, position.
- **Reach / Steal flags** — picks that aged well or badly.
- **Link to post-draft rosters** — see each team's {wikilink('Roster Template')} post-draft roster.
- **Notable storylines** — the auto-drafter, the guy who fell, the panic pick.

> Documenting a draft? Use the {wikilink('Draft Template')}.
"""
    return md


def gen_playoffs_page(champs_years, bible):
    md = f"""---
title: Playoffs
description: Pine Hills Fantasy Football League playoff format, champions, and Finals history.
---

# 🏆 Playoffs

The Pine Hills Fantasy Football League postseason. The top four teams by regular-season record qualify for the playoffs; the winner is crowned league champion.

## Format

- **Qualifiers:** top 4 regular-season teams (seeds 1–4).
- **Champion:** determined by the playoff bracket, not regular-season standing.
- **Consolation (Toilet Bowl):** contested by non-qualifiers.

## Champions by Year

| Year | Champion | Runner-Up | Season |
|------|----------|-----------|--------|
"""
    for yr in sorted(champs_years, reverse=True):
        champ, ru, _, _ = champ_fields(bible, yr)
        md += f"| {yr} | {champ} | {ru} | {wikilink(f'{yr} Season')} |\n"

    md += f"""
> Playoff brackets and game scores are recorded in the league bible (`raw/bible.yaml`). Add per-year `champion` / `runner_up` to populate results.

## Related

- {wikilink('Champions')} · {wikilink('Seasons')} · {wikilink('Records')} · {wikilink('Lore')}
"""
    return md


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main():
    seasons = load_raw()
    bible = load_bible()
    if not seasons:
        print("No raw JSON found in raw/. Run scripts/extract.py first.")
        return

    (CONTENT / "seasons").mkdir(parents=True, exist_ok=True)
    (CONTENT / "teams").mkdir(parents=True, exist_ok=True)
    (CONTENT / "draft").mkdir(parents=True, exist_ok=True)
    (CONTENT / "records").mkdir(parents=True, exist_ok=True)

    aggregates = build_aggregates(seasons)

    # per-team season data for team pages
    team_years = {}  # canon -> list of (year, w, l, rank, po, owner)
    owners = get_owners(bible)

    for year in sorted(seasons):
        d = seasons[year]
        # season page
        sp = CONTENT / "seasons" / f"{year}-season.md"
        sp.write_text(gen_season(year, d, bible, aggregates))
        print(f"  wrote {sp.relative_to(ROOT)}")

        # team pages data
        for t in standings_teams(d):
            name = t.get("name", "Unknown")
            w = int(t.get("wins", 0))
            l = int(t.get("losses", 0))
            rank = int(t.get("rank", 99))
            po = rank <= 4
            owner = owners.get(name, "") or TBD
            team_years.setdefault(name, []).append((year, w, l, rank, po, owner))

        # draft page (already fully captured — regenerate for consistency)
        draft = d.get("draft", {}) or {}
        picks = draft.get("draft_results", draft.get("results", []))
        if isinstance(picks, dict):
            picks = picks.get("draft_results", [])
        dlines = ["| Overall | Round | Team | Player | Position |",
                  "|---------|-------|------|--------|----------|"]
        if isinstance(picks, list):
            for p in picks:
                if isinstance(p, dict):
                    dlines.append(
                        f"| {p.get('pick','?')} | {p.get('round','?')} | {p.get('team','?')} | {p.get('player','?')} | {p.get('position','?')} |"
                    )
        dp = CONTENT / "draft" / f"{year}-draft.md"
        dp.write_text(
            f"---\ntitle: \"{year} Draft\"\ndescription: \"Pine Hills FF {year} draft board.\"\n---\n\n"
            f"# 🎯 {year} Draft\n\n" + "\n".join(dlines) +
            f"\n\n## Related\n\n- {wikilink('Draft History')} · {wikilink(f'{year} Season')}\n"
        )
        print(f"  wrote {dp.relative_to(ROOT)}")

    # team pages
    for name, ydata in team_years.items():
        tp = CONTENT / "teams" / f"{slug(name)}.md"
        tp.write_text(gen_team_page(name, ydata, bible, aggregates))
        print(f"  wrote {tp.relative_to(ROOT)}")

    all_years = sorted(seasons.keys())

    # records index
    rp = CONTENT / "records" / "index.md"
    rp.write_text(gen_records_index(seasons, aggregates, bible))
    print(f"  wrote {rp.relative_to(ROOT)}")

    # teams index
    tip = CONTENT / "teams" / "index.md"
    tip.write_text(gen_teams_index(aggregates, bible))
    print(f"  wrote {tip.relative_to(ROOT)}")

    # seasons index
    sip = CONTENT / "seasons" / "index.md"
    sip.write_text(gen_seasons_index(all_years, bible))
    print(f"  wrote {sip.relative_to(ROOT)}")

    # draft index (scoped to real years — avoids broken links to 2016/2017)
    dip = CONTENT / "draft" / "index.md"
    dip.write_text(gen_draft_index(all_years, bible))
    print(f"  wrote {dip.relative_to(ROOT)}")

    # champions + playoffs (NBA-style)
    cp = CONTENT / "champions.md"
    cp.write_text(gen_champions_page(all_years, bible))
    print(f"  wrote {cp.relative_to(ROOT)}")
    pp = CONTENT / "playoffs.md"
    pp.write_text(gen_playoffs_page(all_years, bible))
    print(f"  wrote {pp.relative_to(ROOT)}")

    # root index — rewrite only the champions table, bounded by markers
    root = CONTENT / "index.md"
    if root.exists():
        rows = gen_root_index(all_years, bible)
        lines = root.read_text().splitlines()
        out = []
        inside = False
        replaced = False
        for line in lines:
            if "<!-- champions-table:start -->" in line:
                out.append(line)
                out.extend(rows)
                inside = True
                replaced = True
                continue
            if "<!-- champions-table:end -->" in line:
                out.append(line)
                inside = False
                continue
            if inside:
                continue  # skip old table body between markers
            out.append(line)
        if not replaced:
            # markers missing — fall back to appending before "## Explore"
            out = []
            for line in lines:
                if line.startswith("## 📚 Explore"):
                    out.extend(rows)
                    out.append("")
                out.append(line)
        root.write_text("\n".join(out) + "\n")
        print(f"  updated {root.relative_to(ROOT)} (champions table)")

    print("Done generating Markdown.")


if __name__ == "__main__":
    main()
