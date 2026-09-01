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

Builds / rewrites (into WIKI_CONTENT_DIR, default zensical/.stage, which
zensical/transform.py turns into zensical/docs):
  seasons/<year>-season.md     (standings, playoffs stub, awards)
  teams/<slug>.md              (franchise page + season log)
  records/index.md             (all-time + single-season leaders)
  teams/index.md               (franchise table)
  seasons/index.md             (champions-by-year table)
  index.md                     (root champions table)
  champions.md                 (NBA-style "List of champions")
  playoffs.md                  (NBA-style "Playoffs / Finals")

Run:  python scripts/generate.py   (or with WIKI_CONTENT_DIR set)
"""

import json
import os
import re
import sys
from pathlib import Path

# Normalize dashes in generated Markdown. Em-dash (—) and en-dash (–) are banned
# by the site's anti-slop style guide (they read as AI tells and break copy
# lint). Collapse both to a plain ASCII hyphen so generated content stays clean
# regardless of which template string introduces them.
_DASHES = {"—": "-", "–": "-"}
_DASH_RE = re.compile("|".join(re.escape(k) for k in _DASHES))

# Magic numbers replaced with named constants
DEFAULT_RANK = 99
PLAYOFF_SEEDS = 4
# Week boundaries used throughout the generator
POST_DRAFT_WEEK = 1
END_SEASON_WEEK = 18
PLAYOFF_START_WEEK = 14
PLAYOFF_END_WEEK = 18
INITIAL_WORST_PF = 1e9
PF_LEADERBOARD_MIN_ROWS = 6


def dash_normalize(text: str) -> str:
    """Replace em/en-dashes with ASCII hyphen in generated Markdown."""
    return _DASH_RE.sub(lambda m: _DASHES[m.group(0)], text)

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
# Allow callers to redirect generated Markdown to a different content directory
# via WIKI_CONTENT_DIR. Defaults to the Zensical staging tree (consumed by
# zensical/transform.py -> zensical/docs). Resolved to an absolute path so
# downstream relative_to() calls are stable.
_content_env = os.environ.get("WIKI_CONTENT_DIR")
CONTENT = Path(_content_env).resolve() if _content_env else ROOT / "zensical" / ".stage"
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
        except json.JSONDecodeError as e:
            print(f"  ! skipping {f.name}: invalid JSON - {e}")
        except KeyError as e:
            print(f"  ! skipping {f.name}: missing key {e} in JSON")
        except OSError as e:
            print(f"  ! skipping {f.name}: unable to read file - {e}")
    return seasons


def load_bible():
    if not BIBLE_PATH.exists():
        return {}
    if yaml is None:
        print(
            "  ! PyYAML not installed — skipping league bible (owners/champions will be _TBD_). Install pyyaml for full data.",
            file=sys.stderr,
        )
        return {}
    try:
        return yaml.safe_load(BIBLE_PATH.read_text()) or {}
    except yaml.YAMLError as e:
        print(f"  ! Failed to parse bible.yaml: {e}", file=sys.stderr)
        return {}
    except OSError as e:
        print(f"  ! Could not read bible.yaml: {e}", file=sys.stderr)
        return {}


def wikilink(title: str, label=None) -> str:
    return f"[[{title}]]" if label is None else f"[[{title}|{label}]]"


def standings_teams(season_data: dict) -> list[dict]:
    """Extract the list of team standings from a season JSON."""
    standings = season_data.get("standings", {}) or {}
    standings = standings.get("standings", standings) if isinstance(standings, dict) else standings
    teams = standings.get("teams", []) if isinstance(standings, dict) else []
    return teams


# --------------------------------------------------------------------------- #
# aggregate: cross-year franchise stats (data-derivable only)
# --------------------------------------------------------------------------- #
def build_aggregates(seasons: dict) -> dict:
    """Return {canonical_name: stats}. Stats are purely data-derived."""
    # alias map: every known name -> canonical
    bible = load_bible()
    aliases = bible.get("aliases", {}) or {}
    name_to_canonical = {}
    for canon, names in (aliases or {}).items():
        name_to_canonical[canon] = canon
        for n in names:
            name_to_canonical[n] = canon

    franchises = {}  # canon -> raw accumulation dict

    for year in sorted(seasons):
        season_data = seasons[year]
        for team in standings_teams(season_data):
            team_name = team.get("name", "Unknown")
            canonical_name = name_to_canonical.get(team_name, team_name)
            franchise = franchises.setdefault(
                canonical_name,
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
                    "worst_pf_season": (INITIAL_WORST_PF, year),
                    "best_wpct_season": (0.0, year, 0, 0),
                    "finishes": [],  # (rank, year)
                },
            )
            franchise["names"].add(team_name)
            franchise["years"].append(year)
            franchise["seasons_count"] += 1
            wins = int(team.get("wins", 0))
            losses = int(team.get("losses", 0))
            points_for = float(team.get("points_for", 0) or 0)
            points_against = float(team.get("points_against", 0) or 0)
            franchise["wins"] += wins
            franchise["losses"] += losses
            franchise["pf"] += points_for
            franchise["pa"] += points_against
            rank = int(team.get("rank", DEFAULT_RANK))
            franchise["finishes"].append((rank, year))
            if rank <= PLAYOFF_SEEDS:
                franchise["playoff_appears"] += 1
            if points_for > franchise["best_pf_season"][0]:
                franchise["best_pf_season"] = (points_for, year)
            if 0 < points_for < franchise["worst_pf_season"][0]:
                franchise["worst_pf_season"] = (points_for, year)
            games_played = wins + losses
            win_pct = (wins / games_played) if games_played else 0.0
            if win_pct > franchise["best_wpct_season"][0]:
                franchise["best_wpct_season"] = (win_pct, year, wins, losses)

    # finalize into output dict
    out = {}
    for canonical_name, franchise in franchises.items():
        games_played = franchise["wins"] + franchise["losses"]
        out[canonical_name] = {
            "names": sorted(franchise["names"]),
            "years": sorted(franchise["years"]),
            "seasons_count": franchise["seasons_count"],
            "wins": franchise["wins"],
            "losses": franchise["losses"],
            "gp": games_played,
            "wpct": (franchise["wins"] / games_played) if games_played else 0.0,
            "pf": round(franchise["pf"], 2),
            "pa": round(franchise["pa"], 2),
            "playoff_appears": franchise["playoff_appears"],
            "best_pf_season": franchise["best_pf_season"],
            "worst_pf_season": franchise["worst_pf_season"],
            "best_wpct_season": franchise["best_wpct_season"],
            "finishes": sorted(franchise["finishes"]),
        }
    return out


# --------------------------------------------------------------------------- #
# bible accessors
# --------------------------------------------------------------------------- #
def get_owners(bible: dict) -> dict:
    return bible.get("owners", {}) or {}


def get_champions(bible: dict) -> dict:
    return bible.get("champions", {}) or {}


def champ_year(bible: dict, year: int) -> dict:
    """Return the champion dict for a year, tolerant of str/int keys."""
    champs = get_champions(bible)
    return champs.get(int(year), champs.get(str(year), {})) or {}


def champ_fields(bible: dict, year: int) -> tuple[str, str, str, str]:
    """Return (champion, runner_up, top_seed, toilet_winner) for a year."""
    champion_data = champ_year(bible, year)
    return (
        champion_data.get("champion") or TBD,
        champion_data.get("runner_up") or TBD,
        champion_data.get("top_seed") or TBD,
        champion_data.get("toilet_winner") or TBD,
    )


def _mermaid_label(text: str) -> str:
    """Quote a team name for use as a Mermaid node label."""
    return '"' + str(text).replace('"', "'") + '"'


def playoff_bracket(seeded: list[tuple[int, str]], champion: str) -> str:
    """Render the playoff bracket with the seeds that actually qualified.

    Falls back to a generic Seed 1-4 skeleton when the standings do not name a
    full bracket, so a season with incomplete data still shows the format.
    """
    by_seed = dict(seeded)
    if len(by_seed) < PLAYOFF_SEEDS:
        names = {n: f"Seed {n}" for n in range(1, PLAYOFF_SEEDS + 1)}
    else:
        names = {n: f"({n}) {by_seed[n]}" for n in range(1, PLAYOFF_SEEDS + 1)}

    champ_label = f"🏆 {champion}" if champion != TBD else "🏆 Champion"
    lines = [
        "```mermaid",
        "flowchart LR",
        f"    S1[{_mermaid_label(names[1])}] --> W1[Semifinal 1]",
        f"    S4[{_mermaid_label(names[4])}] --> W1",
        f"    S2[{_mermaid_label(names[2])}] --> W2[Semifinal 2]",
        f"    S3[{_mermaid_label(names[3])}] --> W2",
        f"    W1 --> Champ[{_mermaid_label(champ_label)}]",
        "    W2 --> Champ",
        "```",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# page generators
# --------------------------------------------------------------------------- #
def gen_season(year: int, season_data: dict, bible: dict, aggregates: dict) -> str:
    teams = standings_teams(season_data)
    owners = get_owners(bible)
    champion, runner_up, top_seed, toilet_bowl_winner = champ_fields(bible, year)

    rows = []
    seeded: list[tuple[int, str]] = []  # (seed, team name) for the bracket
    for position, team in enumerate(sorted(teams, key=lambda x: int(x.get("rank", DEFAULT_RANK))), 1):
        rank = int(team.get("rank", position))
        team_name = team.get("name", "?")
        owner = owners.get(team_name, "") or TBD
        wins = team.get("wins", 0)
        losses = team.get("losses", 0)
        points_for = team.get("points_for", "?")
        points_against = team.get("points_against", "?")
        if position <= PLAYOFF_SEEDS:
            seed = position
            seeded.append((position, team_name))
        else:
            seed = "—"
        rows.append(
            f"| {rank} | {team_name} | {owner} | {wins}–{losses} | {points_for} | {points_against} | {seed} |"
        )

    bracket = playoff_bracket(seeded, champion)

    # Flag the page as unfinished while the bible has no champion for the year.
    # `status` renders the badge configured in zensical.toml.
    status_line = "status: incomplete\n" if champion == TBD else ""

    md = f"""---
