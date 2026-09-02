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
# Franchises listed inline in the owners table before it spills to "+N more".
OWNER_INDEX_TEAMS_SHOWN = 3


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


def player_book_rows(player_log: list) -> list[str]:
    """The five player books as table rows.

    Ties are listed and marked, never arbitrated — the same rule the team books
    follow. Bench marks read the whole log; every other book reads starters only,
    since a benched score is not a lineup result.
    """
    started = [row for row in player_log if row["started"]]

    def holders_rows(label, items, key, value, when) -> list[str]:
        holders = top_holders(items, key)
        if not holders:
            return [f"| {label} | {TBD} | {TBD} | {TBD} |"]
        shared = " (tied)" if len(holders) > 1 else ""
        return [
            f"| {label}{shared} | {row['player']} | {value(row)} | {when(row)} |"
            for row in holders
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
        names = [wikilink(t) for t in row["teams"]]
        if len(names) <= 3:
            return ", ".join(names)
        return f"{', '.join(names[:3])} +{len(names) - 3} more"

    table = []
    table += holders_rows(
        "Highest Regular-Season Week",
        [r for r in started if r["phase"] == PHASE_REGULAR],
        lambda r: r["points"], points_value, week_when,
    )
    table += holders_rows(
        "Highest Playoff Week",
        [r for r in started if r["phase"] == PHASE_PLAYOFF],
        lambda r: r["points"], points_value, week_when,
    )
    table += holders_rows(
        "Highest Season Total", totals,
        lambda r: r["points"],
        lambda r: f"{r['points']:.2f}",
        lambda r: f"{r['year']}, {wikilink(r['team'])}",
    )
    table += holders_rows(
        "Highest-Scoring Benched Player",
        [r for r in player_log if not r["started"]],
        lambda r: r["points"], points_value, week_when,
    )
    table += holders_rows(
        "Most Weeks Rostered", weeks_rows,
        lambda r: r["weeks"],
        lambda r: f"{r['weeks']} weeks",
        teams_when,
    )
    return table


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
        rows.append(
            f"| {player.get('slot') or '—'} "
            f"| {player.get('name') or TBD} "
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

    scored = []
    for position, position_picks in by_position.items():
        draft_order = sorted(position_picks, key=lambda p: int(p.get("pick") or 0))
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
                "pick": int(pick.get("pick") or 0),
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
            f"{row['player']} ({row['position']}) — drafted by {wikilink(row['team'])} "
            f"at pick {row['pick']}, finished {row['gap']:+d} spots at the position, "
            f"{_fmt_score(row['points'])} pts{where}"
        )

    best = max(scored, key=lambda r: (r["gap"], r["points"]))
    early = [r for r in scored if 0 < r["round"] <= BUST_MAX_ROUND]
    if not early:
        return (line(best), TBD)
    bust = min(early, key=lambda r: (r["gap"], -r["points"]))
    return (line(best), line(bust))


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


def roster_cell(year: int, season_data: dict) -> str:
    """Season-log cell: a link to the year's roster blocks, or _TBD_.

    Sixteen names will not fit in a table cell and there are no player pages, so
    the column's job is navigation.
    """
    first, _ = roster_snapshot_weeks(season_data)
    if first is None:
        return TBD
    return wikilink(f"{year} Season")


def gen_season(year: int, season_data: dict, bible: dict, aggregates: dict) -> str:
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

> Auto-generated from Yahoo. **Finish** is Yahoo's final playoff-adjusted rank, so it does not follow W–L order — a team can win the title from a lower seed. **Playoff Seed** is the seed the team actually entered the playoffs with; — means it did not qualify.

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

- 🏆 **League Champion:** {champion}
- 💥 **Highest Single-Week Score:** {high_week}
- 📉 **Lowest Single-Week Score:** {low_week}
- 🔥 **Biggest Bust:** {biggest_bust}
- 🎯 **Best Draft Pick:** {best_pick}
- 🍗 **"Poultry Controversy" Nominee:** {TBD}

> Best Draft Pick and Biggest Bust are computed, not voted: within each position, the gap between where a player was drafted and where they finished on season points. Bust is restricted to rounds 1-{BUST_MAX_ROUND}.

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

# 🏈 {name}

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
        """One table row per holder. A shared record is listed, not arbitrated,
        with "(tied)" on each line so the sharing is obvious."""
        holders = book.get(key) or []
        if not holders:
            return [f"| {label} | {TBD} | {TBD} | {TBD} |"]
        shared = " (tied)" if len(holders) > 1 else ""
        return [
            f"| {label}{shared} | {wikilink(row['team'])} | {value(row)} "
            f"| {game_when(row, tag)} |"
            for row in holders
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


def gen_records_index(
    seasons: dict,
    bible: dict,
    matchup_stats: dict,
    season_records: dict,
    owner_aggregates: dict,
    owner_game_stats: dict,
) -> str:
    player_rows = player_book_rows(build_player_log(seasons))

    # single-season leaders, straight off the standings
    def season_row(label: str, key: str, value) -> str:
        entries = season_records.get(key) or []
        if not entries:
            return f"| {label} | {TBD} | {TBD} | {TBD} |"
        shared = " (tied)" if len(entries) > 1 else ""
        names = ", ".join(wikilink(entry["team"]) for entry in entries)
        years = ", ".join(str(entry["year"]) for entry in entries)
        return f"| {label}{shared} | {names} | {value(entries[0])} | {years} |"

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
        shared = " (tied)" if len(holders) > 1 else ""
        return f"| {label}{shared} | {names} | {value(holders[0][1])} |"

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
description: All-time records, single-season feats, and dubious achievements of the Pine Hills Fantasy Football League.
---

# 📊 Records

The ledger of greatness and shame, computed from {len(matchup_stats.get('log', [])) // 2} captured matchups across {len(seasons)} seasons. Everything here is regular season. The postseason keeps its own record book on {wikilink('Playoffs')}.

## Single-Season Records

| Record | Holder | Value | Year |
|--------|--------|-------|------|
{chr(10).join(season_rows)}

## Single-Game Records

| Record | Holder | Value | When |
|--------|--------|-------|------|
{chr(10).join(game_rows)}

## Career Records

By manager: a career follows the person, not whichever franchise name they were flying that year. Rates carry their sample size, since one full season qualifies and several managers have played exactly that.

| Record | Owner | Value |
|--------|-------|-------|
{chr(10).join(career_rows)}

## Outright Marks

Every game ever played, phase ignored - the league's single-game marks with nothing held back. When the regular-season book above shows the same game, that game is the outright record too.

| Record | Holder | Value | When |
|--------|--------|-------|------|
{chr(10).join(single_game_rows(matchup_stats["books"][BOOK_TOTAL]))}

## Blowouts

Every game won by {BLOWOUT_MARGIN:.0f} or more, across all {len(log) // 2} captured games. Phase is tagged where it is not a regular-season week.

| Margin | Team | Score | Opponent | When |
|--------|------|-------|----------|------|
{chr(10).join(blowout_rows)}

## Nailbiters

Every game decided by {NAILBITER_MARGIN:.0f} point or less, a tie included - it is the closest a game can be.

| Margin | Team | Score | Opponent | When |
|--------|------|-------|----------|------|
{chr(10).join(nailbiter_rows)}

## All-Time Totals

Every game a manager has played, regular season, playoffs and consolation alike. The books above ask who was best; this asks who has played the most and scored the most.

| Owner | Games | Record | Win% | Points For | Points Against | Avg |
|-------|-------|--------|------|------------|----------------|-----|
{chr(10).join(total_rows)}

## Players

> Player records are keyed to the **player**, not the manager or the franchise. Regular season and postseason keep separate books, the same split the team records use. Bench marks count a player who scored while sitting.

| Record | Player | Mark | When |
|--------|--------|------|------|
{chr(10).join(player_rows)}

## Postseason

Kept in its own book, so a big regular-season week is never a Finals record. Championships, playoff and Finals single-game records, career playoff leaders and the per-manager ledger all live on {wikilink('Playoffs')}.

## 🍗 The "Poultry Controversy" Board

A hall of fame for the league's most infamous moments — bad beats, vetoed trades, and questionable lineup decisions.

| Year | Incident | Accused |
|------|----------|---------|
| {TBD} | {TBD} | {TBD} |

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

# 🧑 {owner}

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

Head-to-head against the person, not the franchise: both sides can have renamed several times over. Every meeting counts, playoffs included, most-played opponents first.

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
        shown = [wikilink(name) for name in team_names[:OWNER_INDEX_TEAMS_SHOWN]]
        if len(team_names) > OWNER_INDEX_TEAMS_SHOWN:
            shown.append(f"+{len(team_names) - OWNER_INDEX_TEAMS_SHOWN} more")
        franchises = ", ".join(shown)
        rows.append(
            f"| {wikilink(owner)} | {franchises} | {_year_range(record['years'], latest_year)} "
            f"| {record['wins']}-{record['losses']} | {record['wpct']*100:.1f}% | {len(record['titles'])} |"
        )

    return f"""---
title: Owners
description: The managers of the Pine Hills Fantasy Football League and the franchises they have run.
---

# 🧑 Owners

Every manager in Pine Hills history. A person keeps one page no matter how many
times they rename or replace their franchise, so career totals here span every
team they have run. Names come straight from Yahoo; spelling variants are merged
through `owner_aliases` in the league bible.

## Managers

| Owner | Franchises | Seasons | All-Time Record | Win% | Titles |
|-------|-----------|---------|-----------------|------|--------|
{chr(10).join(rows)}

## Related

- {wikilink('Teams')} · {wikilink('Seasons')} · {wikilink('Records')} · {wikilink('Champions')}
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
description: Franchise histories and owners of the Pine Hills Fantasy Football League.
---

# 👥 Teams

Every franchise in Pine Hills history. Each team page tracks the owner, season-by-season results, championships, and head-to-head records. Standings-derived stats are computed automatically; owners and titles come from the league bible. For career totals that follow a person across every team they have run, see {wikilink('Owners')}.

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
) -> str:
    sizes = playoff_field_sizes(matchup_stats)
    books = matchup_stats["books"]

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
        shared = " (tied)" if len(holders) > 1 else ""
        return f"| {label}{shared} | {names} | {value(holders[0][1])} |"

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
description: Pine Hills Fantasy Football League playoff format, champions, and Finals history.
---

# 🏆 Playoffs

The Pine Hills Fantasy Football League postseason. The bracket decides the title; the regular-season #1 is not the champion unless it wins it.

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

By manager: the trophy follows the person, not the team name they were flying that year.

| Owner | Titles | Years | Won With |
|-------|--------|-------|----------|
{chr(10).join(champ_rows)}

## Playoff Records

Bracket games only. The postseason keeps its own book: a 200-point week in October is a regular-season record and nothing more. Regular-season records live on {wikilink('Records')}.

| Record | Holder | Value | When |
|--------|--------|-------|------|
{chr(10).join(single_game_rows(books[PHASE_PLAYOFF], "Playoff"))}

## Finals Records

The title game only.

| Record | Holder | Value | When |
|--------|--------|-------|------|
{chr(10).join(single_game_rows(books[FINALS_ROUND], "Finals"))}

## Career Playoff Leaders

By manager, not franchise. Rates qualify at {MIN_PLAYOFF_GAMES_FOR_RATE} playoff games - one full bracket run - and carry their sample, so a thin one is visible rather than hidden.

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

    (CONTENT / "seasons").mkdir(parents=True, exist_ok=True)
    (CONTENT / "teams").mkdir(parents=True, exist_ok=True)
    (CONTENT / "owners").mkdir(parents=True, exist_ok=True)
    (CONTENT / "draft").mkdir(parents=True, exist_ok=True)
    (CONTENT / "records").mkdir(parents=True, exist_ok=True)

    owner_map = build_owner_map(bible, seasons)
    # The matchup log has to come first: bracket membership is what tells both
    # the franchise and the owner aggregates who actually made the playoffs.
    matchup_stats = build_matchup_stats(seasons, bible)
    aggregates = build_aggregates(seasons, matchup_stats["playoff_teams"])
    owner_aggregates = build_owner_aggregates(
        seasons, bible, owner_map, matchup_stats["playoff_teams"]
    )
    season_records = build_season_records(seasons, bible)
    owner_game_stats = build_owner_game_stats(seasons, owner_map, matchup_stats)
    print(f"  scanned {len(matchup_stats['log']) // 2} matchups")

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

    # records index
    rp = CONTENT / "records" / "index.md"
    rp.write_text(dash_normalize(gen_records_index(seasons, bible, matchup_stats, season_records, owner_aggregates, owner_game_stats)))
    print(f"  wrote {rp.relative_to(ROOT)}")

    # teams index
    tip = CONTENT / "teams" / "index.md"
    tip.write_text(dash_normalize(gen_teams_index(aggregates, bible, owner_map)))
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
    pp.write_text(dash_normalize(gen_playoffs_page(all_years, bible, matchup_stats, owner_aggregates, owner_game_stats)))
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
