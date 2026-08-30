"""
Generate Quartz Markdown wiki pages from raw/ JSON (produced by extract.py).

Builds:
  content/seasons/<year>-season.md        season page w/ standings, playoffs, rosters
  content/rosters/<year>/<team>-post-draft.md
  content/rosters/<year>/<team>-end-of-season.md
  content/teams/<team>.md                 franchise page w/ season log + roster links
  content/records/index.md                (recomputed aggregate)
  content/draft/<year>-draft.md           pick-by-pick

Run:  python scripts/generate.py
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
CONTENT = ROOT / "content"


# ---------- helpers -------------------------------------------------------
def slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s or "team"


def load_raw():
    seasons = {}
    for f in sorted(RAW.glob("*.json")):
        try:
            d = json.loads(f.read_text())
            seasons[int(d["season"])] = d
        except Exception as e:  # noqa: BLE001
            print(f"  ! skipping {f.name}: {e}")
    return seasons


def wikilink(title: str, label=None) -> str:
    return f"[[{title}]]" if label is None else f"[[{title}|{label}]]"


# ---------- sections ------------------------------------------------------
def roster_block(team_name, owner, snapshot, roster_data):
    """Render a starter/bench table from yfpy roster data (best effort)."""
    lines = [
        f"**Team:** {team_name}",
        f"**Owner:** {owner}",
        f"**Snapshot:** {snapshot}",
        "",
        "| Position | Player | Notes |",
        "|----------|--------|-------|",
    ]
    players = []
    if isinstance(roster_data, dict):
        players = roster_data.get("players", roster_data.get("roster", []))
    if isinstance(players, dict):
        players = players.get("players", [])
    if not isinstance(players, list):
        players = []
    for p in players:
        if isinstance(p, dict):
            name = p.get("name", p.get("player_name", p.get("full_name", "Unknown")))
            pos = p.get("position", p.get("display_position", "—"))
            line = f"| {pos} | {name} | _TBD_ |"
        else:
            line = f"| — | {p} | _TBD_ |"
        lines.append(line)
    if not players:
        lines.append("| — | _No data pulled_ | — |")
    return "\n".join(lines)


def gen_season(year, d, all_teams):
    standings = d.get("standings") or {}
    teams = d.get("teams") or []
    draft = d.get("draft") or {}
    weeks = d.get("weeks", {})
    playoffs = d.get("playoffs", {}) or {}

    # post-draft rosters = weeks["1"]["rosters"], end-of = last week with rosters
    post = weeks.get("1", {}).get("rosters", {})
    end = {}
    for wk in ("18", "17", "16", "15"):
        if wk in weeks and weeks[wk].get("rosters"):
            end = weeks[wk]["rosters"]
            break

    roster_rows = []
    for tk in post.keys() | end.keys():
        tname = all_teams.get(tk, {}).get("name", tk)
        owner = all_teams.get(tk, {}).get("owner", "Unknown")
        pd_link = wikilink(f"{year} {slug(tname)} Post-Draft", "Post-Draft")
        eo_link = wikilink(f"{year} {slug(tname)} End-of-Season", "End-of-Season")
        roster_rows.append(f"| {tname} | {pd_link} | {eo_link} |")

    champ = "TBD"
    try:
        # standings structure varies; best effort
        s = standings
        if isinstance(s, dict):
            s = s.get("standings", s)
        if isinstance(s, dict) and "teams" in s:
            first = s["teams"][0]
            champ = first.get("name", champ)
    except Exception:  # noqa: BLE001
        pass

    md = f"""---
title: "{year} Season"
description: "Pine Hills Fantasy Football League — {year} season."
season: {year}
year: {year}
---

# 🏈 {year} Season

**Champion:** {champ}
**Runner-Up:** _TBD_
**Regular Season Top Seed:** _TBD_
**Toilet Bowl Winner:** _TBD_

## Final Standings

> Auto-generated from Yahoo. Edit `_TBD_` fields and add narrative.

