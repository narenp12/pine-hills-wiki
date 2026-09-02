//! Tests for the Yahoo Fantasy v2 API parser, against REAL captured payloads.
//!
//! Fixtures live in `tests/fixtures/v2/` (committed) so `cargo test` passes on a
//! clean clone — the gitignored `dump/` must never be a test dependency.

use std::path::PathBuf;

use phf_scraper::parse_v2::{
    derive_champions, find_league_key, from_v2_dir, parse_scoreboard, parse_standings,
};

fn fixtures() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/v2")
}

fn read(name: &str) -> String {
    std::fs::read_to_string(fixtures().join(name)).expect("fixture should exist")
}

#[test]
fn standings_parses_every_team_with_owner_and_record() {
    let rows = parse_standings(&read("2018-380.l.1578201-standings.json")).unwrap();
    assert_eq!(rows.len(), 6, "2018 was a 6-team league");

    // Sorted by Yahoo's rank.
    assert_eq!(rows[0].team.rank, 1);
    assert_eq!(rows[0].team.name, "Curry’s legit team");

    // The owner of EVERY team must be present. The rendered-page pipeline could
    // only ever fill in the viewing user's own manager, which is the gap this
    // parser exists to close.
    for r in &rows {
        assert!(
            !r.team.owner.is_empty(),
            "team {:?} has no owner",
            r.team.name
        );
    }
    assert_eq!(rows[0].team.owner, "lokesh");
}

#[test]
fn rank_is_final_finish_not_regular_season_record() {
    // The whole champion derivation rests on this. In 2018 the rank-1 team went
    // 4-7 while a 9-2 team finished 4th, because Yahoo's rank on a completed
    // season is the playoff-adjusted finish.
    let rows = parse_standings(&read("2018-380.l.1578201-standings.json")).unwrap();

    let champ = &rows[0];
    assert_eq!(champ.team.rank, 1);
    assert_eq!((champ.team.wins, champ.team.losses), (4, 7));

    let best_record = rows
        .iter()
        .max_by_key(|r| r.team.wins)
        .expect("non-empty standings");
    assert_eq!(best_record.team.name, "Sharman’s Scorpions");
    assert_eq!((best_record.team.wins, best_record.team.losses), (9, 2));
    assert_eq!(
        best_record.team.rank, 4,
        "the best regular-season record finished 4th"
    );
}

#[test]
fn champion_derivation_uses_rank_and_seed_separately() {
    let rows = parse_standings(&read("2018-380.l.1578201-standings.json")).unwrap();
    let c = derive_champions(&rows);

    assert_eq!(c.champion, "Curry’s legit team");
    assert_eq!(c.runner_up, "Anish's Awesome Team");

    // Top seed is a DIFFERENT team than the champion: 2018's winner entered the
    // playoffs as the 5 seed. Collapsing these two fields would be wrong.
    assert_ne!(c.top_seed, c.champion);
    assert_eq!(
        rows.iter().find(|r| r.playoff_seed == 1).unwrap().team.name,
        c.top_seed
    );

    // Toilet bowl = last place in the FINAL standings (rank 6 of 6 in 2018).
    assert_eq!(c.toilet_winner, rows.last().unwrap().team.name);
    assert_eq!(rows.last().unwrap().team.rank, 6);
    assert_ne!(c.toilet_winner, c.champion);
}

#[test]
fn scoreboard_parses_scores_and_marks_the_declared_winner() {
    let ws = parse_scoreboard(&read("2018-380.l.1578201-scoreboard-wk16.json")).unwrap();
    assert_eq!(ws.week, 16);
    assert_eq!(ws.matchups.len(), 2);
    assert!(ws.is_playoffs.iter().all(|p| *p), "week 16 is all playoffs");

    // The championship game: rank 1 beat rank 2.
    let title = ws
        .matchups
        .iter()
        .find(|m| m.teams.iter().any(|t| t.name == "Curry’s legit team"))
        .expect("championship matchup present");
    let winner = title.teams.iter().find(|t| t.is_winner).unwrap();
    let loser = title.teams.iter().find(|t| !t.is_winner).unwrap();
    assert_eq!(winner.name, "Curry’s legit team");
    assert_eq!(winner.score, 165.16);
    assert_eq!(loser.name, "Anish's Awesome Team");
    assert_eq!(loser.score, 120.74);

    // Exactly one winner per matchup — never both, never neither (for a decided game).
    for m in &ws.matchups {
        assert_eq!(m.teams.iter().filter(|t| t.is_winner).count(), 1);
    }
}

#[test]
fn league_keys_resolve_per_season_from_the_index() {
    let idx = read("leagues.json");

    // The league ids here are the ones in selectors.toml.
    assert_eq!(
        find_league_key(&idx, 2018, "1578201").as_deref(),
        Some("380.l.1578201")
    );
    assert_eq!(
        find_league_key(&idx, 2025, "484479").as_deref(),
        Some("461.l.484479")
    );
    // A season the league never had.
    assert_eq!(find_league_key(&idx, 2017, "1578201"), None);
}

