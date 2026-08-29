//! Canonical data model — must match scripts/generate.py's expected raw/<year>.json.

use serde::Serialize;

#[derive(Debug, Serialize, Default, Clone)]
pub struct Team {
    pub team_key: String,
    pub name: String,
    pub owner: String,
    pub wins: i64,
    pub losses: i64,
    pub points_for: f64,
    pub points_against: f64,
    pub rank: i64,
}

#[derive(Debug, Serialize, Default, Clone)]
pub struct DraftPick {
    pub pick: i64,
    pub round: i64,
    pub team: String,
    pub player: String,
    pub position: String,
}

#[derive(Debug, Serialize, Default, Clone)]
pub struct MatchTeam {
    pub name: String,
    pub score: f64,
    pub is_winner: bool,
}

#[derive(Debug, Serialize, Default, Clone)]
pub struct Matchup {
    pub teams: Vec<MatchTeam>,
}

#[derive(Debug, Serialize, Default, Clone)]
pub struct RosterPlayer {
    pub name: String,
    pub position: String,
}

#[derive(Debug, Serialize, Default, Clone)]
pub struct Roster {
    pub players: Vec<RosterPlayer>,
}

#[derive(Debug, Serialize, Default, Clone)]
pub struct Season {
    pub season: u32,
    #[serde(rename = "standings")]
    pub standings: Standings,
    pub teams: Standings,
    pub draft: Draft,
    pub playoffs: Playoffs,
    pub weeks: std::collections::BTreeMap<String, Week>,
}

#[derive(Debug, Serialize, Default, Clone)]
pub struct Standings {
    #[serde(rename = "teams")]
    pub teams: Vec<Team>,
}

#[derive(Debug, Serialize, Default, Clone)]
pub struct Draft {
    #[serde(rename = "draft_results")]
    pub draft_results: Vec<DraftPick>,
}

#[derive(Debug, Serialize, Default, Clone)]
pub struct Playoffs {
    #[serde(rename = "weeks")]
    pub weeks: std::collections::BTreeMap<String, Vec<Matchup>>,
}

#[derive(Debug, Serialize, Default, Clone)]
pub struct Week {
    #[serde(skip_serializing_if = "std::collections::BTreeMap::is_empty")]
    pub rosters: std::collections::BTreeMap<String, Roster>,
}
