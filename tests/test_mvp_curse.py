"""The MVP Curse lore entry asserts facts about raw/. These check they hold.

Unlike the rest of the suite these run against the real capture, because the
claim is about the data, not the code. A new season that breaks the curse should
fail here so the lore entry gets rewritten instead of quietly going false.
"""
import os
import sys

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.generate import (
    apply_derived_champions,
    apply_derived_owners,
    build_decisive_wins,
    build_matchup_stats,
    build_player_log,
    champ_year,
    load_bible,
    load_raw,
    season_mvp,
)

CURSE_TITLE = "The MVP Curse"


@pytest.fixture(scope="module")
def league():
    seasons = load_raw()
    bible = apply_derived_owners(
        apply_derived_champions(load_bible(), seasons), seasons
    )
    stats = build_matchup_stats(seasons, bible)
    decisive = build_decisive_wins(build_player_log(seasons), stats["log"])
    return seasons, bible, decisive


@pytest.fixture(scope="module")
def curse(league):
    _, bible, _ = league
    entries = ((bible.get("lore") or {}).get("curses")) or []
    for entry in entries:
        if entry.get("title") == CURSE_TITLE:
            return entry
    pytest.skip(f"{CURSE_TITLE} is not in the bible")


def mvp_teams_by_year(seasons, decisive):
    """{year: {team: swung wins}} for the season MVP, skipping years with none."""
    out = {}
    for year in sorted(seasons):
        holders = season_mvp(year, decisive)
        teams = {}
        for row in holders:
            for team, wins in row["teams"].items():
                teams[team] = teams.get(team, 0) + wins
        if teams:
            out[year] = teams
    return out


def test_no_mvp_has_been_on_the_champion(league, curse):
    seasons, bible, decisive = league
    broke = [
        (year, (champ_year(bible, year) or {}).get("champion"))
        for year, teams in mvp_teams_by_year(seasons, decisive).items()
        if (champ_year(bible, year) or {}).get("champion") in teams
    ]
    assert not broke, f"the curse is broken, so {CURSE_TITLE} needs rewriting: {broke}"


def test_the_story_counts_every_captured_season(league, curse):
    """"eight captured seasons" has to keep matching the number of MVPs."""
    seasons, _, decisive = league
    assert len(mvp_teams_by_year(seasons, decisive)) == 8


def test_involved_lists_every_team_that_rostered_an_mvp(league, curse):
    seasons, _, decisive = league
    expected = {
        team
        for teams in mvp_teams_by_year(seasons, decisive).values()
        for team in teams
    }
    assert set(curse.get("involved") or []) == expected


def test_the_cited_seasons_say_what_the_story_says(league, curse):
    seasons, bible, decisive = league
    mvp_teams = mvp_teams_by_year(seasons, decisive)
    assert mvp_teams[2020] == {"Anish's Awesome Team": 9}
    assert mvp_teams[2023] == {"Pukakke NaKupp": 8}
    assert mvp_teams[2021] == {"Super Squirrels": 6}
    assert champ_year(bible, 2021)["champion"] == "varun's victorious team"
    assert champ_year(bible, 2023)["champion"] == "Super Squirrels"


def test_2020_is_the_largest_haul_on_record(league, curse):
    seasons, _, decisive = league
    hauls = {
        year: sum(teams.values())
        for year, teams in mvp_teams_by_year(seasons, decisive).items()
    }
    assert max(hauls, key=hauls.get) == 2020


def test_both_anish_teams_are_his(league, curse):
    _, bible, _ = league
    owners = bible.get("owners") or {}
    assert owners["Anish's Awesome Team"] == owners["Pukakke NaKupp"] == "Anish"
