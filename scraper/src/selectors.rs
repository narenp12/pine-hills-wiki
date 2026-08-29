//! Selector config loaded from selectors.toml at runtime (no recompile to tune).

use anyhow::Result;
use serde::Deserialize;
use std::collections::HashMap;
use std::path::Path;

#[derive(Debug, Deserialize, Default)]
pub struct LeagueCfg {
    pub url_template: String,
    #[serde(default)]
    pub season_ids: HashMap<u32, String>,
}

#[derive(Debug, Deserialize, Default)]
pub struct TableCfg {
    #[serde(default)]
    pub table: String,
    #[serde(default)]
    pub team_col: String,
    #[serde(default)]
    pub owner_col: String,
    #[serde(default)]
    pub wins_col: String,
    #[serde(default)]
    pub losses_col: String,
    #[serde(default)]
    pub pf_col: String,
    #[serde(default)]
    pub pa_col: String,
    #[serde(default)]
    pub rank_col: String,
    #[serde(default)]
    pub pick_col: String,
    #[serde(default)]
    pub round_col: String,
    #[serde(default)]
    pub player_col: String,
    #[serde(default)]
    pub pos_col: String,
    #[serde(default)]
    pub week_col: String,
    #[serde(default)]
    pub opp_col: String,
    #[serde(default)]
    pub score_col: String,
    #[serde(default)]
    pub opp_score_col: String,
    #[serde(default)]
    pub win_col: String,
}

#[derive(Debug, Deserialize, Default)]
pub struct OptsCfg {
    #[serde(default = "default_playoff_week")]
    pub playoff_week: u32,
    #[serde(default = "default_final_week")]
    pub final_week: u32,
}

fn default_playoff_week() -> u32 { 14 }
fn default_final_week() -> u32 { 18 }

#[derive(Debug, Deserialize, Default)]
pub struct Selectors {
    #[serde(default)]
    pub league: LeagueCfg,
    #[serde(default)]
    pub standings: TableCfg,
    #[serde(default)]
    pub draft: TableCfg,
    #[serde(default)]
    pub matchups: TableCfg,
    #[serde(default)]
    pub roster: TableCfg,
    #[serde(default)]
    pub opts: OptsCfg,
}

impl Selectors {
    /// Split a comma-separated selector list into candidate selectors.
    pub fn table_selectors(&self, raw: &str) -> Vec<String> {
        raw.split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect()
    }
}

pub fn load(path: &Path) -> Result<Selectors> {
    let txt = std::fs::read_to_string(path)?;
    let sel: Selectors = toml::from_str(&txt)?;
    Ok(sel)
}
