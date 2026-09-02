//! Parser for the Yahoo Fantasy v2 read-only API (`format=json_f`).
//!
//! Payloads come from `scripts/harvest_v2.py`, which reads them off
//! `pub-api-ro.fantasysports.yahoo.com`. This is a pure offline parser: it never
//! touches the network, so it is fully testable against committed fixtures.
//!
//! Why this exists alongside `parse_rendered`: the rendered-page pipeline can only
//! see standings + draft, and only the viewing user's own manager name. The v2
//! payloads carry every team's owner, every week's matchup scores, and the
//! playoff-adjusted final rank -- the three things `HANDOFF.md` lists as gaps.

use anyhow::{Context, Result};
use serde_json::Value;

use crate::model::{Champions, MatchTeam, Matchup, Season, Team};

/// Yahoo returns numbers as JSON strings in most places but as bare numbers in a
/// few (`rank`, `ties`). Accept either.
fn as_f64(v: &Value) -> f64 {
    v.as_f64()
        .or_else(|| v.as_str().and_then(|s| s.trim().parse::<f64>().ok()))
        .unwrap_or(0.0)
}

fn as_i64(v: &Value) -> i64 {
    v.as_i64()
        .or_else(|| v.as_str().and_then(|s| s.trim().parse::<i64>().ok()))
        .unwrap_or(0)
}

fn as_str(v: &Value) -> String {
    v.as_str().unwrap_or_default().to_string()
}

/// Collection entries are wrapped one level deep: `[{"team": {...}}, ...]`.
/// Unwrap that if present, otherwise use the object as-is.
fn unwrap_entry<'a>(v: &'a Value, key: &str) -> &'a Value {
    v.get(key).unwrap_or(v)
}

/// One parsed standings row, carrying the extra fields the canonical `Team`
/// model has no home for but the generator needs to name a champion.
#[derive(Debug, Clone, Default)]
pub struct StandingsRow {
    pub team: Team,
    pub team_key: String,
    /// Seed the team entered the playoffs with (NOT the final finish).
    pub playoff_seed: i64,
    pub ties: i64,
}

/// Parse a `league/<key>/standings` payload.
///
/// Returns rows sorted by Yahoo's `rank`, which on a COMPLETED season is the
/// final playoff-adjusted finish, not the regular-season record. (2018: the
/// rank-1 team went 4-7 while a 9-2 team finished 4th.)
pub fn parse_standings(json: &str) -> Result<Vec<StandingsRow>> {
    let doc: Value = serde_json::from_str(json).context("standings payload is not valid JSON")?;
    let league = doc
        .pointer("/fantasy_content/league")
        .context("no fantasy_content.league in standings payload")?;
    let league_id = as_str(&league["league_id"]);
    let teams = league
        .pointer("/standings/teams")
        .and_then(Value::as_array)
        .context("no standings.teams array")?;

    let mut rows = Vec::with_capacity(teams.len());
    for entry in teams {
        let t = unwrap_entry(entry, "team");
        let st = &t["team_standings"];
        let outcome = &st["outcome_totals"];
        let name = as_str(&t["name"]);

        // managers: [ { manager: { nickname, ... } } ] -- first manager is the owner.
        let owner = t["managers"]
            .as_array()
            .and_then(|ms| ms.first())
            .map(|m| as_str(&unwrap_entry(m, "manager")["nickname"]))
            .unwrap_or_default();

        rows.push(StandingsRow {
            team: Team {
                // Keyed by NAME, not rank: Yahoo can report two teams at the same
                // rank, which collided and dropped a team when keyed on rank.
                team_key: format!("{league_id}-{name}"),
                name,
                owner,
                wins: as_i64(&outcome["wins"]),
                losses: as_i64(&outcome["losses"]),
                points_for: as_f64(&st["points_for"]),
                points_against: as_f64(&st["points_against"]),
                rank: as_i64(&st["rank"]),
                // Absent for teams that missed the playoffs — keep that as None
                // rather than 0 so the generator can render a dash.
                playoff_seed: match as_i64(&st["playoff_seed"]) {
                    0 => None,
                    n => Some(n),
                },
            },
            team_key: as_str(&t["team_key"]),
            playoff_seed: as_i64(&st["playoff_seed"]),
            ties: as_i64(&outcome["ties"]),
        });
    }
    rows.sort_by_key(|r| r.team.rank);
    Ok(rows)
}

/// Find the full league key (e.g. `380.l.1578201`) for a season from the
/// harvested `leagues.json` index.
///
/// Matching on `league_id` rather than name matters: this account has a SECOND
/// league ("PH Dynasty", 2019-2022) whose seasons overlap Pine Hills, so a
/// season number alone is ambiguous. `selectors.toml` already records the right
/// league id per season, so that is what we key on.
pub fn find_league_key(leagues_json: &str, season: u32, league_id: &str) -> Option<String> {
    let doc: Value = serde_json::from_str(leagues_json).ok()?;
    let games = doc
        .pointer("/fantasy_content/users/0/user/games")?
        .as_array()?;
    for g in games {
        let g = unwrap_entry(g, "game");
        if as_str(&g["season"]) != season.to_string() {
            continue;
        }
        for l in g["leagues"].as_array()? {
            let l = unwrap_entry(l, "league");
            if as_str(&l["league_id"]) == league_id {
                return Some(as_str(&l["league_key"]));
            }
        }
    }
    None
}

