//! Offline tests for the Sleeper mapping.
//!
//! The live Pine Hills V2 league has not played a game yet (2026 week 1), so
//! nothing on the real API exercises the scored paths: final rank off the
//! bracket, champions, points against, the title path. These fixtures are a
//! miniature COMPLETED season built to the shapes confirmed against the live
//! API on 2026-09-02, so those paths stay covered until real results land.

use phf_scraper::model::Season;
use phf_scraper::sleeper::{Payloads, build_season};
use serde_json::{Value, json};
use std::collections::{BTreeMap, HashMap};

/// A four-team league: two make the playoffs, one final decides the title.
fn payloads() -> Payloads {
    let league = json!({
        "league_id": "L1",
        "name": "Test League",
        "season": "2026",
        "status": "complete",
        "draft_id": "D1",
        "roster_positions": ["QB", "RB", "FLEX", "BN", "BN"],
        "settings": { "playoff_week_start": 3, "playoff_teams": 2, "num_teams": 4 },
    });

    let users = json!([
        // Only this manager set a team name; the rest fall back to the handle,
        // which is what the real league looks like (3 of 10 set one).
        { "user_id": "u1", "display_name": "ann", "metadata": { "team_name": "Ann's Team" } },
        { "user_id": "u2", "display_name": "bob", "metadata": {} },
        { "user_id": "u3", "display_name": "cid", "metadata": {} },
        { "user_id": "u4", "display_name": "dee", "metadata": {} },
    ]);

    let rosters = json!([
        { "roster_id": 1, "owner_id": "u1", "settings": { "wins": 2, "losses": 0 } },
        { "roster_id": 2, "owner_id": "u2", "settings": { "wins": 1, "losses": 1 } },
        { "roster_id": 3, "owner_id": "u3", "settings": { "wins": 1, "losses": 1 } },
        { "roster_id": 4, "owner_id": "u4", "settings": { "wins": 0, "losses": 2 } },
    ]);

    // Two regular-season weeks, then the final in week 3.
    let week = |a: (i64, f64), b: (i64, f64), c: (i64, f64), d: (i64, f64)| {
        json!([
            { "roster_id": a.0, "matchup_id": 1, "points": a.1,
              "starters": ["p1", "p2", "0"], "players": ["p1", "p2", "p3"],
              "players_points": { "p1": 10.0, "p2": 5.5, "p3": 1.0 } },
            { "roster_id": b.0, "matchup_id": 1, "points": b.1,
              "starters": [], "players": [], "players_points": {} },
            { "roster_id": c.0, "matchup_id": 2, "points": c.1,
              "starters": [], "players": [], "players_points": {} },
            { "roster_id": d.0, "matchup_id": 2, "points": d.1,
              "starters": [], "players": [], "players_points": {} },
        ])
    };

    let mut matchups = BTreeMap::new();
    matchups.insert(1, week((1, 100.0), (4, 90.0), (2, 80.0), (3, 70.0)));
    matchups.insert(2, week((1, 110.0), (3, 60.0), (2, 50.0), (4, 55.0)));
    // Week 3 is the final: only the two playoff teams play.
    matchups.insert(
        3,
        json!([
            { "roster_id": 1, "matchup_id": 1, "points": 120.0,
              "starters": [], "players": [], "players_points": {} },
            { "roster_id": 2, "matchup_id": 1, "points": 130.0,
              "starters": [], "players": [], "players_points": {} },
        ]),
    );

    let mut players = HashMap::new();
    players.insert("p1".into(), ("Pat One".to_string(), "QB".to_string()));
    players.insert("p2".into(), ("Pat Two".to_string(), "RB".to_string()));
    players.insert("p3".into(), ("Pat Three".to_string(), "WR".to_string()));

    Payloads {
        league,
        users,
        rosters,
        // Roster 2 beat roster 1 in the title game; the p:3 game is consolation.
        winners_bracket: json!([
            { "m": 1, "r": 1, "p": 1, "t1": 1, "t2": 2, "w": 2, "l": 1 },
            { "m": 2, "r": 1, "p": 3, "t1": 3, "t2": 4, "w": 3, "l": 4 },
        ]),
        losers_bracket: Value::Null,
        picks: json!([
            { "pick_no": 2, "round": 1, "roster_id": 2, "player_id": "p2",
              "metadata": { "first_name": "Pat", "last_name": "Two", "position": "RB" } },
            { "pick_no": 1, "round": 1, "roster_id": 1, "player_id": "p1",
              "metadata": { "first_name": "Pat", "last_name": "One", "position": "QB" } },
            // A defense: no full_name, and the city sits in first_name.
            { "pick_no": 3, "round": 1, "roster_id": 1, "player_id": "BAL",
              "metadata": { "first_name": "Baltimore", "last_name": "Ravens", "position": "DEF" } },
        ]),
        matchups,
        players,
    }
}