| Rank | Team | Owner | W–L | PF | PA | Playoff Seed |
|------|------|-------|-----|----|----|--------------|
"""

    # standings table rows
    try:
        st = standings
        if isinstance(st, dict):
            st = st.get("standings", st)
        team_list = st.get("teams", []) if isinstance(st, dict) else []
        for i, t in enumerate(team_list, 1):
            # Show Yahoo's REAL final rank, not the row position. Yahoo can rank two
            # teams equally (2020 has two rank-7 teams), so positional numbering
            # misreported a team's finish.
            rank = t.get("rank") or i
            md += f"| {rank} | {t.get('name','?')} | {t.get('owner','?')} | {t.get('wins',0)}–{t.get('losses',0)} | {t.get('points_for','?')} | {t.get('points_against','?')} | {i if i<=4 else '—'} |\n"
    except Exception:  # noqa: BLE001
        md += "| _TBD_ | _TBD_ | _TBD_ | 0–0 | 0 | 0 | — |\n"

    # ---- Playoff bracket (data-driven from Yahoo matchups) ----
    po_weeks = playoffs.get("weeks", {}) if isinstance(playoffs, dict) else {}
    if po_weeks:
        md += "\n## Playoff Bracket\n\n```mermaid\nflowchart TD\n"
        # assign node ids per (week, matchup index)
        winner_nodes = []
        for wk in sorted(po_weeks, key=int):
            mus = po_weeks[wk]
            if not isinstance(mus, list):
                continue
            for i, mu in enumerate(mus):
                teams = mu.get("teams", []) if isinstance(mu, dict) else []
                nid = f"w{wk}m{i}"
                labels = []
                for t in teams:
                    nm = t.get("name", "Unknown")
                    sc = t.get("score")
                    mark = "🏆" if t.get("is_winner") else ""
                    labels.append(f"{nm} ({sc}) {mark}".strip())
                node_text = " vs ".join(labels) if labels else f"Matchup {i+1}"
                md += f"    {nid}[\"{node_text}\"]\n"
                # track winner for chaining to next round
                for t in teams:
                    if t.get("is_winner"):
                        winner_nodes.append((wk, nid, t.get("name", "Unknown")))
        # chain winners forward: a winner of week N feeds an implicit next round.
        # Simple linear chaining: connect each winner node to the next week's first node.
        prev = None
        for wk, nid, _ in sorted(set((w, n, nm) for w, n, nm in winner_nodes), key=lambda x: int(x[0])):
            if prev:
                md += f"    {prev} --> {nid}\n"
            prev = nid
        md += "```\n\n"
        # Also a plain-text weekly results table (renders even if mermaid is off)
        md += "### Playoff Results by Week\n\n"
        for wk in sorted(po_weeks, key=int):
            mus = po_weeks[wk]
            if not isinstance(mus, list):
                continue
            md += f"**Week {wk}**\n\n| Matchup | Team | Score | Winner |\n|---------|------|-------|--------|\n"
            for mi, mu in enumerate(mus, 1):
                teams = mu.get("teams", []) if isinstance(mu, dict) else []
                for t in teams:
                    nm = t.get("name", "Unknown")
                    sc = t.get("score", "—")
                    w = "✅" if t.get("is_winner") else ""
                    md += f"| {mi} | {nm} | {sc} | {w} |\n"
            md += "\n"
    else:
        md += "\n## Playoff Bracket\n\n```mermaid\nflowchart LR\n"
        md += "    S1[Seed 1] --> W1\n    S4[Seed 4] --> W1\n"
        md += "    S2[Seed 2] --> W2\n    S3[Seed 3] --> W2\n"
        md += "    W1 --> Champ[🏆 Champion]\n    W2 --> Champ\n```\n\n"

    md += "## Team Rosters\n\n"
    md += "| Team | Post-Draft Roster | End-of-Season Roster |\n|------|-------------------|----------------------|\n"
    md += "\n".join(roster_rows) + "\n\n"

    md += "## Awards\n\n"
    md += "- 🏆 **League Champion:** _TBD_\n- 💥 **Highest Single-Week Score:** _TBD_\n"
    md += "- 📉 **Lowest Single-Week Score:** _TBD_\n- 🔥 **Biggest Bust:** _TBD_\n"
    md += "- 🎯 **Best Draft Pick:** _TBD_\n- 🍗 **\"Poultry Controversy\" Nominee:** _TBD_\n\n"

    md += "## The Story of the Year\n\n_TBD — add the defining moments._\n\n"
    md += f"## Related\n\n- {wikilink('Seasons')} · {wikilink(f'{year} Draft')} · {wikilink('Teams')} · {wikilink('Records')} · {wikilink('Lore')}\n"
    return md


def gen_roster_page(year, team_key, team_name, owner, snapshot, roster_data):
    body = roster_block(team_name, owner, snapshot, roster_data)
    return f"""---
title: "{year} {team_name} — {snapshot} Roster"
description: "{year} {team_name} {snapshot.lower()} roster."
---

# 📋 {year} {team_name} — {snapshot} Roster

{body}

## Related

- {wikilink(f'{year} Season')} · {wikilink(team_name)} · {wikilink('Roster Template')}
"""


def gen_team_page(team_key, info, season_log):
    name = info.get("name", team_key)
    owner = info.get("owner", "Unknown")
    rows = []
    for year, (w, l, finish, po) in season_log.items():
        pd = wikilink(f"{year} {slug(name)} Post-Draft", "Post-Draft")
        eo = wikilink(f"{year} {slug(name)} End-of-Season", "End-of-Season")
        rows.append(f"| {year} | {w}–{l} | {finish} | {po} | {pd} | {eo} | _TBD_ |")
    md = f"""---
title: "{name}"
description: "Franchise history for {name} in the Pine Hills Fantasy Football League."
---