/// One parsed week of matchups.
#[derive(Debug, Clone, Default)]
pub struct WeekScores {
    pub week: i64,
    pub matchups: Vec<Matchup>,
    /// Parallel to `matchups`: whether Yahoo flagged each as a playoff game.
    pub is_playoffs: Vec<bool>,
}

/// Parse a `league/<key>/scoreboard;week=N` payload.
pub fn parse_scoreboard(json: &str) -> Result<WeekScores> {
    let doc: Value = serde_json::from_str(json).context("scoreboard payload is not valid JSON")?;
    let league = doc
        .pointer("/fantasy_content/league")
        .context("no fantasy_content.league in scoreboard payload")?;
    let week = as_i64(&league["scoreboard"]["week"]);
    let matchups = league
        .pointer("/scoreboard/matchups")
        .and_then(Value::as_array)
        .context("no scoreboard.matchups array")?;

    let mut out = WeekScores {
        week,
        ..Default::default()
    };
    for entry in matchups {
        let m = unwrap_entry(entry, "matchup");
        let winner = as_str(&m["winner_team_key"]);
        let teams = m["teams"].as_array().map(Vec::as_slice).unwrap_or(&[]);
        let mut mt = Vec::with_capacity(teams.len());
        for tentry in teams {
            let t = unwrap_entry(tentry, "team");
            let key = as_str(&t["team_key"]);
            mt.push(MatchTeam {
                name: as_str(&t["name"]),
                score: as_f64(&t["team_points"]["total"]),
                // Compare against the matchup's declared winner rather than the
                // higher score: a tie has no winner_team_key, and neither side
                // should be marked a winner.
                is_winner: !winner.is_empty() && key == winner,
            });
        }
        out.matchups.push(Matchup { teams: mt });
        out.is_playoffs.push(as_i64(&m["is_playoffs"]) == 1);
    }
    Ok(out)
}

/// Derive champion / runner-up / top seed from parsed standings.
///
/// Champion and runner-up come from the final `rank`, which Yahoo sets from the
/// playoff result. Top seed is the team that ENTERED the playoffs seeded 1, which
/// is a different team in most seasons (2018's champion was the 5 seed).
///
/// Deliberately does not use `is_consolation` to find the title game: 2018 week 16
/// has two matchups both flagged `is_playoffs=1, is_consolation=0`, only one of
/// which is the final.
pub fn derive_champions(rows: &[StandingsRow]) -> Champions {
    let by_rank = |r: i64| {
        rows.iter()
            .find(|x| x.team.rank == r)
            .map(|x| x.team.name.clone())
            .unwrap_or_default()
    };
    Champions {
        champion: by_rank(1),
        runner_up: by_rank(2),
        top_seed: rows
            .iter()
            .find(|x| x.playoff_seed == 1)
            .map(|x| x.team.name.clone())
            .unwrap_or_default(),
        // Toilet bowl goes to whoever finished last. Take the max rank rather
        // than the last element so this holds regardless of sort order, and use
        // `last()` on ties so it matches the bottom of the rendered table.
        toilet_winner: rows
            .iter()
            .max_by_key(|x| x.team.rank)
            .map(|x| x.team.name.clone())
            .unwrap_or_default(),
    }
}

/// Name of a round given how many rounds remain after it (0 = the final).
fn round_name(from_end: usize) -> String {
    match from_end {
        0 => "Final".to_string(),
        1 => "Semifinal".to_string(),
        2 => "Quarterfinal".to_string(),
        n => format!("Round of {}", 2usize.pow(n as u32 + 1)),
    }
}