fn built() -> Season {
    build_season(&payloads(), 3).expect("build_season")
}

#[test]
fn team_name_falls_back_to_the_manager_handle() {
    let season = built();
    let names: Vec<&str> = season
        .teams
        .teams
        .iter()
        .map(|t| t.name.as_str())
        .collect();
    assert!(names.contains(&"Ann's Team"), "team_name wins when set");
    assert!(names.contains(&"bob"), "display_name is the fallback");

    // The owner is always the handle, which is what raw/bible.yaml's
    // `owner_aliases` block maps back to a real person across eras.
    let ann = season
        .teams
        .teams
        .iter()
        .find(|t| t.name == "Ann's Team")
        .unwrap();
    assert_eq!(ann.owner, "ann");
}

#[test]
fn final_rank_comes_from_the_bracket_not_the_regular_season() {
    let season = built();
    let rank = |name: &str| {
        season
            .teams
            .teams
            .iter()
            .find(|t| t.name == name)
            .unwrap_or_else(|| panic!("no team {name}"))
            .rank
    };
    // Ann went 2-0 and was the 1 seed, but lost the final: 2nd, not 1st.
    assert_eq!(rank("bob"), 1);
    assert_eq!(rank("Ann's Team"), 2);
    assert_eq!(rank("cid"), 3);
    assert_eq!(rank("dee"), 4);
}

#[test]
fn playoff_seed_is_regular_season_order_and_only_for_the_bracket() {
    let season = built();
    let seed = |name: &str| {
        season
            .teams
            .teams
            .iter()
            .find(|t| t.name == name)
            .unwrap()
            .playoff_seed
    };
    assert_eq!(seed("Ann's Team"), Some(1));
    assert_eq!(seed("bob"), Some(2));
    // Only two teams made this bracket, so the other two carry no seed at all
    // rather than a misleading 3 and 4.
    assert_eq!(seed("cid"), None);
    assert_eq!(seed("dee"), None);
}

#[test]
fn season_points_are_summed_from_the_weekly_matchups() {
    let season = built();
    let ann = season
        .teams
        .teams
        .iter()
        .find(|t| t.name == "Ann's Team")
        .unwrap();
    // Sleeper exposes no points_against at all and splits points_for across
    // fpts/fpts_decimal, so both totals are summed from the games instead.
    assert_eq!(ann.points_for, 100.0 + 110.0 + 120.0);
    assert_eq!(ann.points_against, 90.0 + 60.0 + 130.0);
}

#[test]
fn champions_come_from_the_title_game() {
    let season = built();
    let champions = season.champions.expect("a completed season names a champion");
    assert_eq!(champions.champion, "bob");
    assert_eq!(champions.runner_up, "Ann's Team");
    // The top seed is a separate fact from the champion, and here they differ.
    assert_eq!(champions.top_seed, "Ann's Team");
    assert_eq!(champions.toilet_winner, "dee");
}

#[test]
fn bracket_holds_only_the_title_path() {
    let season = built();
    let bracket = season.bracket.expect("a decided bracket is emitted");
    // The p:3 consolation game shares the week and must not appear.
    assert_eq!(bracket.games.len(), 1);
    let final_game = &bracket.games[0];
    assert_eq!(final_game.round, "Final");
    assert_eq!(final_game.week, 3);
    assert_eq!(final_game.advances_to, None);
    let winner = final_game.teams.iter().find(|t| t.is_winner).unwrap();
    assert_eq!(winner.name, "bob");
    assert_eq!(winner.score, 130.0);
}

#[test]
fn an_undecided_bracket_is_omitted_rather_than_emitted_empty() {
    // Sleeper publishes the bracket's shape at league creation, months before a
    // playoff game is played. That must not reach the generator as a diagram of
    // blank boxes.
    let mut p = payloads();
    p.winners_bracket = json!([
        { "m": 1, "r": 1, "p": 1, "t1": 1, "t2": 2, "w": null, "l": null },
    ]);
    let season = build_season(&p, 3).unwrap();
    assert!(season.bracket.is_none());
    assert!(season.champions.is_none());
}