title: "{year} Season"
description: "Pine Hills Fantasy Football League — {year} season."
season: {year}
year: {year}
{status_line}---

# 🏈 {year} Season

- **Champion:** {champion}
- **Runner-Up:** {runner_up}
- **Regular Season Top Seed:** {top_seed}
- **Toilet Bowl Winner:** {toilet_bowl_winner}

## Final Standings

> Auto-generated from Yahoo standings. Owners and playoff results are filled from the league bible (`raw/bible.yaml`); _TBD_ means not yet recorded. **Finish** is the standing recorded in the source export and does not always follow W–L order.

| Finish | Team | Owner | W–L | PF | PA | Playoff Seed |
|--------|------|-------|-----|----|----|--------------|
{chr(10).join(rows)}

## Playoff Bracket

> Playoff results are recorded in the league bible. Add `champions: {{ {year}: {{ champion: ..., runner_up: ... }} }}` to `raw/bible.yaml` to populate this section.

{bracket}

## Team Rosters

| Team | Post-Draft Roster | End-of-Season Roster |
|------|-------------------|----------------------|

## Awards

- 🏆 **League Champion:** {champion}
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


def gen_team_page(name: str, years_data: list, bible: dict, aggregates: dict) -> str:
    """Generate a franchise page.
    years_data: list of (year, wins, losses, rank, made_playoffs, owner).
    """
    owners = get_owners(bible)
    franchise_notes = (bible.get("franchise_notes", {}) or {}).get(name, {})
    joined_year = franchise_notes.get("joined", TBD) if isinstance(franchise_notes, dict) else TBD
    status = franchise_notes.get("status", "Active") if isinstance(franchise_notes, dict) else "Active"
    owner = owners.get(name, "") or TBD

    franchise_stats = aggregates.get(name)
    if franchise_stats:
        regular_season_titles = sum(1 for (r, y) in franchise_stats["finishes"] if r == 1)
        runner_up_finishes = sum(1 for (r, y) in franchise_stats["finishes"] if r == 2)
        pf_str = f"{franchise_stats['pf']:.2f}"
        pa_str = f"{franchise_stats['pa']:.2f}"
        win_pct_str = f"{franchise_stats['wpct']*100:.1f}%"
    else:
        regular_season_titles = runner_up_finishes = 0
        pf_str = pa_str = win_pct_str = TBD

    rows = []
    for (year, wins, losses, rank, made_playoffs, _) in sorted(years_data, key=lambda x: x[0]):
        post_draft_link = wikilink(f"{year} {slug(name)} Post-Draft", "Post-Draft")
        end_of_season_link = wikilink(f"{year} {slug(name)} End-of-Season", "End-of-Season")
        rows.append(
            f"| {year} | {wins}–{losses} | {rank} | {'Yes' if made_playoffs else 'No'} | {post_draft_link} | {end_of_season_link} | {TBD} |"
        )

    md = f"""---
title: "{name}"
description: "Franchise history for {name} in the Pine Hills Fantasy Football League."
---

# 🏈 {name}

- **Owner:** {owner}
- **Joined:** {joined_year}
- **Status:** {status}

## Franchise Summary

- **Championships:** {TBD}
- **Regular-Season 1-Seeds:** {regular_season_titles}
- **Runner-Up Finishes (regular season):** {runner_up_finishes}
- **Playoff Appearances:** {franchise_stats['playoff_appears'] if franchise_stats else TBD} / {franchise_stats['seasons_count'] if franchise_stats else TBD} seasons
- **All-Time Record:** {franchise_stats['wins'] if franchise_stats else TBD}–{franchise_stats['losses'] if franchise_stats else TBD} ({win_pct_str})
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


def gen_records_index(seasons: dict, aggregates: dict, bible: dict) -> str:
    champs = get_champions(bible)
    # all-time championship tally (from bible only)
    championship_holders = {}
    for year, champ_data in champs.items():
        if isinstance(champ_data, dict) and champ_data.get("champion"):
            championship_holders.setdefault(champ_data["champion"], []).append(year)

    champ_rows = []
    if championship_holders:
        for team, years in sorted(championship_holders.items(), key=lambda x: -len(x[1])):
            champ_rows.append(
                f"| {team} | {len(years)} | {', '.join(str(y) for y in sorted(years))} |"
            )
    else:
        champ_rows.append(f"| {TBD} | 0 | — |")

    # single-season PF leaders (data-derived) — build the full list first
    pf_sorted = sorted(aggregates.items(), key=lambda x: -x[1]["best_pf_season"][0])
    pf_all = []
    for canonical_name, stats in pf_sorted:
        points_for, year = stats["best_pf_season"]
        pf_all.append(f"| Most Points For (season) | {canonical_name} | {points_for:.2f} | {year} |")
    # pad to a stable length so downstream indexing into pf_all[0] is safe
    while len(pf_all) < PF_LEADERBOARD_MIN_ROWS:
        pf_all.append(f"| _TBD_ | _TBD_ | _TBD_ | _TBD_ |")
    pf_rows = pf_all

    # career leaders
    most_wins = sorted(aggregates.items(), key=lambda x: -x[1]["wins"])[:1]
    most_playoffs = sorted(aggregates.items(), key=lambda x: -x[1]["playoff_appears"])[:1]
    best_record = sorted(aggregates.items(), key=lambda x: -x[1]["best_wpct_season"][0])[:1]

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
| Best Regular-Season Record | {best_record[0][0] if best_record else TBD} | {f"{best_record[0][1]['best_wpct_season'][0]*100:.1f}%" if best_record else TBD} | {best_record[0][1]['best_wpct_season'][1] if best_record else TBD} |
| Worst Regular-Season Record | {TBD} | {TBD} | {TBD} |

## Career Records

| Record | Holder | Value |
|--------|--------|-------|
| Most Career Wins | {most_wins[0][0] if most_wins else TBD} | {most_wins[0][1]['wins'] if most_wins else TBD} |
| Most Playoff Appearances | {most_playoffs[0][0] if most_playoffs else TBD} | {most_playoffs[0][1]['playoff_appears'] if most_playoffs else TBD} |
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


def gen_teams_index(aggregates: dict, bible: dict) -> str:
    owners = get_owners(bible)
    champs = get_champions(bible)
    championship_counts = {}
    for year, champ_data in champs.items():
        if isinstance(champ_data, dict) and champ_data.get("champion"):
            championship_counts[champ_data["champion"]] = championship_counts.get(champ_data["champion"], 0) + 1

    # Latest season in the data: a franchise still active in it reads "present"
    # rather than the open-ended "2018–" the table used to show.
    latest_year = max(
        (max(f["years"]) for f in aggregates.values() if f.get("years")), default=None
    )

    rows = []
    for canonical_name, franchise in sorted(aggregates.items(), key=lambda x: x[0].lower()):
        # pick a representative name (prefer the one that appears latest)
        representative_name = franchise["names"][-1]
        owner = owners.get(representative_name, "") or TBD
        first_year, last_year = min(franchise["years"]), max(franchise["years"])
        if last_year == latest_year:
            year_range = f"{first_year}–present"
        elif first_year == last_year:
            year_range = str(first_year)
        else:
            year_range = f"{first_year}–{last_year}"
        titles = championship_counts.get(representative_name, 0)
        # The team name is the link; a separate "Page" column repeated it and
        # forced both columns to wrap to three lines each on narrow screens.
        rows.append(
            f"| {wikilink(representative_name)} | {owner} | {year_range} | {titles} |"
        )

    md = f"""---
