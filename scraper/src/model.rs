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
    /// Seed the team ENTERED the playoffs with. Distinct from `rank`, which on a
    /// completed season is the final playoff-adjusted finish. Only the v2 API
    /// knows this, so it is omitted when absent rather than guessed from
    /// standings position.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub playoff_seed: Option<i64>,
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
    /// Every week's matchups, keyed by week number. `playoffs.weeks` holds the
    /// playoff subset; this holds the complete regular-season + playoff record.
    /// Only populated by the v2 API path, so it is omitted when empty to keep the
    /// existing rendered-page output byte-identical.
    #[serde(skip_serializing_if = "std::collections::BTreeMap::is_empty")]
    pub matchups: std::collections::BTreeMap<String, Vec<Matchup>>,
    /// Champion / runner-up / top seed, derived from the final standings rank.
    /// Omitted when unknown so the generator falls back to the league bible.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub champions: Option<Champions>,
    /// The real championship bracket, walked back from the final. Omitted when it
    /// cannot be derived, so the generator can fall back rather than invent one.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bracket: Option<Bracket>,
}

/// One game in the championship bracket.
#[derive(Debug, Serialize, Default, Clone)]
pub struct BracketGame {
    /// Stable id, `W<week>G<n>`, used to wire rounds together.
    pub id: String,
    pub week: i64,
    /// Human label for the round: "Final", "Semifinal", "Quarterfinal", ...
    pub round: String,
    pub teams: Vec<MatchTeam>,
    /// Id of the next-round game the winner advanced to. `None` for the final.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub advances_to: Option<String>,
}

/// The championship bracket, earliest round first.
///
/// Only the games on the path to the title — the consolation bracket runs in the
/// same weeks with the same `is_playoffs` flag and is excluded.
#[derive(Debug, Serialize, Default, Clone)]
pub struct Bracket {
    pub games: Vec<BracketGame>,
}

/// Season outcome facts derived from Yahoo's playoff-adjusted final rank.
#[derive(Debug, Serialize, Default, Clone, PartialEq)]
pub struct Champions {
    pub champion: String,
    pub runner_up: String,
    /// Team that entered the playoffs as the 1 seed — usually NOT the champion.
    pub top_seed: String,
    /// Toilet bowl "winner": whoever finished last in the final standings.
    pub toilet_winner: String,
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