# 🏈 {name}

**Owner:** {owner}
**Joined:** _TBD_
**Status:** Active

## Franchise Summary

- **Championships:** _TBD_
- **Runner-Up Finishes:** _TBD_
- **Playoff Appearances:** _TBD_
- **All-Time Record:** _TBD_

## Season Log

| Year | W–L | Finish | Playoffs? | Post-Draft Roster | End-of-Season Roster | Note |
|------|-----|--------|-----------|-------------------|----------------------|------|
{"".join(rows)}

## Rivalries

| Opponent | H2H Record | Notable Meeting |
|----------|-----------|-----------------|
| _TBD_ | _TBD_–_TBD_ | _TBD_ |

## Signature Moments

_TBD._

## Related

- {wikilink('Teams')} · {wikilink('Seasons')} · {wikilink('Records')} · {wikilink('Lore')}
"""
    return md


def main():
    seasons = load_raw()
    if not seasons:
        print("No raw JSON found in raw/. Run scripts/extract.py first.")
        return

    (CONTENT / "seasons").mkdir(parents=True, exist_ok=True)
    (CONTENT / "rosters").mkdir(parents=True, exist_ok=True)
    (CONTENT / "teams").mkdir(parents=True, exist_ok=True)
    (CONTENT / "draft").mkdir(parents=True, exist_ok=True)

    all_teams = {}  # team_key -> {name, owner}
    season_logs = {}  # team_key -> {year: (w,l,finish,po)}

    for year in sorted(seasons):
        d = seasons[year]
        teams = d.get("teams") or []
        tlist = teams.get("teams", teams) if isinstance(teams, dict) else teams
        if isinstance(tlist, dict):
            tlist = [tlist]
        for t in (tlist or []):
            tk = t.get("team_key", t.get("key"))
            all_teams[tk] = {
                "name": t.get("name", tk),
                "owner": t.get("owner", t.get("manager", "Unknown")),
            }
            w = t.get("wins", 0)
            l = t.get("losses", 0)
            finish = t.get("rank", "TBD")
            po = "Yes" if int(t.get("rank", 99)) <= 4 else "No"
            season_logs.setdefault(tk, {})[year] = (w, l, finish, po)

        # season page
        sp = CONTENT / "seasons" / f"{year}-season.md"
        sp.write_text(gen_season(year, d, all_teams))
        print(f"  wrote {sp.relative_to(ROOT)}")

        # roster pages
        weeks = d.get("weeks", {})
        post = weeks.get("1", {}).get("rosters", {})
        end = {}
        for wk in ("18", "17", "16", "15"):
            if wk in weeks and weeks[wk].get("rosters"):
                end = weeks[wk]["rosters"]
                break
        rdir = CONTENT / "rosters" / str(year)
        rdir.mkdir(parents=True, exist_ok=True)
        for tk in post.keys() | end.keys():
            info = all_teams.get(tk, {"name": tk, "owner": "Unknown"})
            tname = info["name"]
            if tk in post:
                p = rdir / f"{slug(tname)}-post-draft.md"
                p.write_text(gen_roster_page(year, tk, tname, info["owner"], "Post-Draft", post[tk]))
            if tk in end:
                e = rdir / f"{slug(tname)}-end-of-season.md"
                e.write_text(gen_roster_page(year, tk, tname, info["owner"], "End-of-Season", end[tk]))
        print(f"  wrote {len(post)+len(end)} roster pages for {year}")

        # draft page
        draft = d.get("draft") or {}
        picks = draft.get("draft_results", draft.get("results", []))
        if isinstance(picks, dict):
            picks = picks.get("draft_results", [])
        dlines = ["| Overall | Round | Team | Player | Position |", "|---------|-------|------|--------|----------|"]
        if isinstance(picks, list):
            for p in picks:
                if isinstance(p, dict):
                    dlines.append(
                        f"| {p.get('pick','?')} | {p.get('round','?')} | {p.get('team','?')} | {p.get('player','?')} | {p.get('position','?')} |"
                    )
        dp = CONTENT / "draft" / f"{year}-draft.md"
        dp.write_text(
            f"---\ntitle: \"{year} Draft\"\ndescription: \"Pine Hills FF {year} draft board.\"\n---\n\n# 🎯 {year} Draft\n\n"
            + "\n".join(dlines)
            + f"\n\n## Related\n\n- {wikilink('Draft History')} · {wikilink(f'{year} Season')}\n"
        )
        print(f"  wrote {dp.relative_to(ROOT)}")

    # team pages
    for tk, info in all_teams.items():
        tp = CONTENT / "teams" / f"{slug(info['name'])}.md"
        tp.write_text(gen_team_page(tk, info, season_logs.get(tk, {})))
        print(f"  wrote {tp.relative_to(ROOT)}")

    print("Done generating Markdown.")


if __name__ == "__main__":
    main()