title: Teams
description: Franchise histories and owners of the Pine Hills Fantasy Football League.
---

# 👥 Teams

Every franchise in Pine Hills history. Each team page tracks the owner, season-by-season results, championships, and head-to-head records. Standings-derived stats are computed automatically; owners and titles come from the league bible.

## Active & Historical Franchises

| Team | Owner | Seasons | Titles |
|------|-------|---------|--------|
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


def gen_seasons_index(seasons: dict, bible: dict) -> str:
    rows = []
    for year in sorted(seasons, reverse=True):
        champion = champ_year(bible, year).get("champion") or TBD
        rows.append(f"| {year} | {champion} | {TBD} | {wikilink(f'{year} Season')} |")
    # include 2018/2019 placeholders if referenced
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


def gen_root_index(seasons: dict, bible: dict) -> list[str]:
    rows = []
    for year in sorted(seasons, reverse=True):
        champion, runner_up, top_seed, _ = champ_fields(bible, year)
        rows.append(f"| {year} | {champion} | {runner_up} | {top_seed} |")
    return rows


def gen_champions_page(seasons: dict, bible: dict) -> str:
    rows = []
    for year in sorted(seasons, reverse=True):
        champion, runner_up, top_seed, _ = champ_fields(bible, year)
        rows.append(f"| {year} | {champion} | {runner_up} | {top_seed} | {wikilink(f'{year} Season')} |")

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
    championship_tally = {}
    for year in seasons:
        champion_data = champ_year(bible, year)
        if champion_data.get("champion"):
            championship_tally.setdefault(champion_data["champion"], []).append(year)
    if championship_tally:
        for team, years in sorted(championship_tally.items(), key=lambda x: (-len(x[1]), x[0])):
            md += f"| {team} | {len(years)} | {', '.join(str(y) for y in sorted(years))} |\n"
    else:
        md += f"| {TBD} | 0 | — |\n"

    md += f"""
## Related

- {wikilink('Seasons')} · {wikilink('Playoffs')} · {wikilink('Records')} · {wikilink('Teams')}
"""
    return md


