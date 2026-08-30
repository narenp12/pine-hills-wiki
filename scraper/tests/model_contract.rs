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
                MatchTeam {
                    name: "Example FC".into(),
                    score: 100.0,
                    is_winner: true,
                },
                MatchTeam {
                    name: "Rivals".into(),
                    score: 98.2,
                    is_winner: false,
                },
            ],
        }],
    );
    season.playoffs.weeks = w;
    let mut weeks = BTreeMap::new();
    let mut ros = BTreeMap::new();
    ros.insert(
        "Example FC".to_string(),
        Roster {
            players: vec![RosterPlayer {
                name: "Christian McCaffrey".into(),
                position: "RB".into(),
            }],
        },
    );
    weeks.insert(
        "1".to_string(),
        Week {
            rosters: ros.clone(),
        },
    );
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
    assert!(
        r1.is_array(),
        "weeks.1.rosters.Example FC.players must be a list"
    );
    assert_eq!(r1[0]["name"], "Christian McCaffrey");
    assert_eq!(r1[0]["position"], "RB");
    assert!(v["weeks"]["18"]["rosters"]["Example FC"]["players"].is_array());
}

/// REGRESSION: the sample above is hand-built, so it could not catch that the REAL
/// `from_dump_dir` pipeline left `standings.teams` EMPTY while filling `teams.teams`.
/// generate.py renders the "Final Standings" table from `standings.teams`, so every
/// season page shipped with an empty table despite the JSON holding full records.
/// This exercises the actual assembly path end-to-end against a committed fixture.
#[test]
fn from_dump_dir_populates_standings_for_the_generator() {
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures");
    let season = phf_scraper::extract::from_dump_dir(&dir, 2024, "489811").expect("assemble 2024");

    assert_eq!(
        season.teams.teams.len(),
        12,
        "teams.teams populated (12 teams)"
    );
    assert_eq!(
        season.standings.teams.len(),
        12,
        "standings.teams MUST be populated — generate.py reads it for the standings table"
    );

    // Both views must agree, and standings must be ordered by rank so the
    // generator's positional numbering (enumerate) matches Yahoo's real rank.
    let ranks: Vec<i64> = season.standings.teams.iter().map(|t| t.rank).collect();
    let mut sorted = ranks.clone();
    sorted.sort();
    assert_eq!(
        ranks, sorted,
        "standings.teams sorted by rank, got {ranks:?}"
    );

    let json = serde_json::to_value(&season).expect("serialize");
    let st = &json["standings"]["teams"];
    assert_eq!(st[0]["rank"], 1, "first standings row is rank 1");
    assert_eq!(st[0]["name"], "Stroud Boys", "2024 rank 1 = Stroud Boys");
    assert!(
        st[0]["points_for"].as_f64().unwrap() > 0.0,
        "standings rows carry real points"
    );
}