#[test]
fn league_lookup_is_not_confused_by_the_second_league() {
    // 2019-2022 this account also ran "PH Dynasty". Resolving by season alone
    // would be ambiguous, so lookup keys on league_id and must return the Pine
    // Hills league — never the Dynasty one.
    let idx = read("leagues.json");

    assert_eq!(
        find_league_key(&idx, 2019, "369572").as_deref(),
        Some("390.l.369572"),
        "2019 Pine Hills"
    );
    // A Dynasty id for the same season resolves to the Dynasty league, proving
    // the two are distinguished rather than collapsed.
    assert_eq!(
        find_league_key(&idx, 2019, "1289366").as_deref(),
        Some("390.l.1289366")
    );
    // ...and a Dynasty id is never returned for a Pine Hills lookup.
    assert_ne!(
        find_league_key(&idx, 2019, "369572").as_deref(),
        Some("390.l.1289366")
    );
}

#[test]
fn from_v2_dir_assembles_a_season_and_leaves_draft_alone() {
    let s = from_v2_dir(&fixtures(), 2018, "380.l.1578201").unwrap();

    assert_eq!(s.season, 2018);
    assert_eq!(s.teams.teams.len(), 6);
    // Bug 5 in HANDOFF.md: generate.py renders the standings table from
    // `standings.teams`, so leaving it empty ships a blank table.
    assert_eq!(s.standings.teams.len(), 6);
    assert_eq!(s.standings.teams[0].rank, 1);

    // Weeks 14-16 are in the fixture dir.
    assert_eq!(s.matchups.keys().collect::<Vec<_>>(), vec!["14", "15", "16"]);
    assert_eq!(s.playoffs.weeks["16"].len(), 2);

    let c = s.champions.expect("champions derived");
    assert_eq!(c.champion, "Curry’s legit team");

    // Draft is NOT this parser's job — the rendered-page pipeline stays the only
    // source for picks, and this path must not silently blank them.
    assert!(s.draft.draft_results.is_empty());
}

#[test]
fn bracket_excludes_consolation_games_in_the_same_week() {
    // 2018 week 15 has THREE playoff-flagged games, but only two are on the path
    // to the title. Yahoo flags none of them as consolation, so a filter on
    // `is_consolation` would wrongly keep all three.
    let s = from_v2_dir(&fixtures(), 2018, "380.l.1578201").unwrap();
    assert_eq!(s.playoffs.weeks["15"].len(), 3, "raw week 15 has 3 games");

    let b = s.bracket.expect("bracket derived");
    let semis: Vec<_> = b.games.iter().filter(|g| g.week == 15).collect();
    assert_eq!(semis.len(), 2, "only 2 of the 3 are semifinals");
    assert!(semis.iter().all(|g| g.round == "Semifinal"));
}

#[test]
fn bracket_handles_first_round_byes() {
    // 2018 was a 6-team bracket: 2 quarterfinals, then the two teams with byes
    // join at the semifinal. They must appear for the first time in round 2.
    let b = from_v2_dir(&fixtures(), 2018, "380.l.1578201")
        .unwrap()
        .bracket
        .unwrap();

    let quarters: Vec<_> = b.games.iter().filter(|g| g.round == "Quarterfinal").collect();
    assert_eq!(quarters.len(), 2);

    let in_quarters: Vec<&str> = quarters
        .iter()
        .flat_map(|g| g.teams.iter().map(|t| t.name.as_str()))
        .collect();
    // Byes: these two played a semifinal without playing a quarterfinal.
    for bye in ["D4rthSi Dragons", "Sharman’s Scorpions"] {
        assert!(!in_quarters.contains(&bye), "{bye} should have a bye");
    }
    assert_eq!(b.games.len(), 5, "2 quarters + 2 semis + 1 final");
}

#[test]
fn bracket_rounds_are_wired_winner_to_next_game() {
    let b = from_v2_dir(&fixtures(), 2018, "380.l.1578201")
        .unwrap()
        .bracket
        .unwrap();

    let by_id = |id: &str| b.games.iter().find(|g| g.id == id).unwrap();

    // Every non-final game points at a real game, and the team it sends there is
    // the winner it actually produced.
    for g in b.games.iter().filter(|g| g.round != "Final") {
        let next_id = g.advances_to.as_ref().expect("non-final advances somewhere");
        let winner = g.teams.iter().find(|t| t.is_winner).unwrap();
        assert!(
            by_id(next_id).teams.iter().any(|t| t.name == winner.name),
            "{} won {} but is absent from {next_id}",
            winner.name,
            g.id
        );
    }

    // The final is the terminus.
    let finals: Vec<_> = b.games.iter().filter(|g| g.round == "Final").collect();
    assert_eq!(finals.len(), 1);
    assert!(finals[0].advances_to.is_none());
    let champ = finals[0].teams.iter().find(|t| t.is_winner).unwrap();
    assert_eq!(champ.name, "Curry’s legit team");
}

#[test]
fn bracket_is_none_without_a_champion() {
    // No champion means no anchor to walk back from; returning None lets the
    // generator fall back rather than render an invented bracket.
    use std::collections::BTreeMap;
    let weeks: BTreeMap<String, Vec<phf_scraper::model::Matchup>> = BTreeMap::new();
    assert!(phf_scraper::parse_v2::derive_bracket(&weeks, "").is_none());
    assert!(phf_scraper::parse_v2::derive_bracket(&weeks, "Nobody").is_none());
}