def gen_draft_index(seasons: dict, bible: dict) -> str:
    rows = []
    for year in sorted(seasons, reverse=True):
        rows.append(f"| {year} | {wikilink(f'{year} Draft')} | {TBD} |")
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


def gen_playoffs_page(seasons: dict, bible: dict) -> str:
    md = f"""---
title: Playoffs
description: Pine Hills Fantasy Football League playoff format, champions, and Finals history.
---

# 🏆 Playoffs

The Pine Hills Fantasy Football League postseason. The top four teams by regular-season record qualify for the playoffs; the winner is crowned league champion.

## Format

- **Qualifiers:** top {PLAYOFF_SEEDS} regular-season teams (seeds 1–{PLAYOFF_SEEDS}).
- **Champion:** determined by the playoff bracket, not regular-season standing.
- **Consolation (Toilet Bowl):** contested by non-qualifiers.

## Champions by Year

| Year | Champion | Runner-Up | Season |
|------|----------|-----------|--------|
"""
    for year in sorted(seasons, reverse=True):
        champion, runner_up, _, _ = champ_fields(bible, year)
        md += f"| {year} | {champion} | {runner_up} | {wikilink(f'{year} Season')} |\n"

    md += f"""
> Playoff brackets and game scores are recorded in the league bible (`raw/bible.yaml`). Add per-year `champion` / `runner_up` to populate results.

## Related

- {wikilink('Champions')} · {wikilink('Seasons')} · {wikilink('Records')} · {wikilink('Lore')}
"""
    return md

