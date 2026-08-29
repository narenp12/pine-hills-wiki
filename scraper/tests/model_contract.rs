//! Contract test: the JSON emitted by the Rust model MUST match what
//! scripts/generate.py expects in raw/<year>.json.
//!
//! This locks the shape so a refactor can't silently drift out of sync with
//! the Python generator. If generate.py's expectations change, update both
//! sides and this test together.

use phf_scraper::model::*;
use std::collections::BTreeMap;

fn sample_season() -> Season {
    let mut season = Season {
        season: 2024,
        ..Default::default()
    };
    season.standings.teams.push(Team {
        team_key: "Example FC".into(),
        name: "Example FC".into(),
        owner: "Naren".into(),
        wins: 12,
        losses: 2,
        points_for: 1500.5,
        points_against: 1100.0,
        rank: 1,
    });
    season.teams = season.standings.clone();
    season.draft.draft_results.push(DraftPick {
        pick: 1,
        round: 1,
        team: "Example FC".into(),
        player: "Justin Jefferson".into(),
        position: "WR".into(),
    });
    let mut w = BTreeMap::new();
    w.insert(
        "15".to_string(),
        vec![Matchup {
            teams: vec![
                MatchTeam { name: "Example FC".into(), score: 100.0, is_winner: true },
                MatchTeam { name: "Rivals".into(), score: 98.2, is_winner: false },
            ],
        }],
    );
    season.playoffs.weeks = w;
    let mut weeks = BTreeMap::new();
    let mut ros = BTreeMap::new();
    ros.insert(
        "Example FC".to_string(),
        Roster {
            players: vec![RosterPlayer { name: "Christian McCaffrey".into(), position: "RB".into() }],
        },
    );
    weeks.insert("1".to_string(), Week { rosters: ros.clone() });
    weeks.insert("18".to_string(), Week { rosters: ros });
    season.weeks = weeks;
    season
}

#[test]
fn emitted_json_matches_generator_contract() {
    let json = serde_json::to_string_pretty(&sample_season()).expect("serialize");
    let v: serde_json::Value = serde_json::from_str(&json).expect("valid json");

    // Top-level shape
    assert_eq!(v["season"], 2024);
    assert!(v.get("standings").is_some(), "missing top-level standings");
    assert!(v.get("teams").is_some(), "missing top-level teams");
    assert!(v.get("draft").is_some(), "missing draft");
    assert!(v.get("playoffs").is_some(), "missing playoffs");
    assert!(v.get("weeks").is_some(), "missing weeks");

    // standings.teams / teams.teams
    let st = &v["standings"]["teams"];
    assert!(st.is_array(), "standings.teams must be a list");
    assert_eq!(st[0]["name"], "Example FC");
    assert_eq!(st[0]["wins"], 12);
    assert_eq!(st[0]["points_for"], 1500.5);
    assert!(v["teams"]["teams"].is_array(), "teams.teams must be a list");

    // draft.draft_results
    let dr = &v["draft"]["draft_results"];
    assert!(dr.is_array(), "draft.draft_results must be a list");
    assert_eq!(dr[0]["player"], "Justin Jefferson");

    // playoffs.weeks keyed by week string, each a list of {teams:[{name,score,is_winner}]}
    let po = &v["playoffs"]["weeks"]["15"];
    assert!(po.is_array(), "playoffs.weeks.15 must be a list");
    assert_eq!(po[0]["teams"][0]["name"], "Example FC");
    assert_eq!(po[0]["teams"][1]["score"], 98.2);
    assert_eq!(po[0]["teams"][0]["is_winner"], true);

    // weeks.<n>.rosters keyed by team -> {players:[{name,position}]}
    let r1 = &v["weeks"]["1"]["rosters"]["Example FC"]["players"];
    assert!(r1.is_array(), "weeks.1.rosters.Example FC.players must be a list");
    assert_eq!(r1[0]["name"], "Christian McCaffrey");
    assert_eq!(r1[0]["position"], "RB");
    assert!(v["weeks"]["18"]["rosters"]["Example FC"]["players"].is_array());
}