#[test]
fn unplayed_weeks_are_excluded() {
    // The whole schedule is published up front, so an in-progress season must
    // emit only the weeks that have actually been scored.
    let season = build_season(&payloads(), 1).unwrap();
    assert_eq!(season.matchups.keys().collect::<Vec<_>>(), vec!["1"]);
    assert!(season.playoffs.weeks.is_empty(), "week 3 has not happened");
}

#[test]
fn a_season_with_no_games_played_claims_no_finish() {
    // Sleeper hands out rosters and a bracket shape months before kickoff. With
    // every team 0-0 on 0 points, any standings order is roster id in disguise,
    // so the season must claim no rank and no seed at all.
    let mut p = payloads();
    // The real pre-season shape: the bracket exists but nothing is decided.
    p.winners_bracket = json!([
        { "m": 1, "r": 1, "p": 1, "t1": 1, "t2": 2, "w": null, "l": null },
    ]);
    let season = build_season(&p, 0).unwrap();
    assert!(season.teams.teams.iter().all(|t| t.rank == 0));
    assert!(season.teams.teams.iter().all(|t| t.playoff_seed.is_none()));
    assert!(season.matchups.is_empty());
    assert!(season.champions.is_none());
    assert!(season.bracket.is_none());

    // ...and it falls back to an alphabetical list rather than Sleeper's order.
    let names: Vec<&str> = season
        .teams
        .teams
        .iter()
        .map(|t| t.name.as_str())
        .collect();
    assert_eq!(names, vec!["Ann's Team", "bob", "cid", "dee"]);
}

#[test]
fn playoff_weeks_stop_at_the_end_of_the_bracket() {
    // playoff_week_start is 3 and the bracket is one round, so a week 4 on the
    // schedule is NOT a playoff week just because it sits past the start.
    let mut p = payloads();
    p.matchups.insert(
        4,
        json!([
            { "roster_id": 1, "matchup_id": 1, "points": 10.0,
              "starters": [], "players": [], "players_points": {} },
            { "roster_id": 2, "matchup_id": 1, "points": 20.0,
              "starters": [], "players": [], "players_points": {} },
        ]),
    );
    let season = build_season(&p, 4).unwrap();
    assert!(season.matchups.contains_key("4"), "still in the full record");
    assert_eq!(season.playoffs.weeks.keys().collect::<Vec<_>>(), vec!["3"]);
}

#[test]
fn starters_map_onto_yahoo_slot_names_and_the_rest_are_bench() {
    let season = built();
    let roster = &season.weeks["1"].rosters["Ann's Team"];
    let rows: Vec<(&str, &str)> = roster
        .players
        .iter()
        .map(|p| (p.slot.as_str(), p.name.as_str()))
        .collect();
    // roster_positions is QB/RB/FLEX/BN/BN; Sleeper's "FLEX" is rendered in the
    // Yahoo vocabulary the generator sorts on, and the "0" placeholder for an
    // empty starting slot is dropped rather than emitted as a player.
    assert_eq!(
        rows,
        vec![("QB", "Pat One"), ("RB", "Pat Two"), ("BN", "Pat Three")]
    );
    assert_eq!(roster.players[1].points, 5.5);
}

#[test]
fn draft_picks_are_ordered_by_overall_pick() {
    let season = built();
    let picks = &season.draft.draft_results;
    // The fixture lists pick 2 first; Sleeper's pick_no is already the overall
    // number, so ordering by it is all that is required.
    assert_eq!(picks[0].pick, 1);
    assert_eq!(picks[0].player, "Pat One");
    assert_eq!(picks[0].team, "Ann's Team");
    assert_eq!(picks[1].pick, 2);
    assert_eq!(picks[1].team, "bob");
}

#[test]
fn a_drafted_defense_is_named_the_way_the_yahoo_era_named_it() {
    // Sleeper splits a defense as "Baltimore" / "Ravens"; Yahoo filed it as
    // "Ravens". Joining them on the nickname is what stops every defense
    // getting a second player page at the platform move.
    let season = built();
    let defense = season
        .draft
        .draft_results
        .iter()
        .find(|p| p.position == "DEF")
        .expect("the fixture drafts a defense");
    assert_eq!(defense.player, "Ravens");
}