# --------------------------------------------------------------------------- #
# root index table generator
# --------------------------------------------------------------------------- #
def gen_root_index(years: list[int], bible: dict) -> list[str]:
    """Generate rows for the root index champions table.
    Returns a list of markdown lines, including header and separator.
    """
    header = [
        "| Year | Champion | Runner-Up | Top Seed |",
        "|------|----------|-----------|----------|",
    ]
    rows = []
    for year in sorted(years, reverse=True):
        champion, runner_up, top_seed, _ = champ_fields(bible, year)
        rows.append(f"| {year} | {champion} | {runner_up} | {top_seed} |")
    return header + rows


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
        sp.write_text(dash_normalize(gen_season(year, d, bible, aggregates)))
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
            dash_normalize(
                f"---\ntitle: \"{year} Draft\"\ndescription: \"Pine Hills FF {year} draft board.\"\n---\n\n"
                f"# 🎯 {year} Draft\n\n" + "\n".join(dlines) +
                f"\n\n## Related\n\n- {wikilink('Draft History')} · {wikilink(f'{year} Season')}\n"
            )
        )
        print(f"  wrote {dp.relative_to(ROOT)}")

    # team pages
    for name, ydata in team_years.items():
        tp = CONTENT / "teams" / f"{slug(name)}.md"
        tp.write_text(dash_normalize(gen_team_page(name, ydata, bible, aggregates)))
        print(f"  wrote {tp.relative_to(ROOT)}")

    all_years = sorted(seasons.keys())

    # records index
    rp = CONTENT / "records" / "index.md"
    rp.write_text(dash_normalize(gen_records_index(seasons, aggregates, bible)))
    print(f"  wrote {rp.relative_to(ROOT)}")

    # teams index
    tip = CONTENT / "teams" / "index.md"
    tip.write_text(dash_normalize(gen_teams_index(aggregates, bible)))
    print(f"  wrote {tip.relative_to(ROOT)}")

    # seasons index
    sip = CONTENT / "seasons" / "index.md"
    sip.write_text(dash_normalize(gen_seasons_index(all_years, bible)))
    print(f"  wrote {sip.relative_to(ROOT)}")

    # draft index (scoped to real years — avoids broken links to 2018/2019)
    dip = CONTENT / "draft" / "index.md"
    dip.write_text(dash_normalize(gen_draft_index(all_years, bible)))
    print(f"  wrote {dip.relative_to(ROOT)}")

    # champions + playoffs (NBA-style)
    cp = CONTENT / "champions.md"
    cp.write_text(dash_normalize(gen_champions_page(all_years, bible)))
    print(f"  wrote {cp.relative_to(ROOT)}")
    pp = CONTENT / "playoffs.md"
    pp.write_text(dash_normalize(gen_playoffs_page(all_years, bible)))
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
        root.write_text(dash_normalize("\n".join(out) + "\n"))
        print(f"  updated {root.relative_to(ROOT)} (champions table)")

    print("Done generating Markdown.")


if __name__ == "__main__":
    main()