/// Derive the championship bracket by walking BACKWARDS from the final.
///
/// Yahoo gives no reliable way to tell a title-path game from a consolation game:
/// `is_consolation` is 0 even for games that are plainly consolation (2018 week 16
/// has two games both flagged `is_playoffs=1, is_consolation=0`), and every playoff
/// week carries the same number of matchups because both brackets run in parallel.
///
/// So we start from the one game we can identify with certainty — the last playoff
/// week's game containing the champion — and keep, in each earlier week, only the
/// games involving teams already known to be in the bracket. Teams with a first-round
/// bye simply appear for the first time in a later round, which needs no special case.
pub fn derive_bracket(
    weeks: &std::collections::BTreeMap<String, Vec<Matchup>>,
    champion: &str,
) -> Option<crate::model::Bracket> {
    use crate::model::{Bracket, BracketGame};

    if champion.is_empty() {
        return None;
    }
    // Week keys are strings; order them NUMERICALLY, not lexically.
    let mut ordered: Vec<(i64, &Vec<Matchup>)> = weeks
        .iter()
        .filter_map(|(k, v)| k.parse::<i64>().ok().map(|n| (n, v)))
        .collect();
    ordered.sort_by_key(|(n, _)| *n);
    let (final_week, final_games) = ordered.last()?;

    let has = |m: &Matchup, name: &str| m.teams.iter().any(|t| t.name == name);

    // The final is the last playoff week's game featuring the champion.
    let final_idx = final_games.iter().position(|m| has(m, champion))?;
    let mut frontier: Vec<String> = final_games[final_idx]
        .teams
        .iter()
        .map(|t| t.name.clone())
        .collect();

    // Collected newest-first, then reversed so the output reads earliest round first.
    let mut rounds: Vec<(i64, Vec<Matchup>)> =
        vec![(*final_week, vec![final_games[final_idx].clone()])];

    for (week, games) in ordered.iter().rev().skip(1) {
        let keep: Vec<Matchup> = games
            .iter()
            .filter(|m| m.teams.iter().any(|t| frontier.contains(&t.name)))
            .cloned()
            .collect();
        if keep.is_empty() {
            continue;
        }
        for m in &keep {
            for t in &m.teams {
                if !frontier.contains(&t.name) {
                    frontier.push(t.name.clone());
                }
            }
        }
        rounds.push((*week, keep));
    }
    rounds.reverse();

    // Assign ids and round labels, then wire each game to the next-round game its
    // winner turns up in.
    let total = rounds.len();
    let mut games: Vec<BracketGame> = Vec::new();
    let mut per_round: Vec<Vec<usize>> = Vec::with_capacity(total);
    for (ri, (week, ms)) in rounds.iter().enumerate() {
        let mut idxs = Vec::with_capacity(ms.len());
        for (gi, m) in ms.iter().enumerate() {
            idxs.push(games.len());
            games.push(BracketGame {
                id: format!("W{week}G{}", gi + 1),
                week: *week,
                round: round_name(total - 1 - ri),
                teams: m.teams.clone(),
                advances_to: None,
            });
        }
        per_round.push(idxs);
    }

    for ri in 0..total.saturating_sub(1) {
        let next = per_round[ri + 1].clone();
        for &gi in &per_round[ri] {
            let winner = games[gi]
                .teams
                .iter()
                .find(|t| t.is_winner)
                .map(|t| t.name.clone());
            let Some(winner) = winner else { continue };
            if let Some(&ni) = next
                .iter()
                .find(|&&ni| games[ni].teams.iter().any(|t| t.name == winner))
            {
                games[gi].advances_to = Some(games[ni].id.clone());
            }
        }
    }

    Some(Bracket { games })
}

/// Build a `Season` from a directory of harvested v2 payloads.
///
/// Files are named by `harvest_v2.py`:
///   `<season>-<league_key>-standings.json`
///   `<season>-<league_key>-scoreboard-wk<NN>.json`
///
/// Only standings and matchups are filled here. Draft picks are NOT touched --
/// the caller merges them from the existing rendered-page pipeline, which remains
/// the only source for them.
pub fn from_v2_dir(dir: &std::path::Path, season: u32, league_key: &str) -> Result<Season> {
    let mut s = Season {
        season,
        ..Default::default()
    };

    let standings_path = dir.join(format!("{season}-{league_key}-standings.json"));
    let text = std::fs::read_to_string(&standings_path)
        .with_context(|| format!("reading {}", standings_path.display()))?;
    let rows = parse_standings(&text)?;
    let teams: Vec<Team> = rows.iter().map(|r| r.team.clone()).collect();
    s.teams.teams = teams.clone();
    s.standings.teams = teams;
    s.champions = Some(derive_champions(&rows));

    // Weeks are whatever the harvest actually wrote; the range differs per season
    // (2018 ran weeks 3-16, later seasons 1-17), so discover rather than assume.
    let mut weeks: Vec<(i64, WeekScores)> = Vec::new();
    for entry in std::fs::read_dir(dir).with_context(|| format!("reading {}", dir.display()))? {
        let path = entry?.path();
        let Some(fname) = path.file_name().and_then(|f| f.to_str()) else {
            continue;
        };
        let prefix = format!("{season}-{league_key}-scoreboard-wk");
        if !fname.starts_with(&prefix) || !fname.ends_with(".json") {
            continue;
        }
        let text = std::fs::read_to_string(&path)
            .with_context(|| format!("reading {}", path.display()))?;
        let ws = parse_scoreboard(&text)
            .with_context(|| format!("parsing {}", path.display()))?;
        weeks.push((ws.week, ws));
    }
    weeks.sort_by_key(|(w, _)| *w);

    for (week, ws) in weeks {
        // playoffs.weeks holds ONLY playoff games, since that is what the bracket
        // renders; the full week-by-week record lives in `matchups`.
        let playoff_games: Vec<Matchup> = ws
            .matchups
            .iter()
            .zip(&ws.is_playoffs)
            .filter(|(_, p)| **p)
            .map(|(m, _)| m.clone())
            .collect();
        if !playoff_games.is_empty() {
            s.playoffs.weeks.insert(week.to_string(), playoff_games);
        }
        s.matchups.insert(week.to_string(), ws.matchups);
    }

    if let Some(c) = &s.champions {
        s.bracket = derive_bracket(&s.playoffs.weeks, &c.champion);
    }

    Ok(s)
}
