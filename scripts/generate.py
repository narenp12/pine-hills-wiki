"""
Generate Wikipedia-style Markdown wiki pages for the Pine Hills Fantasy
Football League from raw/ JSON (produced by extract.py) plus a hand-maintained
raw/bible.yaml of human-only facts.

Design principle — NEVER FABRICATE:
  * Facts derivable from captured Yahoo data (standings + draft) are computed.
  * Facts that are NOT in the data (owners, champions, playoff results, lore)
    come ONLY from raw/bible.yaml. If absent there, the page shows "_TBD_".
  * The regular-season #1 is NOT assumed to be the champion (this is a playoff
    league). Champion / runner-up / top seed / toilet winner are DERIVED from
    Yahoo's final playoff-adjusted rank when raw/<year>.json carries a
    `champions` block; the bible is only a fallback for seasons without one.

Builds / rewrites (into WIKI_CONTENT_DIR, default zensical/.stage, which
zensical/transform.py turns into zensical/docs):
  seasons/<year>-season.md     (standings, playoffs stub, awards)
  teams/<slug>.md              (franchise page + season log)
  players/<slug>.md            (player page + team history)
  players/index.md             (every rostered player, by position)
  records/index.md             (all-time + single-season leaders)
  teams/index.md               (franchise table)
  seasons/index.md             (champions-by-year table)
  index.md                     (root champions table)
  champions.md                 (NBA-style "List of champions")
  lore.md                      (community lore, from the bible's `lore` block)
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
# FALLBACK ONLY. This league's field has never been 4 — it ran 6 teams in 2018
# and 8 by 2025 — so anything that can read bracket membership from captured
# matchups must do that instead. This is what remains for a season with no
# matchup data at all, where a cutoff is the only thing left to guess with.
PLAYOFF_SEEDS = 4
# Week boundaries used throughout the generator
POST_DRAFT_WEEK = 1
END_SEASON_WEEK = 18
PLAYOFF_START_WEEK = 14
PLAYOFF_END_WEEK = 18
INITIAL_WORST_PF = 1e9
# Franchises listed inline in a table cell before the rest fold into a
# "+N more" disclosure. Three fits a column without wrapping on a laptop; the
# player books get two, since their rows already carry a score and a date.
OWNER_INDEX_TEAMS_SHOWN = 3
PLAYER_BOOK_TEAMS_SHOWN = 2


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
# Not the same as _TBD_. TBD means the fact is missing and could still be
# recorded; NA means the question does not apply, so nobody should go looking.
# The first captured season has no Newcomer of the Year because every player in
# it is new, which is a fact about the award rather than a gap in the data.
NA = "_NA_"

# Team images are hand-supplied: Yahoo's capture carries no logo URL. Files live
# under zensical/docs/<TEAM_IMAGE_DIR>/ and are mapped to a team in the bible's
# `team_images` block.
TEAM_IMAGE_DIR = "assets/teams"


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
    # Draft picks carry no position of their own; rosters do. Fill them once
    # here so every consumer — draft boards and the draft-value awards — sees
    # the same data.
    for season_data in seasons.values():
        backfill_draft_positions(season_data)
        annotate_overall_picks(season_data)
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


def shared_label(label: str, holders: int) -> str:
    """Label a record more than one holder shares.

    "Tie" belongs to a game that actually ended level, so a record several
    holders share says how many share it instead of borrowing the scoreline's
    word. The count is the fact worth printing: six players sharing a mark reads
    very differently from two.
    """
    return label if holders < 2 else f"{label} ({holders}-way tie)"


def shared_label_cells(label: str, holders: int) -> list[str]:
    """The label cell for each of a shared record's rows.

    The first row carries the label and the count; the rest are blank, so the
    eye reads the holders as one group rather than as N repetitions of the same
    sentence. `tablesort.js` skips any table with a blank leading cell, since
    sorting one would scatter a group away from the label that heads it.
    """
    if holders < 2:
        return [label]
    return [shared_label(label, holders)] + [""] * (holders - 1)


def more_list(names: list, shown: int) -> str:
    """An inline list that keeps its overflow reachable.

    A bare "+4 more" is a dead end: the names exist in the data and the reader
    has no way to reach them. The overflow goes into a `<details>` they can open
    in place, which still works as a disclosure widget with JavaScript off.

    The revealed names are wrapped and labelled deliberately. A browser slots
    `<details>` content into a block box whatever the element's own `display`
    is, so the overflow cannot be made to flow inline after the summary - it
    always starts a new line. Left unstyled that reads as a broken line break,
    so it is presented as what it is: an indented continuation, under a toggle
    that swaps to "show less" while it is open.
    """
    if not names:
        return TBD
    if len(names) <= shown:
        return ", ".join(names)
    rest = names[shown:]
    return (
        f"{', '.join(names[:shown])} "
        f'<details class="more"><summary>'
        f'<span class="more-show">+{len(rest)} more</span>'
        f'<span class="more-hide">show less</span>'
        f"</summary>"
        f'<span class="more-list">{", ".join(rest)}</span></details>'
    )


def standings_teams(season_data: dict) -> list[dict]:
    """Extract the list of team standings from a season JSON."""
    standings = season_data.get("standings", {}) or {}
    standings = standings.get("standings", standings) if isinstance(standings, dict) else standings
    teams = standings.get("teams", []) if isinstance(standings, dict) else []
    return teams


def build_name_to_canonical(bible: dict) -> dict:
    """Map every known franchise name (including aliases) -> canonical name."""
    name_to_canonical = {}
    for canonical_name, names in (bible.get("aliases", {}) or {}).items():
        name_to_canonical[canonical_name] = canonical_name
        for name in names or []:
            name_to_canonical[name] = canonical_name
    return name_to_canonical


# --------------------------------------------------------------------------- #
# team images (hand-supplied — Yahoo's capture carries no logo)
# --------------------------------------------------------------------------- #
def get_team_images(bible: dict) -> dict:
    """`team_images` from the bible: team name -> file name, path, or URL."""
    return bible.get("team_images", {}) or {}


def team_image_src(name: str, images: dict, prefix: str = "../") -> str:
    """Resolve a bible `team_images` entry to a source-relative Markdown path.

    Accepts a bare file name ("roger-that.png" — assumed to live in
    docs/assets/teams/), a docs-relative path ("assets/teams/roger-that.png"),
    or an absolute URL, which is passed through untouched. Returns "" when the
    team has no image, so callers can omit the field entirely rather than
    rendering a broken placeholder.
    """
    raw = str(images.get(name, "") or "").strip()
    if not raw:
        return ""
    if re.match(r"^(?:https?:)?//", raw) or raw.startswith("data:"):
        return raw
    raw = raw.lstrip("/")
    if not raw.startswith(f"{TEAM_IMAGE_DIR}/"):
        raw = f"{TEAM_IMAGE_DIR}/{raw}"
    return f"{prefix}{raw}"


# --------------------------------------------------------------------------- #
# aggregate: cross-year franchise stats (data-derivable only)
# --------------------------------------------------------------------------- #
def build_aggregates(seasons: dict, playoff_teams=None) -> dict:
    """Return {canonical_name: stats}. Stats are purely data-derived.

    `playoff_teams` is the set of (year, team) that actually reached the bracket.
    Pass it whenever it is available: the field has grown from six teams to
    eight, so the fixed `PLAYOFF_SEEDS` cutoff undercounts appearances for every
    season with a larger bracket. It stays as the fallback for seasons with no
    captured matchups.
    """
    # alias map: every known name -> canonical
    bible = load_bible()
    name_to_canonical = build_name_to_canonical(bible)

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
            if made_playoffs(year, team_name, rank, playoff_teams):
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


def apply_derived_champions(bible: dict, seasons: dict) -> dict:
    """Overlay machine-derived champion facts from raw/<year>.json onto the bible.

    The scraper's v2 API path writes a `champions` block per season, derived from
    Yahoo's final playoff-adjusted standings rank. That is authoritative, so it
    WINS over the hand-maintained bible for champion / runner_up / top_seed --
    the bible's own header says machine-derivable facts must not be hand-edited.

    `toilet_winner` is derived too -- it is simply whoever finished last in the
    final standings. Seasons with no derived block (e.g. built by the older
    rendered-page path) keep whatever the bible has.
    """
    champs = bible.setdefault("champions", {}) or {}
    bible["champions"] = champs
    for year, data in seasons.items():
        derived = (data or {}).get("champions")
        if not derived:
            continue
        # The bible may key years as int or str; keep whichever is already there.
        key = year if year in champs else (str(year) if str(year) in champs else year)
        entry = dict(champs.get(key) or {})
        for field in ("champion", "runner_up", "top_seed", "toilet_winner"):
            value = derived.get(field)
            if value:
                entry[field] = value
        champs[key] = entry
    return bible


def apply_derived_owners(bible: dict, seasons: dict) -> dict:
    """Overlay every team's owner from raw/<year>.json onto the bible.

    The v2 API reports the manager of EVERY team; the bible's hand-maintained
    `owners` map only ever had one entry. Several call sites look owners up by
    team name through the bible, so filling it here fixes all of them at once.

    Later seasons win, so a franchise that changed hands reads as its most recent
    owner. Names absent from the data keep whatever the bible says.
    """
    owners = bible.setdefault("owners", {}) or {}
    bible["owners"] = owners
    for year in sorted(seasons):
        for team in standings_teams(seasons[year]):
            name, owner = team.get("name"), team.get("owner")
            if name and owner:
                owners[name] = owner
    return bible


def champ_fields(bible: dict, year: int) -> tuple[str, str, str, str]:
    """Return (champion, runner_up, top_seed, toilet_winner) for a year."""
    champion_data = champ_year(bible, year)
    return (
        champion_data.get("champion") or TBD,
        champion_data.get("runner_up") or TBD,
        champion_data.get("top_seed") or TBD,
        champion_data.get("toilet_winner") or TBD,
    )


# --------------------------------------------------------------------------- #
# aggregate: cross-franchise owner (manager) stats
# --------------------------------------------------------------------------- #
def get_owner_aliases(bible: dict) -> dict:
    """`owner_aliases` from the bible: canonical person -> list of variants."""
    return bible.get("owner_aliases", {}) or {}


def build_owner_map(bible: dict, seasons: dict) -> dict:
    """Map a lower-cased raw owner name -> the canonical name to display.

    Yahoo reports the manager name as typed, so the same person shows up as
    "lokesh" one year and "Lokesh" the next. Everything is keyed case-folded, so
    casing variants collapse on their own; the bible's `owner_aliases` block
    handles the cases that are genuinely different spellings.
    """
    owner_map = {}
    for canonical_name, variants in get_owner_aliases(bible).items():
        canonical_name = str(canonical_name).strip()
        if not canonical_name:
            continue
        owner_map[canonical_name.lower()] = canonical_name
        for variant in variants or []:
            variant = str(variant).strip()
            if variant:
                owner_map[variant.lower()] = canonical_name
    # Names the bible does not mention keep the casing the data uses. Later
    # seasons win, matching apply_derived_owners.
    from_bible = set(owner_map)
    for year in sorted(seasons):
        for team in standings_teams(seasons[year]):
            owner = str(team.get("owner") or "").strip()
            if owner and owner.lower() not in from_bible:
                owner_map[owner.lower()] = owner
    return owner_map


def canonical_owner(name: str, owner_map: dict) -> str:
    name = str(name or "").strip()
    return owner_map.get(name.lower(), name)


def made_playoffs(year: int, name: str, rank: int, playoff_teams) -> bool:
    """Did this team reach the bracket? Falls back to the seed cutoff if the
    season has no captured bracket to read membership from."""
    if playoff_teams is None:
        return rank <= PLAYOFF_SEEDS
    return (year, name) in playoff_teams


def build_owner_aggregates(
    seasons: dict, bible: dict, owner_map: dict, playoff_teams=None
) -> dict:
    """Return {canonical_owner: stats} across every franchise that person ran.

    Purely data-derived, except that championships are attributed through the
    champion team name for each year (itself derived from Yahoo's final rank).
    """
    name_to_canonical = build_name_to_canonical(bible)
    owners = {}

    for year in sorted(seasons):
        champion = champ_year(bible, year).get("champion") or ""
        for team in standings_teams(seasons[year]):
            owner_raw = str(team.get("owner") or "").strip()
            if not owner_raw:
                continue
            owner = canonical_owner(owner_raw, owner_map)
            team_name = team.get("name", "Unknown")
            canonical_team = name_to_canonical.get(team_name, team_name)

            record = owners.setdefault(
                owner,
                {
                    "rows": [],          # (year, team_name, canonical_team, w, l, rank, playoffs)
                    "teams": {},         # canonical team -> {"name": display, "years": [...], "wins", "losses"}
                    "wins": 0,
                    "losses": 0,
                    "pf": 0.0,
                    "pa": 0.0,
                    "playoff_appears": 0,
                    "seasons_count": 0,
                    "titles": [],
                    "finishes": [],      # (rank, year)
                },
            )
            wins = int(team.get("wins", 0))
            losses = int(team.get("losses", 0))
            rank = int(team.get("rank", DEFAULT_RANK))
            reached_playoffs = made_playoffs(year, team_name, rank, playoff_teams)

            record["rows"].append((year, team_name, canonical_team, wins, losses, rank, reached_playoffs))
            record["wins"] += wins
            record["losses"] += losses
            record["pf"] += float(team.get("points_for", 0) or 0)
            record["pa"] += float(team.get("points_against", 0) or 0)
            record["seasons_count"] += 1
            record["finishes"].append((rank, year))
            if reached_playoffs:
                record["playoff_appears"] += 1
            if champion and champion in (team_name, canonical_team):
                record["titles"].append(year)

            franchise = record["teams"].setdefault(
                canonical_team, {"name": team_name, "years": [], "wins": 0, "losses": 0}
            )
            # Later seasons win the display name, so a renamed franchise reads as
            # whatever it was called most recently under this owner.
            franchise["name"] = team_name
            franchise["years"].append(year)
            franchise["wins"] += wins
            franchise["losses"] += losses

    out = {}
    for owner, record in owners.items():
        games_played = record["wins"] + record["losses"]
        years = sorted({row[0] for row in record["rows"]})
        out[owner] = {
            "rows": sorted(record["rows"]),
            "teams": record["teams"],
            "years": years,
            "seasons_count": len(years),
            "wins": record["wins"],
            "losses": record["losses"],
            "gp": games_played,
            "wpct": (record["wins"] / games_played) if games_played else 0.0,
            "pf": round(record["pf"], 2),
            "pa": round(record["pa"], 2),
            "playoff_appears": record["playoff_appears"],
            "titles": sorted(record["titles"]),
            "finishes": sorted(record["finishes"]),
        }
    return out


# --------------------------------------------------------------------------- #
# aggregate: per-game stats from the weekly matchup log
# --------------------------------------------------------------------------- #
# Weeks 15-17 carry bracket games and consolation games in the same matchup
# list. They are told apart so a title-game score can hold a league record while
# consolation play stays out of the regular-season and playoff ledgers.
PHASE_REGULAR = "regular"
PHASE_PLAYOFF = "playoff"
PHASE_CONSOLATION = "consolation"
PHASE_LABELS = {
    PHASE_REGULAR: "",
    PHASE_PLAYOFF: " (playoffs)",
    PHASE_CONSOLATION: " (consolation)",
}
# The bracket's own label for the title game, kept apart as its own record book.
FINALS_ROUND = "Final"
# Not a phase a game can be in: the book that spans every game regardless of phase.
BOOK_TOTAL = "total"
# Rate leaders need a real sample, but the league is small: eight seasons and
# sixteen managers, several of whom played exactly one year. Both minimums are
# one complete unit of play rather than a round number -- a full regular season
# (the shortest captured one, 2018, ran 11 games) and a full bracket run
# (quarterfinal, semifinal, final). Anything higher silently drops a third of
# the league and hides real marks: at four playoff games the league's best
# postseason scoring average disappears.
MIN_GAMES_FOR_AVERAGE = 11
# One full bracket run: quarterfinal, semifinal, final.
MIN_PLAYOFF_GAMES_FOR_RATE = 3
# Cutoffs for the blowout and nailbiter boards, set from the actual spread of
# margins rather than picked out of the air: across every captured game the
# median margin is 23.4 and the 90th percentile 61.2, so 80+ is the top ~3% of
# games and under a point the bottom ~4%. Both land near 20 rows.
BLOWOUT_MARGIN = 80.0
NAILBITER_MARGIN = 1.0
# Rivalry tables list the opponents a franchise has actually played repeatedly.
RIVALRY_ROWS = 5
MIN_RIVALRY_MEETINGS = 2


def _game_pair(game: dict) -> tuple:
    """(name, score, is_winner) for each side of a matchup, or () if malformed."""
    teams = game.get("teams") or []
    if len(teams) != 2:
        return ()
    return tuple(
        (t.get("name"), float(t.get("score", 0) or 0), bool(t.get("is_winner")))
        for t in teams
    )


def season_phases(season_data: dict) -> tuple:
    """Return (playoff_start_week, {(week, frozenset(names)): round}) per season.

    The round label is what lets Finals records be kept apart from the rest of
    the bracket, the way the NBA record book does. A season without a captured
    bracket reports no playoff start, so every game in it counts as regular
    season rather than being silently dropped.
    """
    playoff_weeks = {
        int(week) for week in ((season_data.get("playoffs") or {}).get("weeks") or {})
    }
    bracket_games = {}
    for game in (season_data.get("bracket") or {}).get("games", []):
        pair = _game_pair(game)
        if pair:
            week = int(game.get("week", 0))
            bracket_games[(week, frozenset(side[0] for side in pair))] = game.get("round") or ""
            playoff_weeks.add(week)
    return (min(playoff_weeks) if playoff_weeks else None), bracket_games


def build_game_log(seasons: dict, bible: dict) -> list:
    """Flatten every captured matchup into one row per team per game.

    Two rows per game (one from each side) is what makes head-to-head records,
    weekly-score boards and streaks all fall out of a single pass.
    """
    name_to_canonical = build_name_to_canonical(bible)
    log = []
    for year in sorted(seasons):
        season_data = seasons[year]
        playoff_start, bracket_games = season_phases(season_data)
        for week_key, games in sorted(
            (season_data.get("matchups") or {}).items(), key=lambda kv: int(kv[0])
        ):
            week = int(week_key)
            for game in games:
                pair = _game_pair(game)
                if not pair:
                    continue
                bracket_key = (week, frozenset(side[0] for side in pair))
                playoff_round = ""
                if playoff_start is None or week < playoff_start:
                    phase = PHASE_REGULAR
                elif bracket_key in bracket_games:
                    phase = PHASE_PLAYOFF
                    playoff_round = bracket_games[bracket_key]
                else:
                    phase = PHASE_CONSOLATION
                for index, (name, score, is_winner) in enumerate(pair):
                    opponent, opponent_score, _ = pair[1 - index]
                    log.append(
                        {
                            "year": year,
                            "week": week,
                            "phase": phase,
                            "round": playoff_round,
                            "team": name,
                            "canonical": name_to_canonical.get(name, name),
                            "opponent": opponent,
                            "opponent_canonical": name_to_canonical.get(opponent, opponent),
                            "score": score,
                            "opponent_score": opponent_score,
                            # is_winner is what Yahoo reported; the score compare is
                            # the fallback for games it left unflagged.
                            "won": is_winner or score > opponent_score,
                            # Fantasy games can end level, and Yahoo drops those
                            # from the standings W-L entirely (2018 Wk 8 leaves
                            # both teams a game short of the season's length).
                            "tied": score == opponent_score,
                            "margin": round(score - opponent_score, 2),
                        }
                    )
    return log


def build_player_log(seasons: dict) -> list:
    """One row per player per week per roster, phase-tagged.

    Phase comes from the same bracket read `build_game_log` uses, so a
    consolation week never contaminates the playoff book. A row is tagged with
    the team whose roster the player sat on that week.
    """
    log = []
    for year in sorted(seasons):
        season_data = seasons[year]
        playoff_start, bracket_games = season_phases(season_data)
        # (week, team) -> the bracket round that team played that week. Keeping
        # the round, not just the fact of a playoff game, is what lets a mark be
        # reported as the Final rather than a generic postseason week.
        bracket_teams = {
            (week, name): round_label
            for (week, names), round_label in bracket_games.items()
            for name in names
        }
        for week_key, week_data in sorted(
            (season_data.get("weeks") or {}).items(), key=lambda kv: int(kv[0])
        ):
            week = int(week_key)
            for team_name, roster in ((week_data or {}).get("rosters") or {}).items():
                playoff_round = ""
                if (week, team_name) in bracket_teams:
                    phase = PHASE_PLAYOFF
                    playoff_round = bracket_teams[(week, team_name)]
                elif playoff_start is not None and week >= playoff_start:
                    phase = PHASE_CONSOLATION
                else:
                    phase = PHASE_REGULAR
                for player in roster.get("players") or []:
                    slot = player.get("slot") or ""
                    log.append({
                        "year": year,
                        "week": week,
                        "phase": phase,
                        "round": playoff_round,
                        "team": team_name,
                        "player": player.get("name") or "",
                        "position": player.get("position") or "",
                        "slot": slot,
                        "points": float(player.get("points") or 0.0),
                        "started": slot not in BENCH_SLOTS,
                    })
    return log


def player_pool(player_log: list, scope: str) -> list:
    """The rows belonging to one book.

    `FINALS_ROUND` is a round, not a phase: the title game only. Every other
    scope is a phase. Consolation games run in the same weeks as the bracket, so
    filtering on the week would drag them in — this filters on what the bracket
    actually said.
    """
    if scope == FINALS_ROUND:
        return [row for row in player_log if row.get("round") == FINALS_ROUND]
    return [row for row in player_log if row["phase"] == scope]


def player_book_rows(player_log: list, scope: str = PHASE_REGULAR) -> list[str]:
    """One phase's player book as table rows.

    Called once per scope so the books stay apart the way the team books do: a
    huge October week cannot become a Finals record. `scope` is `PHASE_REGULAR`,
    `PHASE_PLAYOFF`, or `FINALS_ROUND`.

    Season totals and weeks-rostered appear only in the regular-season book.
    They are whole-season and career marks, so repeating them inside the Finals
    book would say nothing about the Finals.

    Ties are listed and marked, never arbitrated — the same rule the team books
    follow. Bench marks read the whole pool; every other book reads starters
    only, since a benched score is not a lineup result.
    """
    pool = player_pool(player_log, scope)
    started = [row for row in pool if row["started"]]
    # A scoped book already says which phase it covers in its heading, so the
    # row labels do not repeat it.
    career_marks = scope == PHASE_REGULAR

    def holders_rows(label, items, key, value, when) -> list[str]:
        holders = top_holders(items, key)
        if not holders:
            return [f"| {label} | {TBD} | {TBD} | {TBD} |"]
        cells = shared_label_cells(label, len(holders))
        return [
            f"| {cell} | {wikilink(row['player'])} | {value(row)} | {when(row)} |"
            for cell, row in zip(cells, holders)
        ]

    def week_when(row) -> str:
        """When and for whom: "2024 Wk 16 (Final), Stroud Boys".

        The bracket round is more specific than the phase tag, so it wins when
        the game had one — a Final reads as a Final, not as a generic postseason
        week. The fantasy team is always named: a player's big week belongs to
        whoever actually had them rostered.
        """
        tag = f" ({row['round']})" if row.get("round") else PHASE_LABELS[row["phase"]]
        return f"{row['year']} Wk {row['week']}{tag}, {wikilink(row['team'])}"

    def points_value(row) -> str:
        return f"{row['points']:.2f} ({row['position'] or '—'})"

    season_totals = {}
    for row in started:
        key = (row["player"], row["team"], row["year"])
        season_totals[key] = season_totals.get(key, 0.0) + row["points"]
    totals = [
        {"player": k[0], "team": k[1], "year": k[2], "points": v}
        for k, v in season_totals.items()
    ]

    # Weeks rostered is a career mark, so it needs the teams that did the
    # rostering — a player who bounced between three managers reads very
    # differently from one who sat on the same roster all eight years.
    rostered = {}
    rostered_teams = {}
    for row in player_log:
        player = row["player"]
        rostered[player] = rostered.get(player, 0) + 1
        teams = rostered_teams.setdefault(player, {})
        teams[row["team"]] = teams.get(row["team"], 0) + 1
    weeks_rows = [
        {
            "player": k,
            "weeks": v,
            # Most weeks first, so the primary owner leads.
            "teams": sorted(rostered_teams[k], key=lambda t: -rostered_teams[k][t]),
        }
        for k, v in rostered.items()
    ]

    def teams_when(row) -> str:
        return more_list([wikilink(t) for t in row["teams"]], PLAYER_BOOK_TEAMS_SHOWN)

    table = []
    table += holders_rows(
        "Highest Week", started, lambda r: r["points"], points_value, week_when,
    )
    table += holders_rows(
        "Highest-Scoring Benched Player",
        [r for r in pool if not r["started"]],
        lambda r: r["points"], points_value, week_when,
    )
    if career_marks:
        table += holders_rows(
            "Highest Season Total", totals,
            lambda r: r["points"],
            lambda r: f"{r['points']:.2f}",
            lambda r: f"{r['year']}, {wikilink(r['team'])}",
        )
        table += holders_rows(
            "Most Weeks Rostered", weeks_rows,
            lambda r: r["weeks"],
            lambda r: f"{r['weeks']} weeks",
            teams_when,
        )
    return table


# --------------------------------------------------------------------------- #
# player index: one career record per player, across every roster they sat on
# --------------------------------------------------------------------------- #
# Positions, in the order a league page reads them. Anything Yahoo reports that
# is not on the list still gets a section, appended after these.
POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF"]
# Franchises listed inline in the players index before it spills to "+N more".
PLAYER_INDEX_TEAMS_SHOWN = 2


def draft_picks_by_player(seasons: dict) -> dict:
    """{player: [pick, ...]} across every captured draft, earliest year first.

    Reads the same shape the draft boards do, including the `overall` number
    `annotate_overall_picks` backfills, so a player page and the board it links
    to quote the same pick.
    """
    picks = {}
    for year in sorted(seasons):
        draft = seasons[year].get("draft") or {}
        rows = draft.get("draft_results", draft.get("results", []))
        if isinstance(rows, dict):
            rows = rows.get("draft_results", [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("player") or "").strip()
            if not name:
                continue
            picks.setdefault(name, []).append(
                {
                    "year": year,
                    "round": row.get("round"),
                    "overall": row.get("overall", row.get("pick")),
                    "team": str(row.get("team") or "").strip(),
                    "position": str(row.get("position") or "").strip(),
                }
            )
    return picks


def team_owners_by_year(seasons: dict, owner_map: dict) -> dict:
    """{(year, team name): canonical owner} from the standings block."""
    owners = {}
    for year, season_data in seasons.items():
        for team in standings_teams(season_data):
            name = str(team.get("name") or "").strip()
            owner = str(team.get("owner") or "").strip()
            if name and owner:
                owners[(year, name)] = canonical_owner(owner, owner_map)
    return owners


def _empty_player_bucket() -> dict:
    """The counters a player record and each of its stints both carry."""
    return {
        "weeks": 0,
        "starts": 0,
        "points": 0.0,
        "bench_points": 0.0,
        "best": None,
        "positions": {},
    }


def _add_player_week(bucket: dict, row: dict) -> None:
    """Fold one roster-week into a bucket.

    Lineup points and bench points are kept apart: a player who scored 30 from
    the bench did not score them for the team, and a career page that adds the
    two together would credit a manager for points they never fielded.
    """
    bucket["weeks"] += 1
    if row["started"]:
        bucket["starts"] += 1
        bucket["points"] += row["points"]
    else:
        bucket["bench_points"] += row["points"]
    best = bucket["best"]
    # The best week is the biggest score of either kind; whether it was started
    # is on the row, so the page can say so.
    if best is None or row["points"] > best["points"]:
        bucket["best"] = row
    position = row["position"]
    if position:
        bucket["positions"][position] = bucket["positions"].get(position, 0) + 1


def player_positions(bucket: dict) -> list:
    """Positions a player was listed at, most-played first.

    Yahoo re-files a handful of players (Taysom Hill, Cordarrelle Patterson)
    mid-career, so a player can hold two honestly. Both are kept rather than
    picking one and quietly dropping the other.
    """
    return sorted(bucket["positions"], key=lambda p: (-bucket["positions"][p], p))


def build_player_index(seasons: dict, player_log: list, owner_map: dict) -> dict:
    """Return {player: career record}, one entry per player ever rostered.

    Built from the same `player_log` the record books read, so a player page can
    never disagree with the leaderboards that link to it. Stints are keyed by
    (year, team): a player who changed hands mid-season gets one row per
    manager, which is the whole point of a team history.

    Players who were drafted and then cut before the first captured roster still
    get a record, so the draft boards have somewhere to link.
    """
    owners = team_owners_by_year(seasons, owner_map)
    drafts = draft_picks_by_player(seasons)

    index = {}
    for row in player_log:
        record = index.get(row["player"])
        if record is None:
            record = _empty_player_bucket()
            record.update({"name": row["player"], "years": set(), "teams": {}, "stints": {}})
            index[row["player"]] = record
        _add_player_week(record, row)
        record["years"].add(row["year"])
        record["teams"][row["team"]] = record["teams"].get(row["team"], 0) + 1

        key = (row["year"], row["team"])
        stint = record["stints"].get(key)
        if stint is None:
            stint = _empty_player_bucket()
            stint.update(
                {
                    "year": row["year"],
                    "team": row["team"],
                    "owner": owners.get(key, ""),
                }
            )
            record["stints"][key] = stint
        _add_player_week(stint, row)

    for name, picks in drafts.items():
        record = index.get(name)
        if record is None:
            record = _empty_player_bucket()
            record.update({"name": name, "years": set(), "teams": {}, "stints": {}})
            for pick in picks:
                if pick["position"]:
                    record["positions"][pick["position"]] = (
                        record["positions"].get(pick["position"], 0) + 1
                    )
            index[name] = record
        record["drafts"] = picks

    for record in index.values():
        record.setdefault("drafts", [])
        record["years"] = sorted(record["years"])
    return index


def build_decisive_wins(player_log: list, game_log: list) -> dict:
    """{(year, player): record} of the wins each player swung, across every phase.

    A win is "swung" when the player was in the starting lineup, their team won,
    and they outscored the margin of victory: take the player out of that lineup
    and the result flips. It is the narrowest defensible reading of contributing
    to a win, and unlike raw points it cannot credit a player who piled up
    yardage in games their team lost by forty.

    Each record carries the position and the franchises the swung wins came for,
    so the same pass answers the MVP award and the per-position team of the
    season. Ties are excluded - nothing was won to swing.
    """
    margins = {
        (row["year"], row["week"], row["team"]): row["margin"]
        for row in game_log
        if row["won"] and not row["tied"]
    }
    decisive = {}
    for row in player_log:
        if not row["started"]:
            continue
        margin = margins.get((row["year"], row["week"], row["team"]))
        if margin is None or row["points"] <= margin:
            continue
        record = decisive.setdefault(
            (row["year"], row["player"]),
            {"player": row["player"], "wins": 0, "points": 0.0, "positions": {}, "teams": {}},
        )
        record["wins"] += 1
        record["points"] += row["points"]
        if row["position"]:
            record["positions"][row["position"]] = (
                record["positions"].get(row["position"], 0) + 1
            )
        record["teams"][row["team"]] = record["teams"].get(row["team"], 0) + 1
    return decisive


# Which positions a flex slot will accept. Yahoo's slot vocabulary; anything
# not listed here is a fixed-position slot that only takes its own position.
FLEX_SLOTS = {
    "W/R": ("RB", "WR"),
    "W/T": ("WR", "TE"),
    "W/R/T": ("RB", "WR", "TE"),
    "Q/W/R/T": ("QB", "RB", "WR", "TE"),
}


def season_lineup_shape(season_data: dict) -> list:
    """The season's starting lineup, slot by slot, read off the rosters.

    Discovered rather than assumed: the shape is whatever most team-weeks
    actually started that year, so a season that added a flex or dropped a
    kicker selects a team matching its own rules. Bench and IR are not slots
    anyone is selected into.
    """
    shapes = {}
    for week_data in (season_data.get("weeks") or {}).values():
        for roster in ((week_data or {}).get("rosters") or {}).values():
            counts = {}
            for player in roster.get("players") or []:
                slot = player.get("slot") or ""
                if slot and slot not in BENCH_SLOTS:
                    counts[slot] = counts.get(slot, 0) + 1
            if counts:
                key = tuple(sorted(counts.items()))
                shapes[key] = shapes.get(key, 0) + 1
    if not shapes:
        return []
    # The modal lineup, not the largest: one team with an illegal roster in one
    # week should not redefine the league's shape.
    modal = max(shapes.items(), key=lambda kv: (kv[1], kv[0]))[0]
    order = {slot: index for index, slot in enumerate(ROSTER_SLOT_ORDER)}
    slots = []
    for slot, count in sorted(modal, key=lambda kv: order.get(kv[0], len(order))):
        slots.extend([slot] * count)
    return slots


def top_n_holders(rows: list, key, count: int) -> list:
    """The best `count` rows, plus anyone tied with the last of them.

    An All-Pro team names co-selections rather than breaking a tie with a
    coin toss, which is also the rule the record books here follow.
    """
    if not rows or count < 1:
        return []
    ranked = sorted(rows, key=key, reverse=True)
    if len(ranked) <= count:
        return ranked
    cutoff = key(ranked[count - 1])
    return [row for row in ranked if key(row) >= cutoff]


def team_of_the_season(year: int, season_data: dict, decisive: dict) -> list:
    """Fill every starting slot with the players who swung the most wins there.

    The league's own lineup decides the shape, and each slot is won on the same
    measure as the MVP award, restricted to the players who played that
    position. Fixed slots are filled first and the flex takes the best player
    left who is eligible for it, so a flex-worthy back cannot cost a team its
    second running back.
    """
    pool = {}
    for (row_year, player), record in decisive.items():
        if row_year != year or not record["positions"]:
            continue
        # A player Yahoo re-filed mid-season is selected where they played most.
        position = player_positions(record)[0]
        pool.setdefault(position, []).append(dict(record, position=position))

    rank = lambda row: (row["wins"], row["points"])  # noqa: E731
    slots = season_lineup_shape(season_data)
    # Fixed slots first: the flex should take what is left over, not compete for
    # a place a position slot was going to fill anyway.
    counts = {}
    for slot in slots:
        counts[slot] = counts.get(slot, 0) + 1

    selected = []
    taken = set()
    for slot in [s for s in dict.fromkeys(slots) if s not in FLEX_SLOTS]:
        holders = top_n_holders(pool.get(slot, []), rank, counts[slot])
        if holders:
            taken.update(row["player"] for row in holders)
            selected.append({"slot": slot, "slots": counts[slot], "holders": holders})
    for slot in [s for s in dict.fromkeys(slots) if s in FLEX_SLOTS]:
        eligible = [
            row
            for position in FLEX_SLOTS[slot]
            for row in pool.get(position, [])
            if row["player"] not in taken
        ]
        holders = top_n_holders(eligible, rank, counts[slot])
        if holders:
            taken.update(row["player"] for row in holders)
            selected.append({"slot": slot, "slots": counts[slot], "holders": holders})

    order = {slot: index for index, slot in enumerate(ROSTER_SLOT_ORDER)}
    selected.sort(key=lambda entry: order.get(entry["slot"], len(order)))
    return selected


def team_of_the_season_rows(selected: list) -> list:
    """The selection as table rows, one per slot."""
    rows = []
    for entry in selected:
        # Two backs filling two RB slots is not a tie; more holders than slots
        # is. The label carries the count only in that case, and only on the
        # first row, the same way a shared record is labelled.
        extra = len(entry["holders"]) > entry.get("slots", 1)
        for index, row in enumerate(entry["holders"]):
            label = entry["slot"] if index == 0 else ""
            if index == 0 and extra:
                label = f"{entry['slot']} ({len(entry['holders'])}-way tie)"
            teams = sorted(row["teams"], key=lambda team: -row["teams"][team])
            rows.append(
                f"| {label} | {wikilink(row['player'])} | {row['position']} "
                f"| {row['wins']} | {row['points']:.2f} "
                f"| {more_list([wikilink(t) for t in teams], PLAYER_BOOK_TEAMS_SHOWN)} |"
            )
    return rows or [f"| {TBD} | {TBD} | {TBD} | {TBD} | {TBD} | {TBD} |"]


def season_mvp(year: int, decisive: dict) -> list:
    """The season's MVP: the player who swung the most wins.

    League-wide, not per franchise, and not the season's top scorer - points
    piled up in losses win nothing. Ties are listed rather than arbitrated.
    """
    rows = [
        record for (row_year, _), record in decisive.items() if row_year == year
    ]
    return top_holders(rows, lambda row: (row["wins"], row["points"]))


def league_debut_years(player_log: list) -> dict:
    """{player: the first season they appear on any captured roster}.

    This is a debut in *this league*, which is not the same thing as an NFL
    rookie season - the captured data carries no NFL service time. A veteran
    signed off waivers in 2023 debuts here in 2023. The award named from this is
    labelled accordingly.
    """
    debuts = {}
    for row in player_log:
        player = row["player"]
        if player not in debuts or row["year"] < debuts[player]:
            debuts[player] = row["year"]
    return debuts


def award_from_pool(year: int, decisive: dict, eligible) -> list:
    """The most wins swung among the players `eligible` admits."""
    rows = [
        record
        for (row_year, player), record in decisive.items()
        if row_year == year and eligible(player)
    ]
    return top_holders(rows, lambda row: (row["wins"], row["points"]))


def newcomer_of_the_year(year: int, decisive: dict, debuts: dict, first_year: int) -> list:
    """The best season by a player making their first appearance in the league.

    Not a rookie award: it counts a first Pine Hills roster spot, not a first
    NFL season, because nothing in the captured data records NFL service time.
    The first captured season is skipped - every player is new that year, so the
    award would say nothing.
    """
    if year <= first_year:
        return []
    return award_from_pool(year, decisive, lambda player: debuts.get(player) == year)


def undrafted_player_of_the_year(year: int, season_data: dict, decisive: dict) -> list:
    """The best season by a player nobody took in that year's draft.

    Waiver claims and free-agent adds only: a player who went undrafted and then
    decided games is the whole point of the award. A season with no captured
    draft has no award rather than one that flatters every player in the league.
    """
    picks = (season_data.get("draft") or {}).get("draft_results") or []
    if not picks:
        return []
    drafted = {pick.get("player") for pick in picks if pick.get("player")}
    return award_from_pool(year, decisive, lambda player: player not in drafted)


def finals_mvp(year: int, player_log: list, game_log: list) -> list:
    """The Finals MVP: the top scorer in the title game's winning lineup.

    One game decides it, so "wins swung" has nothing to rank - the title game is
    the only game there is. This is the ordinary sporting definition instead:
    the best performance on the team that lifted the trophy. A season with no
    captured Final has no Finals MVP rather than a guessed one.
    """
    winners = {
        (row["year"], row["week"], row["team"])
        for row in game_log
        if row["year"] == year and row.get("round") == FINALS_ROUND and row["won"]
    }
    if not winners:
        return []
    lineup = [
        row
        for row in player_log
        if row["started"] and (row["year"], row["week"], row["team"]) in winners
    ]
    return top_holders(lineup, lambda row: row["points"])


def mvp_cell(holders: list, value) -> str:
    """One table cell naming every holder of an MVP award."""
    if not holders:
        return TBD
    return ", ".join(f"{wikilink(row['player'])} - {value(row)}" for row in holders)


def season_mvp_cell(holders: list) -> str:
    return mvp_cell(holders, lambda row: f"{row['wins']} wins swung")


def finals_mvp_cell(holders: list) -> str:
    return mvp_cell(
        holders, lambda row: f"{row['points']:.2f} pts ({wikilink(row['team'])})"
    )


def draft_pick_label(pick: dict) -> str:
    """Where a player went, as "R4 P41"."""
    parts = []
    if pick.get("round"):
        parts.append(f"R{pick['round']}")
    if pick.get("overall"):
        parts.append(f"P{pick['overall']}")
    return " ".join(parts) or TBD


def top_draft_contributor(year: int, season_data: dict, decisive: dict) -> str:
    """The player from this draft who swung the most wins, and where they went.

    Answers the question the draft board cannot: of everyone taken that year,
    who actually decided games. Ties are listed rather than arbitrated, the same
    rule the record books follow.
    """
    picks = (season_data.get("draft") or {}).get("draft_results") or []
    scored = [
        dict(decisive[(year, pick["player"])], pick=pick)
        for pick in picks
        if pick.get("player") and (year, pick["player"]) in decisive
    ]
    if not scored:
        return TBD
    holders = top_holders(scored, lambda row: (row["wins"], row["points"]))
    return ", ".join(
        f"{wikilink(row['player'])} - {row['wins']} ({draft_pick_label(row['pick'])})"
        for row in holders
    )


def games_by_margin(log: list, threshold: float, above: bool) -> list:
    """Every game whose margin clears a threshold, widest (or closest) first.

    One row per game, from the winner's side. A tie is margin 0.00, so it
    belongs in the close list and is deduplicated to a single row.
    """
    def qualifies(row) -> bool:
        if above:
            return row["margin"] >= threshold
        return 0 <= row["margin"] <= threshold

    seen, games = set(), []
    candidates = [row for row in log if qualifies(row)]
    for row in sorted(candidates, key=lambda r: -r["margin"] if above else r["margin"]):
        game = (row["year"], row["week"], frozenset((row["team"], row["opponent"])))
        if game in seen:
            continue
        seen.add(game)
        games.append(row)
    return games


def top_holders(items: list, key, largest: bool = True) -> list:
    """Every item tied at the extreme.

    Records are shared, not arbitrated: two different games really are both
    decided by 0.02, and two managers really do both have two titles. Returning
    a single winner would silently pick one and hide the other.
    """
    if not items:
        return []
    best = (max if largest else min)(key(item) for item in items)
    return [item for item in items if key(item) == best]


def single_game_leaders(rows: list) -> dict:
    """The single-game records over one pool of games, each a list of holders.

    Called once per phase so the regular-season, playoff and Finals books stay
    separate: a record set in January cannot show up as a Finals record.
    """
    scored = [row for row in rows if row["score"] > 0]
    # A tie has no winner, so it belongs to neither margin record; it is listed
    # on its own instead.
    decided = [row for row in rows if row["margin"] > 0]  # winner's row only
    leaders = {}
    if scored:
        leaders["highest_score"] = top_holders(scored, lambda r: r["score"])
        leaders["lowest_score"] = top_holders(scored, lambda r: r["score"], largest=False)
        leaders["most_points_in_loss"] = top_holders(
            [r for r in scored if not r["won"] and not r["tied"]] or scored,
            lambda r: r["score"],
        )
        leaders["fewest_points_in_win"] = top_holders(
            [r for r in scored if r["won"]] or scored, lambda r: r["score"], largest=False
        )
    if decided:
        leaders["blowout"] = top_holders(decided, lambda r: r["margin"])
        leaders["nailbiter"] = top_holders(decided, lambda r: r["margin"], largest=False)
    # Every tied game, listed rather than ranked: they are the closest games
    # possible and there is nothing to rank them by.
    ties = [row for row in rows if row["tied"]]
    if ties:
        # One row per game, not per side.
        seen, unique = set(), []
        for row in sorted(ties, key=lambda r: (r["year"], r["week"], r["team"])):
            game = (row["year"], row["week"], frozenset((row["team"], row["opponent"])))
            if game not in seen:
                seen.add(game)
                unique.append(row)
        leaders["ties"] = unique
    return leaders


def add_head_to_head(bucket: dict, key: str, display: str, row: dict) -> None:
    """Fold one game into a head-to-head ledger, whatever phase it was played in."""
    record = bucket.setdefault(
        key,
        {
            "name": display,
            "wins": 0,
            "losses": 0,
            "ties": 0,
            "playoff_wins": 0,
            "playoff_losses": 0,
            "pf": 0.0,
            "pa": 0.0,
            "best": None,
            "closest": None,
        },
    )
    record["name"] = display
    if row["tied"]:
        record["ties"] += 1
    else:
        record["wins" if row["won"] else "losses"] += 1
    if row["phase"] == PHASE_PLAYOFF:
        record["playoff_wins" if row["won"] else "playoff_losses"] += 1
    record["pf"] += row["score"]
    record["pa"] += row["opponent_score"]
    # Two meetings are worth remembering from any rivalry: the rout and the one
    # that came down to the wire. game_when says if either was a playoff game.
    if record["best"] is None or abs(row["margin"]) > abs(record["best"]["margin"]):
        record["best"] = row
    # A tie is margin 0.00, which is as close as a meeting can be.
    if record["closest"] is None or abs(row["margin"]) < abs(record["closest"]["margin"]):
        record["closest"] = row


def _streak(rows: list) -> tuple:
    """Longest run of wins in a chronological game list -> (length, year, year)."""
    best = (0, None, None)
    run, start = 0, None
    for row in rows:
        if row["won"]:
            run += 1
            start = start if run > 1 else row["year"]
            if run > best[0]:
                best = (run, start, row["year"])
        else:
            run, start = 0, None
    return best


def build_matchup_stats(seasons: dict, bible: dict) -> dict:
    """Per-team and league-wide records derived from the game log."""
    log = build_game_log(seasons, bible)
    teams = {}

    for row in log:
        record = teams.setdefault(
            row["canonical"],
            {
                "games": [],
                "regular": [],
                "playoff_wins": 0,
                "playoff_losses": 0,
                "playoff_years": set(),
                "head_to_head": {},
            },
        )
        record["games"].append(row)
        # Rivalries count every meeting; the phase-scoped lists below feed the
        # record books, which do not.
        add_head_to_head(
            record["head_to_head"], row["opponent_canonical"], row["opponent"], row
        )
        if row["phase"] == PHASE_REGULAR:
            record["regular"].append(row)
        elif row["phase"] == PHASE_PLAYOFF:
            record["playoff_wins" if row["won"] else "playoff_losses"] += 1
            record["playoff_years"].add(row["year"])

    for record in teams.values():
        record["ties"] = sum(1 for row in record["regular"] if row["tied"])
        regular = record["regular"]
        record["regular_games"] = len(regular)
        record["best_week"] = max(regular, key=lambda r: r["score"], default=None)
        record["worst_week"] = min(regular, key=lambda r: r["score"], default=None)
        record["avg_score"] = (
            round(sum(r["score"] for r in regular) / len(regular), 2) if regular else 0.0
        )
        record["streak"] = _streak(regular)

    # Scoring averages and win streaks are league records at the career level,
    # which is per person -- they are ranked from the owner stats, not here.

    # Who actually reached the bracket, by season. Yahoo's field has grown from
    # six teams to eight, so membership is read off the bracket rather than
    # assumed from a fixed seed cutoff.
    playoff_teams = {
        (row["year"], row["team"]) for row in log if row["phase"] == PHASE_PLAYOFF
    }
    # One record book per phase, the way the NBA keeps regular season, playoffs
    # and Finals apart. A 200-point January week is not a Finals record.
    playoff_rows = [row for row in log if row["phase"] == PHASE_PLAYOFF]
    books = {
        PHASE_REGULAR: single_game_leaders([r for r in log if r["phase"] == PHASE_REGULAR]),
        PHASE_PLAYOFF: single_game_leaders(playoff_rows),
        FINALS_ROUND: single_game_leaders(
            [row for row in playoff_rows if row["round"] == FINALS_ROUND]
        ),
        # Every game ever played, phase ignored: the outright league marks. Today
        # a regular-season game holds all six, but a playoff blowup can take one
        # at any time, which is exactly what this book is here to catch.
        BOOK_TOTAL: single_game_leaders(log),
    }
    return {
        "log": log,
        "teams": teams,
        "books": books,
        "playoff_teams": playoff_teams,
    }


def build_owner_game_stats(seasons: dict, owner_map: dict, matchup_stats: dict) -> dict:
    """Re-attribute the game log from franchises to the people who ran them."""
    owner_of = {}
    for year in sorted(seasons):
        for team in standings_teams(seasons[year]):
            owner = str(team.get("owner") or "").strip()
            if team.get("name") and owner:
                owner_of[(year, team["name"])] = canonical_owner(owner, owner_map)

    owners = {}
    for row in matchup_stats.get("log", []):
        owner = owner_of.get((row["year"], row["team"]))
        if not owner:
            continue
        record = owners.setdefault(
            owner,
            {
                "all": [],
                "regular": [],
                "playoff": [],
                "playoff_wins": 0,
                "playoff_losses": 0,
                "playoff_years": set(),
                "finals_years": set(),
                "head_to_head": {},
            },
        )
        record["all"].append(row)
        # Head-to-head between people, so a rivalry survives both sides renaming
        # their franchise. Every meeting counts, bracket games included.
        opponent_owner = owner_of.get((row["year"], row["opponent"]))
        if opponent_owner and opponent_owner != owner:
            add_head_to_head(record["head_to_head"], opponent_owner, opponent_owner, row)
        if row["phase"] == PHASE_REGULAR:
            record["regular"].append(row)
        elif row["phase"] == PHASE_PLAYOFF:
            record["playoff"].append(row)
            record["playoff_wins" if row["won"] else "playoff_losses"] += 1
            record["playoff_years"].add(row["year"])
            if row["round"] == FINALS_ROUND:
                record["finals_years"].add(row["year"])

    for record in owners.values():
        regular = record["regular"]
        record["best_week"] = max(regular, key=lambda r: r["score"], default=None)
        record["worst_week"] = min(regular, key=lambda r: r["score"], default=None)
        record["avg_score"] = (
            round(sum(r["score"] for r in regular) / len(regular), 2) if regular else 0.0
        )
        record["streak"] = _streak(regular)
        playoff = record["playoff"]
        record["playoff_avg"] = (
            round(sum(r["score"] for r in playoff) / len(playoff), 2) if playoff else 0.0
        )
        played = record["playoff_wins"] + record["playoff_losses"]
        record["playoff_wpct"] = record["playoff_wins"] / played if played else 0.0
        # Totals across every phase, consolation play included: these are games
        # that were really played, so they count toward a career total even
        # though they belong to neither record book.
        every = record["all"]
        record["total_games"] = len(every)
        record["total_wins"] = sum(1 for r in every if r["won"])
        record["total_ties"] = sum(1 for r in every if r["tied"])
        record["total_losses"] = (
            record["total_games"] - record["total_wins"] - record["total_ties"]
        )
        record["total_points"] = round(sum(r["score"] for r in every), 2)
        record["total_against"] = round(sum(r["opponent_score"] for r in every), 2)
        record["total_avg"] = (
            round(record["total_points"] / record["total_games"], 2) if every else 0.0
        )
        # A tie counts as half a win, the way the NFL rates one.
        record["total_wpct"] = (
            (record["total_wins"] + 0.5 * record["total_ties"]) / record["total_games"]
            if every
            else 0.0
        )
        record["total_streak"] = _streak(every)
    return owners


def build_season_records(seasons: dict, bible: dict) -> dict:
    """Best/worst single-season standings lines: points for and win percentage."""
    name_to_canonical = build_name_to_canonical(bible)
    entries = []
    for year in sorted(seasons):
        for team in standings_teams(seasons[year]):
            wins, losses = int(team.get("wins", 0)), int(team.get("losses", 0))
            games_played = wins + losses
            if not games_played:
                continue
            name = team.get("name", "Unknown")
            entries.append(
                {
                    "year": year,
                    "team": name_to_canonical.get(name, name),
                    "pf": float(team.get("points_for", 0) or 0),
                    "wins": wins,
                    "losses": losses,
                    "wpct": wins / games_played,
                }
            )
    if not entries:
        return {}
    # Each record is every entry tied at the extreme, not one arbitrary winner.
    return {
        "most_pf": top_holders(entries, lambda e: e["pf"]),
        "fewest_pf": top_holders(entries, lambda e: e["pf"], largest=False),
        "best_record": top_holders(entries, lambda e: (e["wpct"], e["wins"])),
        "worst_record": top_holders(entries, lambda e: (e["wpct"], e["wins"]), largest=False),
    }


def _mermaid_label(text: str) -> str:
    """Quote a team name for use as a Mermaid node label."""
    return '"' + str(text).replace('"', "'") + '"'


def _fmt_score(value) -> str:
    """Render a score the way Yahoo does: always two decimals."""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def real_bracket(bracket: dict, seeds: dict[str, int]) -> str:
    """Render the ACTUAL championship bracket from captured matchup data.

    `bracket["games"]` is derived by the scraper by walking back from the final,
    so it contains only games on the path to the title -- not the consolation
    games that share the same weeks and the same `is_playoffs` flag.

    Each game becomes one node showing both teams, their real scores, and the
    seed each entered with. Edges follow `advances_to`, so the diagram shows who
    actually beat whom rather than an assumed bracket shape. Teams with a first-
    round bye simply appear for the first time in a later round.
    """
    games = bracket.get("games") or []
    if not games:
        return ""

    def team_line(t: dict) -> str:
        name = t.get("name", "?")
        seed = seeds.get(name)
        prefix = f"({seed}) " if seed else ""
        mark = "✓ " if t.get("is_winner") else ""
        return f"{mark}{prefix}{name} {_fmt_score(t.get('score', 0))}"

    lines = ["```mermaid", "flowchart LR"]
    # Group by round so each round renders as a labelled subgraph, which is what
    # makes the diagram read as a bracket rather than a flat graph.
    order: list[str] = []
    by_round: dict[str, list[dict]] = {}
    for g in games:
        rnd = g.get("round", "Round")
        if rnd not in by_round:
            by_round[rnd] = []
            order.append(rnd)
        by_round[rnd].append(g)

    for rnd in order:
        lines.append(f'    subgraph {_mermaid_id(rnd)}["{rnd}"]')
        for g in by_round[rnd]:
            label = "<br>".join(team_line(t) for t in g.get("teams", []))
            lines.append(f'        {g["id"]}["{label}"]')
        lines.append("    end")

    for g in games:
        nxt = g.get("advances_to")
        if nxt:
            winner = next((t for t in g.get("teams", []) if t.get("is_winner")), None)
            # Quote the edge label: team names contain apostrophes, which break
            # an unquoted mermaid edge label.
            label = f'|{_mermaid_label(winner["name"])}|' if winner else ""
            lines.append(f'    {g["id"]} -->{label} {nxt}')

    # Terminal node for the title, so the champion is visually the endpoint.
    final = games[-1]
    champ = next((t for t in final.get("teams", []) if t.get("is_winner")), None)
    if champ:
        lines.append(f'    {final["id"]} --> CHAMP[{_mermaid_label("🏆 " + champ["name"])}]')

    lines.append("```")
    return "\n".join(lines)


def _mermaid_id(text: str) -> str:
    """Turn a round name into a safe mermaid node/subgraph id."""
    return "R" + re.sub(r"[^A-Za-z0-9]", "", str(text))


def playoff_bracket(seeded: list[tuple[int, str]], champion: str) -> str:
    """Render a SEEDING skeleton — the fallback when no real bracket is available.

    Only used for seasons with no captured matchup data. It shows the format, not
    what happened; `real_bracket` is preferred wherever the data exists.
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
# Yahoo's slot vocabulary, in the order a lineup card reads. Anything unknown
# sorts after the named slots but still above the bench.
ROSTER_SLOT_ORDER = [
    "QB", "RB", "WR", "TE", "W/R", "W/T", "W/R/T", "Q/W/R/T", "K", "DEF", "D/ST",
]
BENCH_SLOTS = {"BN", "IR"}


def roster_snapshot_weeks(season_data: dict) -> tuple:
    """(first, last) week that actually has rosters, or (None, None).

    Discovered, never assumed: 2018 ran weeks 3-16 while later seasons ran 1-17,
    and a mid-season week is empty if its harvest file was missing.
    """
    weeks = season_data.get("weeks") or {}
    have = sorted(int(w) for w, v in weeks.items() if (v or {}).get("rosters"))
    if not have:
        return (None, None)
    return (have[0], have[-1])


def roster_table(roster: dict) -> list[str]:
    """Markdown rows for one team's roster snapshot, starters first."""
    players = (roster or {}).get("players") or []

    def sort_key(player):
        slot = player.get("slot") or ""
        if slot in BENCH_SLOTS:
            rank = len(ROSTER_SLOT_ORDER) + 1
        elif slot in ROSTER_SLOT_ORDER:
            rank = ROSTER_SLOT_ORDER.index(slot)
        else:
            rank = len(ROSTER_SLOT_ORDER)
        # Within a slot, the bigger week takes the higher row.
        return (rank, -float(player.get("points") or 0.0), player.get("name") or "")

    rows = ["| Slot | Player | Pos | Pts |", "|------|--------|-----|-----|"]
    for player in sorted(players, key=sort_key):
        name = player.get("name")
        rows.append(
            f"| {player.get('slot') or '—'} "
            f"| {wikilink(name) if name else TBD} "
            f"| {player.get('position') or '—'} "
            f"| {_fmt_score(player.get('points'))} |"
        )
    return rows


def team_roster_blocks(season_data: dict, teams: list[dict]) -> str:
    """One collapsed admonition per team, holding both roster snapshots."""
    first, last = roster_snapshot_weeks(season_data)
    if first is None:
        return "_TBD — no roster data captured for this season._"

    weeks = season_data.get("weeks") or {}

    def roster_for(week, name):
        return ((weeks.get(str(week)) or {}).get("rosters") or {}).get(name)

    out: list[str] = []
    for team in teams:
        name = team.get("name") or "?"
        snapshots = [
            ("Post-draft", first, roster_for(first, name)),
            ("End of season", last, roster_for(last, name)),
        ]
        if not any(roster for _, _, roster in snapshots):
            continue
        out.append(f'??? note "{name}"')
        for label, week, roster in snapshots:
            if not roster:
                continue
            out.append(f"    **{label} — week {week}**")
            out.append("")
            out.extend("    " + line for line in roster_table(roster))
            out.append("")
    return "\n".join(out) if out else "_TBD — no roster data captured for this season._"


BUST_MAX_ROUND = 3


def weekly_score_awards(season_data: dict) -> tuple[str, str]:
    """Highest and lowest single-week team score. Needs no roster data."""
    scored = []
    for week_key, games in (season_data.get("matchups") or {}).items():
        for game in games:
            for side in game.get("teams") or []:
                if side.get("score") is None:
                    continue
                scored.append((float(side["score"]), side.get("name") or "?", int(week_key)))
    if not scored:
        return (TBD, TBD)
    high = max(scored)
    low = min(scored)
    return (
        f"{high[1]} — {_fmt_score(high[0])} (Wk {high[2]})",
        f"{low[1]} — {_fmt_score(low[0])} (Wk {low[2]})",
    )


def draft_value_awards(season_data: dict) -> tuple[str, str]:
    """Best Draft Pick and Biggest Bust, by draft-slot-versus-finish gap.

    Within each position, picks are ranked by draft order and players by season
    points. The gap is (draft rank) - (finish rank): positive means the player
    finished better than where they were taken. Best pick is the largest gap;
    bust is the smallest, restricted to the first three rounds so a late-round
    miss cannot win an award nobody would give it.

    Computed, not voted — and the season page prints the formula next to the
    result so it reads as arithmetic rather than a verdict.
    """
    picks = (season_data.get("draft") or {}).get("draft_results") or []
    totals = {}
    # Where the points were actually scored, which is not always the team that
    # drafted the player — a mid-season trade or waiver claim moves them.
    weeks_by_team = {}
    for week in (season_data.get("weeks") or {}).values():
        for team_name, roster in ((week or {}).get("rosters") or {}).items():
            for player in roster.get("players") or []:
                name = player.get("name")
                if not name:
                    continue
                totals[name] = totals.get(name, 0.0) + float(player.get("points") or 0.0)
                teams = weeks_by_team.setdefault(name, {})
                teams[team_name] = teams.get(team_name, 0) + 1
    if not picks or not totals:
        return (TBD, TBD)

    by_position = {}
    for pick in picks:
        position = pick.get("position") or ""
        if position and pick.get("player") in totals:
            by_position.setdefault(position, []).append(pick)

    # Order by the OVERALL pick. Yahoo's `pick` restarts every round, so sorting
    # on it would rank round 2 pick 1 ahead of round 1 pick 5 and invert the
    # draft order. `overall` is set by annotate_overall_picks at load.
    def pick_order(p) -> int:
        return int(p.get("overall") or p.get("pick") or 0)

    scored = []
    for position, position_picks in by_position.items():
        draft_order = sorted(position_picks, key=pick_order)
        finish_order = sorted(
            position_picks, key=lambda p: totals.get(p.get("player"), 0.0), reverse=True
        )
        draft_rank = {p["player"]: i for i, p in enumerate(draft_order, 1)}
        finish_rank = {p["player"]: i for i, p in enumerate(finish_order, 1)}
        for pick in position_picks:
            name = pick["player"]
            scored.append({
                "player": name,
                "position": position,
                "team": pick.get("team") or "?",
                "round": int(pick.get("round") or 0),
                "pick": pick_order(pick),
                "gap": draft_rank[name] - finish_rank[name],
                "points": totals.get(name, 0.0),
            })
    if not scored:
        return (TBD, TBD)

    def line(row) -> str:
        """Name the drafting team explicitly, and the roster the points came
        from when a trade or waiver claim moved the player mid-season."""
        rostered = weeks_by_team.get(row["player"]) or {}
        primary = max(rostered, key=lambda t: rostered[t], default="")
        where = ""
        if primary and primary != row["team"]:
            where = f", scored mostly for {wikilink(primary)}"
        return (
            f"{wikilink(row['player'])} ({row['position']}) — drafted by {wikilink(row['team'])} "
            f"at pick {row['pick']}, finished {row['gap']:+d} spots at the position, "
            f"{_fmt_score(row['points'])} pts{where}"
        )

    best = max(scored, key=lambda r: (r["gap"], r["points"]))
    early = [r for r in scored if 0 < r["round"] <= BUST_MAX_ROUND]
    if not early:
        return (line(best), TBD)
    bust = min(early, key=lambda r: (r["gap"], -r["points"]))
    return (line(best), line(bust))


def annotate_overall_picks(season_data: dict) -> None:
    """Add an `overall` field to each draft pick, in place.

    Yahoo numbers picks WITHIN the round: round 2 starts again at 1. What a draft
    board wants is the overall number — round 2 pick 1 of a 12-team league is the
    13th pick of the draft, not the 2nd. Ordering on the within-round number also
    inverts the draft order outright, ranking round 2 pick 1 ahead of round 1
    pick 5.

    Round size is the widest round in the season, since the last round can be
    short (a forfeited or auto-skipped pick); taking the short one would number
    every later round too low.
    """
    picks = (season_data.get("draft") or {}).get("draft_results") or []
    if not picks:
        return
    round_size = max((int(p.get("pick") or 0) for p in picks), default=0)
    if round_size <= 0:
        return
    for pick in picks:
        round_number = int(pick.get("round") or 0)
        within = int(pick.get("pick") or 0)
        if round_number <= 0 or within <= 0:
            continue
        pick["overall"] = (round_number - 1) * round_size + within


def backfill_draft_positions(season_data: dict) -> None:
    """Fill blank draft-pick positions from that season's roster data, in place.

    Yahoo's draft-results table never carried a position column, so every season
    shipped with `position: ""`. Rosters have it. Unmatched picks stay blank — an
    unrostered player's position is not in the captured data, and guessing it
    would be fabrication.
    """
    picks = (season_data.get("draft") or {}).get("draft_results") or []
    if not picks:
        return
    positions = {}
    for week in (season_data.get("weeks") or {}).values():
        for roster in ((week or {}).get("rosters") or {}).values():
            for player in roster.get("players") or []:
                name, position = player.get("name"), player.get("position")
                if name and position:
                    positions.setdefault(name, position)
    for pick in picks:
        if not pick.get("position"):
            pick["position"] = positions.get(pick.get("player"), "")


def apply_bible_positions(seasons: dict, bible: dict) -> None:
    """Fill the draft positions the rosters could not, from the bible, in place.

    `backfill_draft_positions` leaves a pick blank when the player never reached
    a captured weekly roster - drafted, then cut before week one. The bible's
    `player_positions` block is the hand-sourced fallback for exactly those, and
    it is applied second so captured data always wins over a typed value.
    """
    positions = bible.get("player_positions", {}) or {}
    if not positions:
        return
    for season_data in seasons.values():
        for pick in (season_data.get("draft") or {}).get("draft_results") or []:
            if not pick.get("position"):
                pick["position"] = str(positions.get(pick.get("player"), "") or "")


def roster_cell(year: int, season_data: dict) -> str:
    """Season-log cell: a link to the year's roster blocks, or _TBD_.

    Sixteen names will not fit in a table cell and there are no player pages, so
    the column's job is navigation.
    """
    first, _ = roster_snapshot_weeks(season_data)
    if first is None:
        return TBD
    return wikilink(f"{year} Season")


def gen_season(
    year: int, season_data: dict, bible: dict, aggregates: dict,
    mvp: list = (), finals: list = (), all_league: list = (),
    newcomer: list = (), undrafted: list = (), first_season: int = None,
) -> str:
    teams = standings_teams(season_data)
    owners = get_owners(bible)
    champion, runner_up, top_seed, toilet_bowl_winner = champ_fields(bible, year)

    rows = []
    seeded: list[tuple[int, str]] = []  # (seed, team name) for the bracket
    # Seeds are omitted per-team for non-qualifiers, so decide once per season
    # whether this data has real seeds at all before falling back to guessing.
    has_real_seeds = any(t.get("playoff_seed") for t in teams)
    for position, team in enumerate(sorted(teams, key=lambda x: int(x.get("rank", DEFAULT_RANK))), 1):
        rank = int(team.get("rank", position))
        team_name = team.get("name", "?")
        # Yahoo knows the owner of every team; the bible is only a fallback for
        # seasons captured before the v2 API path existed.
        owner = team.get("owner") or owners.get(team_name, "") or TBD
        wins = team.get("wins", 0)
        losses = team.get("losses", 0)
        points_for = team.get("points_for", "?")
        points_against = team.get("points_against", "?")
        # The real playoff seed, when the data has it. Falling back to the
        # standings position would be a guess: the seed a team entered the
        # playoffs with is frequently NOT its final finish (2018's champion was
        # the 5 seed and finished 1st).
        real_seed = team.get("playoff_seed")
        if real_seed:
            seed = real_seed
            seeded.append((int(real_seed), team_name))
        elif has_real_seeds:
            # This season HAS seed data, so a missing seed means the team simply
            # did not make the playoffs.
            seed = "—"
        elif position <= PLAYOFF_SEEDS:
            seed = position
            seeded.append((position, team_name))
        else:
            seed = "—"
        rows.append(
            f"| {rank} | {team_name} | {owner} | {wins}–{losses} | {points_for} | {points_against} | {seed} |"
        )

    # Prefer the real bracket derived from captured matchups; the seeding
    # skeleton is only a fallback for seasons with no matchup data.
    seeds_by_team = {
        t.get("name"): t.get("playoff_seed")
        for t in teams
        if t.get("name") and t.get("playoff_seed")
    }
    bracket = real_bracket(season_data.get("bracket") or {}, seeds_by_team)
    if not bracket:
        bracket = playoff_bracket(seeded, champion)

    roster_blocks = team_roster_blocks(season_data, teams)
    high_week, low_week = weekly_score_awards(season_data)
    best_pick, biggest_bust = draft_value_awards(season_data)

    # Every player is new in the league's first captured season, so the award
    # does not apply rather than being unrecorded.
    newcomer_cell = NA if year == first_season else season_mvp_cell(newcomer)

    # Flag the page as unfinished while the bible has no champion for the year.
    # `status` renders the badge configured in zensical.toml.
    status_line = "status: incomplete\n" if champion == TBD else ""

    md = f"""---
title: "{year} Season"
description: "Pine Hills Fantasy Football League — {year} season."
season: {year}
year: {year}
{status_line}---

# {year} Season

- **Champion:** {champion}
- **Runner-Up:** {runner_up}
- **Regular Season Top Seed:** {top_seed}
- **Toilet Bowl Winner:** {toilet_bowl_winner}

## Final Standings

> **Finish** is Yahoo's final playoff-adjusted rank, so it does not follow W-L order: a team can win the title from a lower seed. **Playoff Seed** is the seed the team entered the playoffs with; a dash means it did not qualify.

| Finish | Team | Owner | W–L | PF | PA | Playoff Seed |
|--------|------|-------|-----|----|----|--------------|
{chr(10).join(rows)}

## Playoff Bracket

> The actual championship bracket, from captured weekly matchups. Seeds in parentheses; ✓ marks the winner. Consolation games are excluded, and a team that appears first in a later round had a bye.

{bracket}

## Team Rosters

> Post-draft and end-of-season lineups as Yahoo recorded them. Bench and IR rows are included; points are that week's score.

{roster_blocks}

## Awards

- **League Champion:** {champion}
- **Most Valuable Player:** {season_mvp_cell(mvp)}
- **Finals MVP:** {finals_mvp_cell(finals)}
- **Newcomer of the Year:** {newcomer_cell}
- **Undrafted Player of the Year:** {season_mvp_cell(undrafted)}
- **Highest Single-Week Score:** {high_week}
- **Lowest Single-Week Score:** {low_week}
- **Best Draft Pick:** {best_pick}
- **Biggest Bust:** {biggest_bust}

## Team of the Season

The best starting lineup the season produced, one selection per slot the league actually starts. A slot is won the same way the MVP is: by wins swung, the games a team won by less than the player scored from the starting lineup. The flex takes the best eligible player the position slots did not already claim.

| Slot | Player | Pos | Wins Swung | Points in Them | Rostered By |
|------|--------|-----|------------|----------------|-------------|
{chr(10).join(team_of_the_season_rows(all_league))}

> Every award here is computed, not voted. **MVP** is the player who swung the most wins: games their team won by less than the player scored from the starting lineup. **Finals MVP** is the top scorer in the title game's winning lineup. **Newcomer of the Year** is the same wins-swung measure among players making their first appearance on a Pine Hills roster - a league debut, not an NFL rookie season, which the captured data does not record. **Undrafted Player of the Year** is the same measure among players nobody took in that year's draft. **Best Draft Pick** and **Biggest Bust** compare, within a position, where a player was taken against where they finished on season points; Bust is restricted to rounds 1-{BUST_MAX_ROUND}.

## The Story of the Year

_TBD — add the defining moments._

## Related

- {wikilink('Seasons')} · {wikilink(f'{year} Draft')} · {wikilink('Teams')} · {wikilink('Records')} · {wikilink('Lore')} · {wikilink('Playoffs')}
"""
    return md


def record_str(wins: int, losses: int, ties: int = 0) -> str:
    """W-L, or W-L-T when the league has actually tied one. Sports convention:
    the third number appears only when it is not zero."""
    return f"{wins}-{losses}-{ties}" if ties else f"{wins}-{losses}"


def streak_str(streak) -> str:
    """A win streak as "7 games (2021-2022)"."""
    length, first_year, last_year = streak or (0, None, None)
    if not length:
        return TBD
    span = str(first_year) if first_year == last_year else f"{first_year}-{last_year}"
    return f"{length} games ({span})"


def scoring_rows(game_stats: dict) -> list:
    """Best/worst week, scoring average and longest streak, as table rows.

    Shared by franchise and manager pages so both read the same way.
    """
    def week_cell(row):
        if not row:
            return TBD
        return f"{row['score']:.2f} ({game_when(row)})"

    average = game_stats.get("avg_score")
    average_cell = f"{average:.2f}" if average else TBD
    return [
        f"| Best Week | {week_cell(game_stats.get('best_week'))} |",
        f"| Worst Week | {week_cell(game_stats.get('worst_week'))} |",
        f"| Average (regular season) | {average_cell} |",
        f"| Longest Win Streak | {streak_str(game_stats.get('streak'))} |",
    ]


def franchise_titles(bible: dict, names) -> list:
    """Years this franchise won it all, matching any name it has gone by."""
    names = set(names or [])
    years = []
    for year, champ_data in get_champions(bible).items():
        if isinstance(champ_data, dict) and champ_data.get("champion") in names:
            years.append(int(year))
    return sorted(years)


def rivalry_rows(head_to_head: dict) -> list:
    """The opponents met most, as table rows.

    Every meeting counts, playoffs included. The phase split exists so a
    regular-season score cannot win a Finals record; a rivalry is the opposite
    case, where the bracket meetings are the ones that define it. The playoff
    column shows that split rather than hiding those games.
    """
    rows = []
    ranked = sorted(
        head_to_head.items(),
        key=lambda kv: (-(kv[1]["wins"] + kv[1]["losses"] + kv[1]["ties"]), kv[0].lower()),
    )
    for opponent, stats in ranked[:RIVALRY_ROWS]:
        meetings = stats["wins"] + stats["losses"] + stats["ties"]
        if meetings < MIN_RIVALRY_MEETINGS:
            continue
        def meeting(row) -> str:
            if not row:
                return TBD
            outcome = "T" if row["tied"] else ("W" if row["won"] else "L")
            return (
                f"{row['score']:.2f} - {row['opponent_score']:.2f} "
                f"({outcome}, {game_when(row)})"
            )

        rout, closest = meeting(stats["best"]), meeting(stats["closest"])
        postseason = (
            record_str(stats["playoff_wins"], stats["playoff_losses"])
            if stats["playoff_wins"] or stats["playoff_losses"]
            else "-"
        )
        rows.append(
            f"| {wikilink(stats['name'])} "
            f"| {record_str(stats['wins'], stats['losses'], stats['ties'])} "
            f"| {postseason} | {stats['pf']:.2f} / {stats['pa']:.2f} | {rout} | {closest} |"
        )
    return rows


def gen_team_page(
    name: str,
    years_data: list,
    bible: dict,
    aggregates: dict,
    owner_map: dict,
    matchup_stats: dict,
    seasons: dict,
) -> str:
    """Generate a franchise page.
    years_data: list of (year, wins, losses, rank, made_playoffs, owner).
    """
    owners = get_owners(bible)
    franchise_notes = (bible.get("franchise_notes", {}) or {}).get(name, {})
    joined_year = franchise_notes.get("joined", TBD) if isinstance(franchise_notes, dict) else TBD
    status = franchise_notes.get("status", "Active") if isinstance(franchise_notes, dict) else "Active"
    owner_name = owners.get(name, "") or ""
    owner = wikilink(canonical_owner(owner_name, owner_map)) if owner_name else TBD

    # Optional hand-supplied logo/photo. Emitted as Markdown so the path is
    # rewritten by the engine even if transform.py never promotes it into the
    # infobox; omitted entirely when the bible has no entry for this team.
    image_src = team_image_src(name, get_team_images(bible))
    image_line = f"- **Image:** ![{name}]({image_src})\n" if image_src else ""

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

    titles = franchise_titles(bible, (franchise_stats or {}).get("names", [name]))
    titles_str = f"{len(titles)} ({', '.join(str(y) for y in titles)})" if titles else "0"

    game_stats = matchup_stats.get("teams", {}).get(name, {})
    rivalries = rivalry_rows(game_stats.get("head_to_head", {})) or [
        f"| {TBD} | {TBD} | {TBD} | {TBD} | {TBD} | {TBD} |"
    ]
    playoff_wins = game_stats.get("playoff_wins", 0)
    playoff_losses = game_stats.get("playoff_losses", 0)
    playoff_record = f"{playoff_wins}-{playoff_losses}" if (playoff_wins or playoff_losses) else TBD
    # Appearances come from the bracket itself. build_aggregates now reads the
    # same bracket membership, so the fallback agrees rather than reverting to a
    # four-team cutoff this league outgrew.
    playoff_years = game_stats.get("playoff_years")
    appearances = (
        len(playoff_years)
        if playoff_years is not None
        else (franchise_stats["playoff_appears"] if franchise_stats else TBD)
    )
    scoring = scoring_rows(game_stats)

    rows = []
    for (year, wins, losses, rank, made_playoffs, _) in sorted(years_data, key=lambda x: x[0]):
        # Both cells point at the same place: the season page's roster blocks.
        # These previously linked to per-team roster pages the generator never
        # wrote, so every row shipped two dead links.
        roster_link = roster_cell(year, seasons.get(year) or {})
        rows.append(
            f"| {year} | {wins}–{losses} | {rank} | {'Yes' if made_playoffs else 'No'} | {roster_link} | {roster_link} | {TBD} |"
        )

    md = f"""---
title: "{name}"
description: "Franchise history for {name} in the Pine Hills Fantasy Football League."
---

# {name}

{image_line}- **Owner:** {owner}
- **Joined:** {joined_year}
- **Status:** {status}

## Franchise Summary

- **Championships:** {titles_str}
- **Regular-Season 1-Seeds:** {regular_season_titles}
- **Runner-Up Finishes (regular season):** {runner_up_finishes}
- **Playoff Appearances:** {appearances} / {franchise_stats['seasons_count'] if franchise_stats else TBD} seasons
- **Playoff Record:** {playoff_record}
- **All-Time Record:** {franchise_stats['wins'] if franchise_stats else TBD}–{franchise_stats['losses'] if franchise_stats else TBD} ({win_pct_str})
- **All-Time Points For / Against:** {pf_str} / {pa_str}

## Season Log

| Year | W–L | Finish | Playoffs? | Post-Draft Roster | End-of-Season Roster | Note |
|------|-----|--------|-----------|-------------------|----------------------|------|
{chr(10).join(rows)}

## Scoring

| Split | Value |
|-------|-------|
{chr(10).join(scoring)}

## Rivalries

Every meeting, playoffs included, most-played opponents first.

| Opponent | H2H Record | Playoffs | Points For / Against | Biggest Rout | Closest Meeting |
|----------|-----------|----------|----------------------|--------------|-----------------|
{chr(10).join(rivalries)}

## Signature Moments

_TBD._

## Related

- {wikilink('Teams')} · {wikilink('Owners')} · {wikilink('Seasons')} · {wikilink('Records')} · {wikilink('Lore')}
"""
    return md


def game_when(row: dict, tag: bool = True) -> str:
    """Where a game happened: "2019 Wk 5", plus a tag for non-regular play.

    Tables that are already scoped to one phase pass tag=False - repeating
    "(playoffs)" on every row of the playoff book says nothing.
    """
    return f"{row['year']} Wk {row['week']}" + (PHASE_LABELS[row["phase"]] if tag else "")


def game_line(row: dict) -> str:
    """A score with its opponent: "218.24 - 120.00 vs [[Roger That]]"."""
    return f"{row['score']:.2f} - {row['opponent_score']:.2f} vs {wikilink(row['opponent'])}"


def single_game_rows(book: dict, scope: str = "") -> list:
    """Render one phase's single-game record book as table rows.

    `scope` qualifies each label ("Playoff", "Finals") so a row lifted out of
    context still says which book it came from.
    """
    scope = f"{scope} " if scope else ""

    tag = not scope  # a scoped book already says which phase it covers

    def rows_for(label: str, key: str, value) -> list:
        """One table row per holder. A shared record is listed, not arbitrated:
        the first row says how many share it and the rest run under it."""
        holders = book.get(key) or []
        if not holders:
            return [f"| {label} | {TBD} | {TBD} | {TBD} |"]
        cells = shared_label_cells(label, len(holders))
        return [
            f"| {cell} | {wikilink(row['team'])} | {value(row)} "
            f"| {game_when(row, tag)} |"
            for cell, row in zip(cells, holders)
        ]

    def score_value(row) -> str:
        return game_line(row)

    def margin_value(row) -> str:
        return (
            f"{row['margin']:.2f} ({row['score']:.2f} - {row['opponent_score']:.2f} "
            f"vs {wikilink(row['opponent'])})"
        )

    table = []
    table += rows_for(f"Highest {scope}Score", "highest_score", score_value)
    table += rows_for(f"Lowest {scope}Score", "lowest_score", score_value)
    table += rows_for(f"Biggest {scope}Blowout", "blowout", margin_value)
    table += rows_for(f"Closest {scope}Game", "nailbiter", margin_value)
    table += rows_for(f"Most Points in a {scope}Loss", "most_points_in_loss", score_value)
    table += rows_for(f"Fewest Points in a {scope}Win", "fewest_points_in_win", score_value)
    # Ties are listed only when they exist: no "_TBD_" row for a thing that
    # simply has not happened.
    if book.get("ties"):
        table += [
            f"| {scope}Tie | {wikilink(row['team'])} | {row['score']:.2f} - "
            f"{row['opponent_score']:.2f} vs {wikilink(row['opponent'])} "
            f"| {game_when(row, tag)} |"
            for row in book["ties"]
        ]
    return table


# Career award tallies for the Records book. Newcomer of the Year is absent on
# purpose: a player can only ever debut once, so "most" is not a question.
AWARD_LEADERBOARDS = [
    ("Most MVP Awards", "mvp"),
    ("Most Finals MVP Awards", "finals"),
    ("Most Team of the Season Selections", "all_league"),
    ("Most Undrafted Player of the Year Awards", "undrafted"),
]


def award_leader_rows(player_awards: dict) -> list:
    """Career award leaders as table rows, one block per award.

    Reads the same per-player award record the player pages print, so a page and
    the leaderboard cannot disagree. Ties are labelled once and listed under it,
    the same way every shared record here is.
    """
    rows = []
    for label, key in AWARD_LEADERBOARDS:
        holders = top_holders(
            [
                {"player": player, "years": awards[key]}
                for player, awards in player_awards.items()
                if awards.get(key)
            ],
            lambda row: len(row["years"]),
        )
        # An award nobody has won twice has no leader: listing eight players
        # tied on one apiece says nothing the by-season table did not.
        if not holders or len(holders[0]["years"]) < 2:
            continue
        holders.sort(key=lambda row: (-len(row["years"]), row["player"]))
        cells = shared_label_cells(label, len(holders))
        rows.extend(
            f"| {cell} | {wikilink(row['player'])} | {len(row['years'])} "
            f"| {', '.join(str(year) for year in row['years'])} |"
            for cell, row in zip(cells, holders)
        )
    return rows


def gen_records_index(
    seasons: dict,
    bible: dict,
    matchup_stats: dict,
    season_records: dict,
    owner_aggregates: dict,
    owner_game_stats: dict,
    player_log: list,
    player_awards: dict = None,
) -> str:
    player_rows = player_book_rows(player_log)

    # single-season leaders, straight off the standings
    def season_row(label: str, key: str, value) -> str:
        entries = season_records.get(key) or []
        if not entries:
            return f"| {label} | {TBD} | {TBD} | {TBD} |"
        names = ", ".join(wikilink(entry["team"]) for entry in entries)
        years = ", ".join(str(entry["year"]) for entry in entries)
        return (
            f"| {shared_label(label, len(entries))} | {names} "
            f"| {value(entries[0])} | {years} |"
        )

    points = lambda e: f"{e['pf']:.2f}"  # noqa: E731
    record = lambda e: f"{e['wins']}-{e['losses']} ({e['wpct']*100:.1f}%)"  # noqa: E731
    season_rows = [
        season_row("Most Points For (season)", "most_pf", points),
        season_row("Fewest Points For (season)", "fewest_pf", points),
        season_row("Best Regular-Season Record", "best_record", record),
        season_row("Worst Regular-Season Record", "worst_record", record),
    ]

    # Regular-season single-game book. The playoff and Finals books live on the
    # Playoffs page, kept apart the way the NBA record book keeps them.
    game_rows = single_game_rows(matchup_stats["books"][PHASE_REGULAR])

    # Career leaders are per person. A franchise-keyed career record fragments a
    # serial renamer into eight short careers and flatters a two-season team.
    def career_row(label: str, holders, value) -> str:
        """One row naming every manager tied at the top of a record."""
        if not holders:
            return f"| {label} | {TBD} | {TBD} |"
        names = ", ".join(wikilink(owner) for owner, _ in sorted(holders))
        return f"| {shared_label(label, len(holders))} | {names} | {value(holders[0][1])} |"

    by_wins = top_holders(list(owner_aggregates.items()), lambda kv: kv[1]["wins"])
    by_streak = top_holders(
        [kv for kv in owner_game_stats.items() if kv[1]["streak"][0]],
        lambda kv: kv[1]["streak"][0],
    )
    # Averages need enough games behind them to mean anything.
    qualified = [
        kv for kv in owner_game_stats.items() if len(kv[1]["regular"]) >= MIN_GAMES_FOR_AVERAGE
    ]
    best_average = top_holders(qualified, lambda kv: kv[1]["avg_score"])
    worst_average = top_holders(qualified, lambda kv: kv[1]["avg_score"], largest=False)

    def margin_board(games: list) -> list:
        # Columns are neutral rather than Winner/Loser: a drawn game has
        # neither, and the score already says who came out ahead.
        return [
            f"| {row['margin']:.2f}{' (tie)' if row['tied'] else ''} "
            f"| {wikilink(row['team'])} | {row['score']:.2f} - "
            f"{row['opponent_score']:.2f} | {wikilink(row['opponent'])} | {game_when(row)} |"
            for row in games
        ] or [f"| {TBD} | {TBD} | {TBD} | {TBD} | {TBD} |"]

    log = matchup_stats.get("log", [])
    blowout_rows = margin_board(games_by_margin(log, BLOWOUT_MARGIN, above=True))
    nailbiter_rows = margin_board(games_by_margin(log, NAILBITER_MARGIN, above=False))

    # All-time totals: every game ever played, phase ignored. The split books
    # answer "best regular season" and "best postseason"; this answers "most,
    # full stop".
    total_rows = []
    for owner, stats in sorted(
        owner_game_stats.items(),
        key=lambda kv: (-kv[1]["total_wins"], kv[1]["total_losses"], kv[0].lower()),
    ):
        total_rows.append(
            f"| {wikilink(owner)} | {stats['total_games']} "
            f"| {record_str(stats['total_wins'], stats['total_losses'], stats['total_ties'])} "
            f"| {stats['total_wpct']*100:.1f}% "
            f"| {stats['total_points']:.2f} | {stats['total_against']:.2f} "
            f"| {stats['total_avg']:.2f} |"
        )
    if not total_rows:
        total_rows.append("| " + " | ".join([TBD] * 7) + " |")

    def average_value(stats) -> str:
        # The sample rides along with the rate: a thin one should be visible,
        # not quietly filtered out of the table.
        return f"{stats['avg_score']:.2f} pts/game ({len(stats['regular'])} games)"

    career_rows = [
        career_row("Most Career Wins", by_wins, lambda s: f"{s['wins']}-{s['losses']}"),
        career_row("Longest Win Streak", by_streak, lambda s: streak_str(s["streak"])),
        career_row("Best Scoring Average", best_average, average_value),
        career_row("Worst Scoring Average", worst_average, average_value),
    ]


    md = f"""---
title: Records
icon: lucide/chart-bar
description: All-time records, single-season feats, and dubious achievements of the Pine Hills Fantasy Football League.
---

# Records

League records across {len(seasons)} seasons and {len(matchup_stats.get('log', [])) // 2} captured matchups. Every mark on this page is regular season; postseason records are on {wikilink('Playoffs')}.

## Single-Season Records

| Record | Holder | Value | Year |
|--------|--------|-------|------|
{chr(10).join(season_rows)}

## Single-Game Records

| Record | Holder | Value | When |
|--------|--------|-------|------|
{chr(10).join(game_rows)}

## Career Records

Career totals follow the manager, not the franchise name. Rate marks qualify at {MIN_GAMES_FOR_AVERAGE} games, one full regular season, and carry their sample size.

| Record | Owner | Value |
|--------|-------|-------|
{chr(10).join(career_rows)}

## Outright Marks

Single-game marks across every phase. A mark that also appears in the regular-season book above is the outright record as well.

| Record | Holder | Value | When |
|--------|--------|-------|------|
{chr(10).join(single_game_rows(matchup_stats["books"][BOOK_TOTAL]))}

## Blowouts

Games decided by {BLOWOUT_MARGIN:.0f} points or more. Phase is tagged where it is not a regular-season week.

| Margin | Team | Score | Opponent | When |
|--------|------|-------|----------|------|
{chr(10).join(blowout_rows)}

## Nailbiters

Games decided by {NAILBITER_MARGIN:.0f} point or less, ties included.

| Margin | Team | Score | Opponent | When |
|--------|------|-------|----------|------|
{chr(10).join(nailbiter_rows)}

## All-Time Totals

Every game a manager has played, in all phases.

| Owner | Games | Record | Win% | Points For | Points Against | Avg |
|-------|-------|--------|------|------------|----------------|-----|
{chr(10).join(total_rows)}

## Players

> Keyed to the player rather than the manager or franchise, and regular season only; the playoff and Finals player books are on {wikilink('Playoffs')}. Bench marks count a player who scored while benched. Weeks rostered spans every phase, since it counts time on a roster rather than a result.

| Record | Player | Mark | When |
|--------|--------|------|------|
{chr(10).join(player_rows)}

## Player Awards

MVP, Finals MVP, Team of the Season, Newcomer of the Year and Undrafted Player of the Year, season by season and by career, are on {wikilink('Awards')}.

## Postseason

Championships, playoff and Finals single-game records, career playoff leaders and the per-manager ledger are on {wikilink('Playoffs')}.

## Related

- {wikilink('Seasons')} · {wikilink('Teams')} · {wikilink('Draft History')} · {wikilink('Lore')} · {wikilink('Champions')}
"""
    return md


def _year_range(years: list, latest_year=None) -> str:
    """Render a season span: "2018-present", "2019-2022", or "2020"."""
    if not years:
        return TBD
    first_year, last_year = min(years), max(years)
    if latest_year is not None and last_year == latest_year:
        return f"{first_year}-present"
    if first_year == last_year:
        return str(first_year)
    return f"{first_year}-{last_year}"


def gen_owner_page(
    owner: str, record: dict, latest_year, images: dict, game_stats: dict
) -> str:
    """Generate a manager page: career totals across every franchise they ran."""
    season_span = _year_range(record["years"], latest_year)
    status = "Active" if latest_year in record["years"] else "Former"
    win_pct_str = f"{record['wpct']*100:.1f}%"
    titles = record["titles"]
    titles_str = f"{len(titles)} ({', '.join(str(y) for y in titles)})" if titles else "0"
    best_rank, best_year = record["finishes"][0] if record["finishes"] else (TBD, TBD)
    playoff_wins = game_stats.get("playoff_wins", 0)
    playoff_losses = game_stats.get("playoff_losses", 0)
    playoff_record = f"{playoff_wins}-{playoff_losses}" if (playoff_wins or playoff_losses) else TBD
    playoff_years = game_stats.get("playoff_years")
    appearances = len(playoff_years) if playoff_years is not None else record["playoff_appears"]
    scoring = scoring_rows(game_stats)
    rivalries = rivalry_rows(game_stats.get("head_to_head", {})) or [
        f"| {TBD} | {TBD} | {TBD} | {TBD} | {TBD} | {TBD} |"
    ]

    season_rows = []
    for (year, team_name, _canonical, wins, losses, rank, made_playoffs) in record["rows"]:
        season_rows.append(
            f"| {year} | {wikilink(team_name)} | {wins}-{losses} | {rank} | {'Yes' if made_playoffs else 'No'} |"
        )

    franchise_rows = []
    for franchise in sorted(record["teams"].values(), key=lambda f: min(f["years"])):
        # A thumbnail here is the same opt-in bible entry the team page uses; the
        # cell is just the link when the franchise has no image.
        image_src = team_image_src(franchise["name"], images)
        thumb = f"![{franchise['name']}]({image_src}){{ .team-thumb }} " if image_src else ""
        franchise_rows.append(
            f"| {thumb}{wikilink(franchise['name'])} | {_year_range(franchise['years'], latest_year)} "
            f"| {franchise['wins']}-{franchise['losses']} |"
        )

    return f"""---
title: "{owner}"
description: "Career record and franchises of {owner} in the Pine Hills Fantasy Football League."
---

# {owner}

- **Franchises:** {len(record['teams'])}
- **Seasons:** {season_span}
- **Status:** {status}

## Career Summary

- **Championships:** {titles_str}
- **Playoff Appearances:** {appearances} / {record['seasons_count']} seasons
- **Playoff Record:** {playoff_record}
- **Best Finish:** {best_rank} ({best_year})
- **All-Time Record:** {record['wins']}-{record['losses']} ({win_pct_str})
- **All-Time Points For / Against:** {record['pf']:.2f} / {record['pa']:.2f}

## Scoring

| Split | Value |
|-------|-------|
{chr(10).join(scoring)}

## Franchises

| Team | Seasons | Record |
|------|---------|--------|
{chr(10).join(franchise_rows)}

## Rivalries

Head-to-head by manager rather than franchise, since either side may have renamed. Every meeting counts, playoffs included; most-played opponents first.

| Opponent | H2H Record | Playoffs | Points For / Against | Biggest Rout | Closest Meeting |
|----------|-----------|----------|----------------------|--------------|-----------------|
{chr(10).join(rivalries)}

## Season Log

| Year | Team | W-L | Finish | Playoffs? |
|------|------|-----|--------|-----------|
{chr(10).join(season_rows)}

## Related

- {wikilink('Owners')} · {wikilink('Teams')} · {wikilink('Seasons')} · {wikilink('Records')}
"""


def gen_owners_index(owner_aggregates: dict, latest_year) -> str:
    rows = []
    for owner, record in sorted(owner_aggregates.items(), key=lambda x: x[0].lower()):
        # Serial renamers run to eight franchises; listing all of them turns the
        # column into a wall of links, so the rest are left to the owner page.
        team_names = [
            f["name"] for f in sorted(record["teams"].values(), key=lambda f: min(f["years"]))
        ]
        franchises = more_list(
            [wikilink(name) for name in team_names], OWNER_INDEX_TEAMS_SHOWN
        )
        rows.append(
            f"| {wikilink(owner)} | {franchises} | {_year_range(record['years'], latest_year)} "
            f"| {record['wins']}-{record['losses']} | {record['wpct']*100:.1f}% | {len(record['titles'])} |"
        )

    return f"""---
title: Owners
icon: lucide/user
description: The managers of the Pine Hills Fantasy Football League and the franchises they have run.
---

# Owners

Every manager in league history. Career totals span every franchise a manager
has run, so renaming a team does not start a new record.

## Managers

| Owner | Franchises | Seasons | All-Time Record | Win% | Titles |
|-------|-----------|---------|-----------------|------|--------|
{chr(10).join(rows)}

## Related

- {wikilink('Teams')} · {wikilink('Players')} · {wikilink('Seasons')} · {wikilink('Records')} · {wikilink('Champions')}
"""


def player_week_label(row: dict) -> str:
    """When a roster-week happened: "2024 Wk 16 (Final)".

    The bracket round beats the phase tag when the game had one, the same rule
    the player book follows, so a Final reads as a Final rather than as a
    generic postseason week.
    """
    if row.get("round"):
        return f"{row['year']} Wk {row['week']} ({row['round']})"
    return f"{row['year']} Wk {row['week']}{PHASE_LABELS[row['phase']]}"


def player_best_week(row: dict, with_team: bool = True) -> str:
    """The best-week cell: score, when, and (optionally) for whom."""
    if row is None:
        return TBD
    bench = "" if row["started"] else " (benched)"
    when = player_week_label(row)
    if with_team:
        when = f"{when}, {wikilink(row['team'])}"
    return f"{row['points']:.2f}{bench} - {when}"


def player_draft_line(picks: list) -> str:
    """Summary line for the lead: how many times, and where they went first."""
    if not picks:
        return "Never drafted (added in-season)"
    first = picks[0]
    where = f"R{first['round']}" if first.get("round") else TBD
    if first.get("overall"):
        where += f" P{first['overall']}"
    return f"{len(picks)} (first: {first['year']} {where})"


def build_player_awards(
    season_mvps: dict, finals_mvps: dict, all_league: dict,
    newcomers: dict = None, undrafted_awards: dict = None,
) -> dict:
    """{player: {"mvp": [...], "finals": [...], "all_league": [...]}} by year.

    A player page that does not mention an MVP season or a team of the season
    selection is missing the most notable thing about it, so the awards are
    inverted here once rather than re-derived per page.
    """
    awards = {}
    selections = {
        year: [row for entry in selected for row in entry["holders"]]
        for year, selected in all_league.items()
    }
    newcomers = newcomers or {}
    undrafted_awards = undrafted_awards or {}
    for key, source in (
        ("mvp", season_mvps), ("finals", finals_mvps), ("all_league", selections),
        ("newcomer", newcomers), ("undrafted", undrafted_awards),
    ):
        for year, holders in source.items():
            for row in holders:
                awards.setdefault(row["player"], {}).setdefault(key, []).append(year)
    for player in awards:
        for key in awards[player]:
            awards[player][key].sort()
    return awards


def player_awards_line(awards: dict) -> str:
    """"MVP 2020, 2023 · Finals MVP 2024", or "" when the player has none."""
    parts = []
    for label, key in (
        ("MVP", "mvp"), ("Finals MVP", "finals"), ("Team of the Season", "all_league"),
        ("Newcomer of the Year", "newcomer"),
        ("Undrafted Player of the Year", "undrafted"),
    ):
        years = awards.get(key) or []
        if years:
            parts.append(f"{label} {', '.join(str(year) for year in years)}")
    return " · ".join(parts)


def gen_player_page(name: str, record: dict, latest_year, awards: dict = None) -> str:
    """Generate a player page: every fantasy roster this player has sat on.

    The table is the point of the page. A player who spent eight years on one
    roster and one who was churned by six managers look nothing alike here, and
    neither reads that way from a team page.
    """
    positions = player_positions(record) or [TBD]
    # Only players who actually won something carry the line; an empty
    # "Awards: -" on 590 pages would be noise.
    won = player_awards_line(awards or {})
    awards_line = f"{chr(10)}- **Awards:** {won}" if won else ""

    stints = sorted(
        record["stints"].values(), key=lambda s: (s["year"], -s["weeks"], s["team"])
    )
    stint_rows = [
        f"| {stint['year']} | {wikilink(stint['team'])} "
        f"| {wikilink(stint['owner']) if stint['owner'] else TBD} "
        f"| {'/'.join(player_positions(stint)) or '-'} "
        f"| {stint['weeks']} | {stint['starts']} | {stint['points']:.2f} "
        f"| {player_best_week(stint['best'], with_team=False)} |"
        for stint in stints
    ]
    draft_rows = [
        f"| {pick['year']} | {pick['round'] or TBD} | {pick['overall'] or TBD} "
        f"| {wikilink(pick['team']) if pick['team'] else TBD} |"
        for pick in record["drafts"]
    ]

    team_history = (
        "\n".join(
            [
                "| Season | Team | Owner | Pos | Weeks | Starts | Lineup Points | Best Week |",
                "|--------|------|-------|-----|-------|--------|---------------|-----------|",
            ]
            + stint_rows
        )
        if stint_rows
        # The six draft-only players: taken in a draft, cut before the first
        # captured roster. Saying so is more useful than an empty table.
        else "_Drafted, but never appeared on a captured weekly roster._"
    )
    draft_history = (
        "\n".join(
            ["| Year | Round | Overall | Drafted By |", "|------|-------|---------|------------|"]
            + draft_rows
        )
        if draft_rows
        else "_Never taken in a captured draft; added in-season every time._"
    )

    return f"""---
title: "{name}"
description: "Every Pine Hills fantasy roster {name} has appeared on, season by season."
---

# {name}

- **Position:** {" / ".join(positions)}
- **Seasons:** {_year_range(record["years"], latest_year)}
- **Fantasy Teams:** {len(record["teams"])}{awards_line}

## Career Summary

- **Weeks Rostered:** {record["weeks"]} ({record["starts"]} started)
- **Points in Lineup:** {record["points"]:.2f}
- **Points on the Bench:** {record["bench_points"]:.2f}
- **Best Week:** {player_best_week(record["best"])}
- **Times Drafted:** {player_draft_line(record["drafts"])}

## Team History

One row per franchise per season. Weeks counts roster spots rather than games
played; lineup points exclude weeks spent on the bench.

{team_history}

## Draft History

{draft_history}

## Related

- {wikilink('Players')} · {wikilink('Teams')} · {wikilink('Draft History')} · {wikilink('Records')}
"""


def gen_players_index(player_index: dict, latest_year) -> str:
    """Generate the players index: every player, grouped by position."""
    by_position = {}
    for name, record in player_index.items():
        primary = (player_positions(record) or ["Other"])[0]
        by_position.setdefault(primary, []).append(record)

    ordered = [p for p in POSITION_ORDER if p in by_position]
    ordered += sorted(p for p in by_position if p not in POSITION_ORDER)

    sections = []
    for position in ordered:
        rows = []
        # Most weeks rostered first: the players the league actually kept lead
        # their own section, and the one-week fill-ins fall to the bottom.
        for record in sorted(
            by_position[position], key=lambda r: (-r["weeks"], r["name"])
        ):
            team_names = sorted(record["teams"], key=lambda t: -record["teams"][t])
            shown = [wikilink(t) for t in team_names[:PLAYER_INDEX_TEAMS_SHOWN]]
            if len(team_names) > PLAYER_INDEX_TEAMS_SHOWN:
                shown.append(f"+{len(team_names) - PLAYER_INDEX_TEAMS_SHOWN} more")
            rows.append(
                f"| {wikilink(record['name'])} | {_year_range(record['years'], latest_year)} "
                f"| {len(record['teams'])} | {', '.join(shown) or TBD} "
                f"| {record['weeks']} | {record['starts']} | {record['points']:.2f} |"
            )
        sections.append(
            f"""### {position} ({len(rows)})

| Player | Seasons | Teams | Rostered By | Weeks | Starts | Lineup Points |
|--------|---------|-------|-------------|-------|--------|---------------|
{chr(10).join(rows)}"""
        )

    return f"""---
title: Players
icon: material/football
description: Every NFL player rostered in the Pine Hills Fantasy Football League, and the fantasy teams that held them.
---

# Players

Every player who has appeared on a league roster, drawn from the weekly roster
captures. A player page carries the franchises that held them, the seasons, weeks
rostered, and points scored in the lineup.

Weeks counts roster spots rather than games played: a player benched all season
still occupied one.

## Players by Position

{chr(10).join(f"{section}{chr(10)}" for section in sections)}
## Related

- {wikilink('Teams')} · {wikilink('Owners')} · {wikilink('Draft History')} · {wikilink('Records')}
"""


def gen_teams_index(aggregates: dict, bible: dict, owner_map: dict) -> str:
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

    images = get_team_images(bible)
    rows = []
    for canonical_name, franchise in sorted(aggregates.items(), key=lambda x: x[0].lower()):
        # pick a representative name (prefer the one that appears latest)
        representative_name = franchise["names"][-1]
        owner_name = owners.get(representative_name, "") or ""
        owner = wikilink(canonical_owner(owner_name, owner_map)) if owner_name else TBD
        year_range = _year_range(franchise["years"], latest_year)
        titles = championship_counts.get(representative_name, 0)
        # A thumbnail rides in the Team cell rather than a column of its own: an
        # extra column would be blank for every franchise with no image yet.
        image_src = team_image_src(representative_name, images)
        thumb = f"![{representative_name}]({image_src}){{ .team-thumb }} " if image_src else ""
        # The team name is the link; a separate "Page" column repeated it and
        # forced both columns to wrap to three lines each on narrow screens.
        rows.append(
            f"| {thumb}{wikilink(representative_name)} | {owner} | {year_range} | {titles} |"
        )

    md = f"""---
title: Teams
icon: lucide/users
description: Franchise histories and owners of the Pine Hills Fantasy Football League.
---

# Teams

Every franchise in league history, with its owner, seasons active, and titles won. A franchise page carries the season log and head-to-head records. Career totals that follow a manager across franchises are on {wikilink('Owners')}.

## Active & Historical Franchises

| Team | Owner | Seasons | Titles |
|------|-------|---------|--------|
{chr(10).join(rows)}

"""
    return md


def gen_seasons_index(seasons: dict, bible: dict, mvps: dict) -> str:
    rows = []
    for year in sorted(seasons, reverse=True):
        champion = champ_year(bible, year).get("champion") or TBD
        rows.append(
            f"| {wikilink(f'{year} Season', year)} | {champion} "
            f"| {season_mvp_cell(mvps.get(year, []))} |"
        )
    # include 2018/2019 placeholders if referenced
    md = f"""---
title: Seasons
icon: lucide/calendar
description: Year-by-year history of the Pine Hills Fantasy Football League.
---

# Seasons

Every completed season of the league, with its champion and MVP. A season page carries the final
standings, playoff bracket, draft board, weekly rosters and computed awards.

The MVP is the player who swung the most wins that season: games their team won by less than the
player scored from the starting lineup.

## Season Index

| Year | Champion | Most Valuable Player |
|------|----------|----------------------|
{chr(10).join(rows)}

"""
    return md


def gen_root_index(seasons: dict, bible: dict) -> list[str]:
    rows = []
    for year in sorted(seasons, reverse=True):
        champion, runner_up, top_seed, _ = champ_fields(bible, year)
        rows.append(f"| {year} | {champion} | {runner_up} | {top_seed} |")
    return rows


def gen_champions_page(seasons: dict, bible: dict, finals_mvps: dict) -> str:
    rows = []
    for year in sorted(seasons, reverse=True):
        champion, runner_up, top_seed, _ = champ_fields(bible, year)
        rows.append(
            f"| {wikilink(f'{year} Season', year)} | {champion} | {runner_up} | {top_seed} "
            f"| {finals_mvp_cell(finals_mvps.get(year, []))} |"
        )

    md = f"""---
title: Champions
icon: lucide/trophy
description: List of Pine Hills Fantasy Football League champions by season.
---

# Champions

Every champion in league history. The champion is the winner of the playoff bracket, not the
regular-season top seed. The Finals MVP is the top scorer in the title game's winning lineup.

| Year | Champion | Runner-Up | Regular Season Top Seed | Finals MVP |
|------|----------|-----------|-------------------------|------------|
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


def lore_entries(bible: dict, key: str) -> list:
    """The bible's lore entries of one kind, oldest first, junk dropped."""
    entries = (bible.get("lore", {}) or {}).get(key) or []
    entries = [entry for entry in entries if isinstance(entry, dict) and entry.get("title")]
    return sorted(entries, key=lambda entry: (entry.get("year") or 0, entry["title"]))


def lore_blocks(entries: list, empty: str) -> str:
    """Render lore entries as collapsible admonitions.

    One entry can be a sentence or six paragraphs, and a table would truncate
    the long ones while padding the short. A collapsed admonition per entry
    keeps the page scannable - the reader sees every title at once and opens the
    one they want.
    """
    if not entries:
        return empty
    out = []
    for entry in entries:
        year = entry.get("year")
        heading = f"{year} - {entry['title']}" if year else entry["title"]
        out.append(f'??? quote "{heading}"')
        out.append("")
        # Who it happened to, when the bible names them. Franchise and manager
        # names are linked, so a curse reads as part of that team's history.
        involved = entry.get("involved") or []
        if involved:
            names = ", ".join(wikilink(str(name)) for name in involved)
            out.append(f"    **Involved:** {names}")
            out.append("")
        for line in str(entry.get("story") or TBD).strip().splitlines():
            out.append(f"    {line}".rstrip())
        out.append("")
    return "\n".join(out)


def gen_lore_page(bible: dict) -> str:
    """Generate the Lore page from the bible's `lore` block.

    Lore is the one part of this wiki no scraper can produce: vetoed trades,
    curses, the reason a franchise is named what it is. The page is generated so
    it always exists and every `[[Lore]]` link resolves, but its content comes
    only from `raw/bible.yaml` - an empty block prints the invitation to fill it
    in, never an invented incident.
    """
    incidents = lore_entries(bible, "incidents")
    curses = lore_entries(bible, "curses")

    return f"""---
title: Lore
icon: lucide/scroll-text
description: Incidents, curses and infamous moments of the Pine Hills Fantasy Football League.
---

# Lore

League history the scoreboard does not record: disputed trades, curses, and
other incidents. Entries are community-contributed and none are derived from the
captured data.

## Incidents

{lore_blocks(incidents, "_No incidents recorded. Entries are added under `lore.incidents` in the league bible._")}

## Curses

{lore_blocks(curses, "_No curses recorded. Entries are added under `lore.curses` in the league bible._")}

## Related

- {wikilink('Seasons')} · {wikilink('Teams')} · {wikilink('Records')} · {wikilink('Champions')}
"""


def gen_awards_page(
    seasons: dict,
    season_mvps: dict,
    finals_mvps: dict,
    newcomers: dict,
    undrafted_awards: dict,
    all_league_teams: dict,
    player_awards: dict,
    first_season: int,
) -> str:
    """Generate the Awards page: every computed award, by season and by career.

    The season pages each hand out their own year's awards; this is the place
    the whole run can be read at once, which is the only way a repeat winner is
    visible at all.
    """
    season_rows = []
    for year in sorted(seasons, reverse=True):
        # Every player is new in the first captured season, so the newcomer
        # award does not apply rather than being unrecorded.
        newcomer = NA if year == first_season else season_mvp_cell(newcomers.get(year, []))
        season_rows.append(
            f"| {wikilink(f'{year} Season', year)} "
            f"| {season_mvp_cell(season_mvps.get(year, []))} "
            f"| {finals_mvp_cell(finals_mvps.get(year, []))} "
            f"| {newcomer} "
            f"| {season_mvp_cell(undrafted_awards.get(year, []))} |"
        )

    # One collapsed block per season: nine tables stacked flat would bury the
    # rest of the page, and the reader almost always wants one year.
    lineups = []
    for year in sorted(seasons, reverse=True):
        selected = all_league_teams.get(year) or []
        if not selected:
            continue
        lineups.append(f'??? note "{year}"')
        lineups.append("")
        lineups.append("    | Slot | Player | Pos | Wins Swung | Rostered By |")
        lineups.append("    |------|--------|-----|------------|-------------|")
        for entry in selected:
            extra = len(entry["holders"]) > entry.get("slots", 1)
            for index, row in enumerate(entry["holders"]):
                label = entry["slot"] if index == 0 else ""
                if index == 0 and extra:
                    label = f"{entry['slot']} ({len(entry['holders'])}-way tie)"
                teams = sorted(row["teams"], key=lambda team: -row["teams"][team])
                lineups.append(
                    f"    | {label} | {wikilink(row['player'])} | {row['position']} "
                    f"| {row['wins']} "
                    f"| {more_list([wikilink(t) for t in teams], PLAYER_BOOK_TEAMS_SHOWN)} |"
                )
        lineups.append("")

    career = award_leader_rows(player_awards or {})
    career_block = (
        "\n".join(
            ["| Award | Player | Won | Years |", "|-------|--------|-----|-------|"] + career
        )
        if career
        else "_No award has been won twice by the same player._"
    )

    return f"""---
title: Awards
icon: lucide/award
description: Every computed award in the Pine Hills Fantasy Football League, by season and by career.
---

# Awards

Every award the league hands out is computed from the captured data; none is
voted on. Four of the five rank players by *wins swung*: games their team won by
a smaller margin than the player scored from the starting lineup, so removing
the player from that lineup flips the result. Points piled up in losses win
nothing, and a bench week is not a lineup result.

- **Most Valuable Player.** The most wins swung in a season, league-wide.
- **Finals MVP.** The top scorer in the title game's winning lineup. One game
  leaves nothing to rank by wins, so this is the ordinary sporting definition.
- **Newcomer of the Year.** The most wins swung by a player in their first
  season on a Pine Hills roster. A league debut, not an NFL rookie season: the
  captured data records no NFL service time. The first captured season has no
  award, since every player in it is new.
- **Undrafted Player of the Year.** The most wins swung by a player nobody took
  in that year's draft.
- **Team of the Season.** Each starting slot goes to the player who swung the
  most wins playing it, in the lineup shape the league actually started that
  year.

Ties are listed rather than arbitrated.

## By Season

| Season | MVP | Finals MVP | Newcomer of the Year | Undrafted Player of the Year |
|--------|-----|------------|----------------------|------------------------------|
{chr(10).join(season_rows) if season_rows else f"| {TBD} | {TBD} | {TBD} | {TBD} | {TBD} |"}

## Team of the Season

{chr(10).join(lineups) if lineups else "_No selections recorded._"}

## Career Leaders

{career_block}

## Related

- {wikilink('Seasons')} · {wikilink('Players')} · {wikilink('Records')} · {wikilink('Champions')}
"""


def get_eras(bible: dict) -> list:
    """The league's eras from the bible, oldest first, unusable entries dropped."""
    eras = [
        era
        for era in (bible.get("eras") or [])
        if isinstance(era, dict) and era.get("first_season")
    ]
    return sorted(eras, key=lambda era: int(era["first_season"]))


def era_seasons(era: dict, latest_year=None) -> str:
    """An era's span: "2018-2025", or "2026-present" while it is still running."""
    first = int(era["first_season"])
    last = era.get("last_season")
    if last:
        return str(first) if int(last) == first else f"{first}-{int(last)}"
    if latest_year is not None and latest_year > first:
        return f"{first}-present"
    return f"{first}-present"


def gen_history_page(bible: dict, seasons: dict) -> str:
    """Generate the League History page from the bible's `eras` block.

    The platform a season ran on decides whether this wiki has data for it, so
    the eras are what explain the shape of everything else: why the record books
    start in 2018, and why a season the league has actually played may have no
    page. Nothing here is derived - an era is a fact about the league that no
    capture reports.
    """
    eras = get_eras(bible)
    captured = sorted(seasons)
    latest = max(captured) if captured else None

    rows = []
    for era in eras:
        first = int(era["first_season"])
        last = int(era["last_season"]) if era.get("last_season") else None
        in_wiki = [
            year for year in captured if year >= first and (last is None or year <= last)
        ]
        # What the wiki holds for the era, counted rather than claimed: an era
        # flagged `captured` whose seasons never landed still reads honestly.
        if in_wiki:
            held = f"{len(in_wiki)} seasons ({in_wiki[0]}-{in_wiki[-1]})"
        else:
            held = "None captured"
        rows.append(
            f"| {era.get('name') or TBD} | {era.get('platform') or TBD} "
            f"| {era_seasons(era, latest)} | {held} |"
        )
    if not rows:
        rows = [f"| {TBD} | {TBD} | {TBD} | {TBD} |"]

    notes = []
    for era in eras:
        note = str(era.get("note") or "").strip()
        if note:
            notes.append(f"**{era.get('name') or TBD}.** {note}")

    return f"""---
title: History
icon: lucide/milestone
description: The eras of the Pine Hills Fantasy Football League and the platforms it has run on.
---

# History

The league has not run on one platform throughout, and which platform a season
ran on decides what this wiki can say about it. Every page here is derived from
data captured off the platform of its era; a season the league has played but
nobody has captured has no page.

## Eras

| Era | Platform | Seasons | In This Wiki |
|-----|----------|---------|--------------|
{chr(10).join(rows)}

{(chr(10) + chr(10)).join(notes) if notes else ""}

## Related

- {wikilink('Seasons')} · {wikilink('Teams')} · {wikilink('Records')} · {wikilink('Lore')}
"""


def gen_draft_index(seasons: dict, bible: dict, decisive: dict) -> str:
    rows = []
    for year in sorted(seasons, reverse=True):
        season_data = seasons[year] if isinstance(seasons, dict) else {}
        picks = (season_data.get("draft") or {}).get("draft_results") or []
        rows.append(
            f"| {wikilink(f'{year} Draft', year)} | {len(picks) or TBD} "
            f"| {top_draft_contributor(year, season_data, decisive)} |"
        )
    md = f"""---
title: Draft History
icon: lucide/target
description: Every draft in Pine Hills history, pick by pick.
---

# Draft History

Every league draft by year. A draft page lists the full board, pick by pick.

The last column names the player from that draft who swung the most wins: games their team won
by less than the player scored from the starting lineup. A season's MVP is the same measure taken
across every player, drafted or not, and is listed on {wikilink('Seasons')}.

## Drafts by Year

| Draft | Picks | Most Wins Swung |
|-------|-------|-----------------|
{chr(10).join(rows)}

"""
    return md


def playoff_field_sizes(matchup_stats: dict) -> dict:
    """Teams that reached the bracket, per season, read off the bracket itself."""
    sizes = {}
    for year, _name in matchup_stats.get("playoff_teams", set()):
        sizes[year] = sizes.get(year, 0) + 1
    return sizes


def gen_playoffs_page(
    seasons: dict,
    bible: dict,
    matchup_stats: dict,
    owner_aggregates: dict,
    owner_game_stats: dict,
    player_log: list,
) -> str:
    sizes = playoff_field_sizes(matchup_stats)
    books = matchup_stats["books"]

    # Postseason player books live here, next to the team ones, rather than on
    # Records — Records is the regular-season book. The log is passed in rather
    # than built here: this function's first parameter is named `seasons` but is
    # handed a list of years, so it has no season data of its own to read.
    playoff_player_rows = player_book_rows(player_log, PHASE_PLAYOFF)
    finals_player_rows = player_book_rows(player_log, FINALS_ROUND)

    # Titles belong to the person, not the franchise name they were flying that
    # year: lokesh's two came under one team, Naren's franchises change yearly.
    champ_rows = []
    titled_owners = [
        (owner, record["titles"])
        for owner, record in owner_aggregates.items()
        if record.get("titles")
    ]
    for owner, years in sorted(titled_owners, key=lambda x: (-len(x[1]), x[0].lower())):
        teams_won = sorted(
            {row[1] for row in owner_aggregates[owner]["rows"] if row[0] in years}
        )
        champ_rows.append(
            f"| {wikilink(owner)} | {len(years)} | {', '.join(str(y) for y in years)} "
            f"| {', '.join(wikilink(t) for t in teams_won)} |"
        )
    if not champ_rows:
        champ_rows.append(f"| {TBD} | 0 | {TBD} | {TBD} |")

    # The per-manager postseason ledger. A résumé follows the person through
    # every rename, so it is keyed to the owner rather than the franchise.
    ledger_rows = []
    for owner, stats in sorted(
        owner_game_stats.items(),
        key=lambda kv: (-kv[1]["playoff_wins"], kv[1]["playoff_losses"], kv[0].lower()),
    ):
        if not (stats["playoff_wins"] or stats["playoff_losses"]):
            continue
        titles = owner_aggregates.get(owner, {}).get("titles", [])
        ledger_rows.append(
            f"| {wikilink(owner)} | {stats['playoff_wins']}-{stats['playoff_losses']} "
            f"| {stats['playoff_wpct']*100:.1f}% | {len(stats['playoff_years'])} "
            f"| {len(stats['finals_years'])} | {len(titles)} | {stats['playoff_avg']:.2f} |"
        )
    if not ledger_rows:
        ledger_rows.append("| " + " | ".join([TBD] * 7) + " |")

    def career_playoff_row(label: str, holders, value) -> str:
        """One row naming every manager tied at the top of a record."""
        if not holders:
            return f"| {label} | {TBD} | {TBD} |"
        names = ", ".join(wikilink(owner) for owner, _ in sorted(holders))
        return f"| {shared_label(label, len(holders))} | {names} | {value(holders[0][1])} |"

    contenders = [kv for kv in owner_game_stats.items() if kv[1]["playoff_years"]]
    by_playoff_wins = top_holders(contenders, lambda kv: kv[1]["playoff_wins"])
    by_appearances = top_holders(contenders, lambda kv: len(kv[1]["playoff_years"]))
    by_finals = top_holders(contenders, lambda kv: len(kv[1]["finals_years"]))
    # A win rate needs a real sample: one lucky quarterfinal is not a record.
    rated = [
        kv
        for kv in contenders
        if kv[1]["playoff_wins"] + kv[1]["playoff_losses"] >= MIN_PLAYOFF_GAMES_FOR_RATE
    ]
    by_rate = top_holders(rated, lambda kv: kv[1]["playoff_wpct"])
    by_playoff_average = top_holders(rated, lambda kv: kv[1]["playoff_avg"])
    titled = top_holders(
        [kv for kv in owner_aggregates.items() if kv[1].get("titles")],
        lambda kv: len(kv[1]["titles"]),
    )

    career_rows = [
        career_playoff_row(
            "Most Playoff Wins",
            by_playoff_wins,
            lambda s: record_str(s["playoff_wins"], s["playoff_losses"]),
        ),
        career_playoff_row("Most Appearances", by_appearances, lambda s: len(s["playoff_years"])),
        career_playoff_row("Most Finals", by_finals, lambda s: len(s["finals_years"])),
        career_playoff_row(
            "Best Win%",
            by_rate,
            lambda s: f"{s['playoff_wpct']*100:.1f}% ({record_str(s['playoff_wins'], s['playoff_losses'])})",
        ),
        career_playoff_row(
            "Best Scoring Average",
            by_playoff_average,
            lambda s: f"{s['playoff_avg']:.2f} pts/game ({len(s['playoff'])} games)",
        ),
        career_playoff_row("Most Titles", titled, lambda s: len(s["titles"])),
    ]
    if sizes:
        earliest, latest = min(sizes), max(sizes)
        field = (
            f"{sizes[earliest]} teams"
            if sizes[earliest] == sizes[latest]
            else f"{sizes[earliest]} teams in {earliest}, {sizes[latest]} in {latest}"
        )
    else:
        field = TBD

    md = f"""---
title: Playoffs
icon: lucide/swords
description: Pine Hills Fantasy Football League playoff format, champions, and Finals history.
---

# Playoffs

The league postseason. The title is decided by the bracket: the regular-season top seed is champion only by winning it.

## Format

- **Qualifiers:** {field}. The field has not been constant, so bracket membership is read from each season's captured bracket rather than assumed from a seed cutoff.
- **Champion:** determined by the playoff bracket, not regular-season standing.
- **Consolation (Toilet Bowl):** contested by non-qualifiers.

## Field by Year

| Year | Playoff Teams | Champion |
|------|---------------|----------|
"""
    for year in sorted(seasons, reverse=True):
        champion, _, _, _ = champ_fields(bible, year)
        md += f"| {wikilink(f'{year} Season', str(year))} | {sizes.get(year, TBD)} | {champion} |\n"

    md += f"""
## All-Time Championships

Titles follow the manager, not the franchise name.

| Owner | Titles | Years | Won With |
|-------|--------|-------|----------|
{chr(10).join(champ_rows)}

## Playoff Records

Bracket games only. Regular-season records are on {wikilink('Records')}.

| Record | Holder | Value | When |
|--------|--------|-------|------|
{chr(10).join(single_game_rows(books[PHASE_PLAYOFF], "Playoff"))}

## Finals Records

The title game only.

| Record | Holder | Value | When |
|--------|--------|-------|------|
{chr(10).join(single_game_rows(books[FINALS_ROUND], "Finals"))}

## Playoff Player Records

Keyed to the player rather than the manager. Bracket games only; consolation play runs in the same weeks and is excluded. Each mark names the franchise that had the player rostered. The regular-season player book is on {wikilink('Records')}.

| Record | Player | Mark | When |
|--------|--------|------|------|
{chr(10).join(playoff_player_rows)}

## Finals Player Records

The title game only.

| Record | Player | Mark | When |
|--------|--------|------|------|
{chr(10).join(finals_player_rows)}

## Career Playoff Leaders

By manager. Rate marks qualify at {MIN_PLAYOFF_GAMES_FOR_RATE} playoff games, one full bracket run, and carry their sample size.

| Record | Owner | Value |
|--------|-------|-------|
{chr(10).join(career_rows)}

## Playoff Ledger

Every manager who has reached a bracket. Consolation play is excluded.

| Owner | Record | Win% | Appearances | Finals | Titles | Avg |
|-------|--------|------|-------------|--------|--------|-----|
{chr(10).join(ledger_rows)}

## Champions by Year

| Year | Champion | Runner-Up | Season |
|------|----------|-----------|--------|
"""
    for year in sorted(seasons, reverse=True):
        champion, runner_up, _, _ = champ_fields(bible, year)
        md += f"| {year} | {champion} | {runner_up} | {wikilink(f'{year} Season')} |\n"

    md += f"""

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
    # Champions come from Yahoo's final rank where we have it; the bible is only
    # the fallback for seasons the scraper could not derive.
    bible = apply_derived_champions(bible, seasons)
    bible = apply_derived_owners(bible, seasons)
    # Draft positions the rosters could not fill: the players cut before week one.
    apply_bible_positions(seasons, bible)

    (CONTENT / "seasons").mkdir(parents=True, exist_ok=True)
    (CONTENT / "teams").mkdir(parents=True, exist_ok=True)
    (CONTENT / "owners").mkdir(parents=True, exist_ok=True)
    (CONTENT / "players").mkdir(parents=True, exist_ok=True)
    (CONTENT / "draft").mkdir(parents=True, exist_ok=True)
    (CONTENT / "records").mkdir(parents=True, exist_ok=True)

    first_captured = min(seasons)
    owner_map = build_owner_map(bible, seasons)
    # The matchup log has to come first: bracket membership is what tells both
    # the franchise and the owner aggregates who actually made the playoffs.
    matchup_stats = build_matchup_stats(seasons, bible)
    aggregates = build_aggregates(seasons, matchup_stats["playoff_teams"])
    owner_aggregates = build_owner_aggregates(
        seasons, bible, owner_map, matchup_stats["playoff_teams"]
    )
    season_records = build_season_records(seasons, bible)
    # One pass over every roster row, shared by the Records and Playoffs books.
    player_log = build_player_log(seasons)
    player_index = build_player_index(seasons, player_log, owner_map)
    # MVP awards: one pass over the roster weeks joined to the matchup log, then
    # sliced per season for the pages that name a winner.
    decisive_wins = build_decisive_wins(player_log, matchup_stats["log"])
    season_mvps = {year: season_mvp(year, decisive_wins) for year in seasons}
    finals_mvps = {
        year: finals_mvp(year, player_log, matchup_stats["log"]) for year in seasons
    }
    all_league_teams = {
        year: team_of_the_season(year, seasons[year], decisive_wins) for year in seasons
    }
    debuts = league_debut_years(player_log)
    newcomers = {
        year: newcomer_of_the_year(year, decisive_wins, debuts, first_captured)
        for year in seasons
    }
    undrafted_awards = {
        year: undrafted_player_of_the_year(year, seasons[year], decisive_wins)
        for year in seasons
    }
    player_awards = build_player_awards(
        season_mvps, finals_mvps, all_league_teams, newcomers, undrafted_awards
    )
    owner_game_stats = build_owner_game_stats(seasons, owner_map, matchup_stats)
    print(f"  scanned {len(matchup_stats['log']) // 2} matchups")

    # per-team season data for team pages
    team_years = {}  # canon -> list of (year, w, l, rank, po, owner)
    owners = get_owners(bible)

    for year in sorted(seasons):
        d = seasons[year]
        # season page
        sp = CONTENT / "seasons" / f"{year}-season.md"
        sp.write_text(
            dash_normalize(
                gen_season(
                    year, d, bible, aggregates,
                    season_mvps.get(year, []), finals_mvps.get(year, []),
                    all_league_teams.get(year, []),
                    newcomers.get(year, []), undrafted_awards.get(year, []),
                    first_captured,
                )
            )
        )
        print(f"  wrote {sp.relative_to(ROOT)}")

        # team pages data
        for t in standings_teams(d):
            name = t.get("name", "Unknown")
            w = int(t.get("wins", 0))
            l = int(t.get("losses", 0))
            rank = int(t.get("rank", DEFAULT_RANK))
            po = made_playoffs(year, name, rank, matchup_stats["playoff_teams"])
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
                        # The column is "Overall", so print the overall number:
                        # Yahoo's `pick` restarts at 1 every round.
                        f"| {p.get('overall', p.get('pick','?'))} | {p.get('round','?')} | {p.get('team','?')} "
                        f"| {wikilink(p['player']) if p.get('player') else '?'} | {p.get('position','?')} |"
                    )
        dp = CONTENT / "draft" / f"{year}-draft.md"
        dp.write_text(
            dash_normalize(
                f"---\ntitle: \"{year} Draft\"\ndescription: \"Pine Hills FF {year} draft board.\"\n---\n\n"
                f"# {year} Draft\n\n" + "\n".join(dlines) +
                f"\n\n## Related\n\n- {wikilink('Draft History')} · {wikilink(f'{year} Season')}\n"
            )
        )
        print(f"  wrote {dp.relative_to(ROOT)}")

    # team pages
    for name, ydata in team_years.items():
        tp = CONTENT / "teams" / f"{slug(name)}.md"
        tp.write_text(dash_normalize(gen_team_page(name, ydata, bible, aggregates, owner_map, matchup_stats, seasons)))
        print(f"  wrote {tp.relative_to(ROOT)}")

    all_years = sorted(seasons.keys())
    latest_year = max(all_years) if all_years else None

    # owner (manager) pages
    images = get_team_images(bible)
    for owner, record in owner_aggregates.items():
        op = CONTENT / "owners" / f"{slug(owner)}.md"
        op.write_text(dash_normalize(gen_owner_page(owner, record, latest_year, images, owner_game_stats.get(owner, {}))))
        print(f"  wrote {op.relative_to(ROOT)}")

    oip = CONTENT / "owners" / "index.md"
    oip.write_text(dash_normalize(gen_owners_index(owner_aggregates, latest_year)))
    print(f"  wrote {oip.relative_to(ROOT)}")

    # player pages — one per player ever rostered (or drafted and cut)
    for player_name, record in player_index.items():
        pp = CONTENT / "players" / f"{slug(player_name)}.md"
        pp.write_text(
            dash_normalize(
                gen_player_page(
                    player_name, record, latest_year, player_awards.get(player_name, {})
                )
            )
        )
    print(f"  wrote {len(player_index)} pages -> {(CONTENT / 'players').relative_to(ROOT)}")

    pip = CONTENT / "players" / "index.md"
    pip.write_text(dash_normalize(gen_players_index(player_index, latest_year)))
    print(f"  wrote {pip.relative_to(ROOT)}")

    # records index
    rp = CONTENT / "records" / "index.md"
    rp.write_text(dash_normalize(gen_records_index(seasons, bible, matchup_stats, season_records, owner_aggregates, owner_game_stats, player_log, player_awards)))
    print(f"  wrote {rp.relative_to(ROOT)}")

    # teams index
    tip = CONTENT / "teams" / "index.md"
    tip.write_text(dash_normalize(gen_teams_index(aggregates, bible, owner_map)))
    print(f"  wrote {tip.relative_to(ROOT)}")

    # seasons index
    sip = CONTENT / "seasons" / "index.md"
    sip.write_text(dash_normalize(gen_seasons_index(seasons, bible, season_mvps)))
    print(f"  wrote {sip.relative_to(ROOT)}")

    # draft index (scoped to real years — avoids broken links to 2018/2019)
    dip = CONTENT / "draft" / "index.md"
    dip.write_text(dash_normalize(gen_draft_index(seasons, bible, decisive_wins)))
    print(f"  wrote {dip.relative_to(ROOT)}")

    # champions + playoffs (NBA-style)
    ap = CONTENT / "awards.md"
    ap.write_text(
        dash_normalize(
            gen_awards_page(
                seasons, season_mvps, finals_mvps, newcomers, undrafted_awards,
                all_league_teams, player_awards, first_captured,
            )
        )
    )
    print(f"  wrote {ap.relative_to(ROOT)}")

    hp = CONTENT / "history.md"
    hp.write_text(dash_normalize(gen_history_page(bible, seasons)))
    print(f"  wrote {hp.relative_to(ROOT)}")

    lp = CONTENT / "lore.md"
    lp.write_text(dash_normalize(gen_lore_page(bible)))
    print(f"  wrote {lp.relative_to(ROOT)}")

    cp = CONTENT / "champions.md"
    cp.write_text(dash_normalize(gen_champions_page(seasons, bible, finals_mvps)))
    print(f"  wrote {cp.relative_to(ROOT)}")
    pp = CONTENT / "playoffs.md"
    pp.write_text(dash_normalize(gen_playoffs_page(all_years, bible, matchup_stats, owner_aggregates, owner_game_stats, player_log)))
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
                if line.startswith("## Explore"):
                    out.extend(rows)
                    out.append("")
                out.append(line)
        root.write_text(dash_normalize("\n".join(out) + "\n"))
        print(f"  updated {root.relative_to(ROOT)} (champions table)")

    print("Done generating Markdown.")


if __name__ == "__main__":
    main()
