#!/usr/bin/env python3
"""One-shot probe: does the nested roster+stats endpoint answer?

Reuses harvest_v2's CDP plumbing so the request comes from the fantasy page's
own JS context (session cookies + Origin match what Yahoo expects). Read-only
GET, two requests maximum, then it exits.

Usage:
  uv run --with websocket-client python3 scripts/probe_rosters.py <edge>

RESULT (confirmed 2026-09-01 against 2024 week 1 — parse_v2::parse_rosters
parses against this):
  winning path: league/<key>/teams/roster;week=N/players/stats;type=week;week=N
  players at:   /fantasy_content/league/teams/<i>/team/roster/players/<j>/player
  payload size: 1.83 MB for one week of a 12-team league (182 player rows)

  Fields, all present:
    team.name                          "Kamara's a b*tch"
    team.roster.week                   1          (echoed per team)
    player.name.full                   "Jalen Hurts"
    player.primary_position            "QB"
    player.selected_position.position  "QB" | "W/R/T" | "BN" | "IR"
    player.player_points.total         "18.42"    (a STRING; as_f64 handles it)

  Collection entries are wrapped one level deep (`{"team": {...}}`,
  `{"player": {...}}`), so unwrap_entry applies to both.
"""
import json
import os
import sys
import time
import urllib.request

from websocket import create_connection

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harvest_v2 import API_BASE, ORIGIN_PAGE, fetch, send

# 2024 Pine Hills. Its standings payload is already cached in dump/v2, so the
# key is known-good rather than guessed.
LEAGUE_KEY = "449.l.489811"
WEEK = 1

CANDIDATES = [
    # Preferred: roster and weekly points in ONE response.
    f"league/{LEAGUE_KEY}/teams/roster;week={WEEK}/players/stats;type=week;week={WEEK}",
    # Fallback: roster only. If this is the one that answers, the harvest needs
    # a second call per week for points.
    f"league/{LEAGUE_KEY}/teams/roster;week={WEEK}",
]


def sample_player(doc):
    """Walk to the first player object and return (pointer, player) or (None, None)."""
    teams = doc.get("fantasy_content", {}).get("league", {}).get("teams")
    if not isinstance(teams, list) or not teams:
        return None, None
    team = teams[0].get("team", teams[0])
    players = (team.get("roster") or {}).get("players")
    if not isinstance(players, list) or not players:
        return None, None
    player = players[0].get("player", players[0])
    return "/fantasy_content/league/teams/0/team/roster/players/0/player", player


def main():
    base = sys.argv[1]
    outdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dump", "v2")
    os.makedirs(outdir, exist_ok=True)

    ver = json.load(urllib.request.urlopen(f"{base}/json/version", timeout=10))
    conn = create_connection(ver["webSocketDebuggerUrl"], timeout=120)
    tid = send(conn, "Target.createTarget", {"url": "about:blank"})["targetId"]
    sid = send(conn, "Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
    send(conn, "Page.enable", {}, sid)
    send(conn, "Runtime.enable", {}, sid)
    send(conn, "Page.navigate", {"url": ORIGIN_PAGE}, sid)
    time.sleep(9)

    for path in CANDIDATES:
        url = f"{API_BASE}/{path}?format=json_f"
        res = fetch(conn, sid, url)
        status, body = res.get("status"), res.get("body", "")
        print(f"{status} {len(body):>8}b  {path}")
        if status != 200:
            time.sleep(5)
            continue
        doc = json.loads(body)
        pointer, player = sample_player(doc)
        if not player:
            print("   200 but no players found — dumping top-level keys:")
            print("  ", list(doc.get("fantasy_content", {}).keys()))
            time.sleep(5)
            continue
        out = os.path.join(outdir, f"probe-rosters-wk{WEEK:02d}.json")
        with open(out, "w") as f:
            f.write(body)
        print(f"OK {path}")
        print(f"   players at: {pointer}")
        print("   name       :", (player.get("name") or {}).get("full"))
        print("   position   :", player.get("primary_position"))
        print("   slot       :", (player.get("selected_position") or {}).get("position"))
        print("   points     :", (player.get("player_points") or {}).get("total"))
        print(f"   saved -> {out}")
        break
    else:
        print("FAIL: neither candidate returned usable roster data")
        sys.exit(1)

    send(conn, "Target.closeTarget", {"targetId": tid})
    conn.close()


if __name__ == "__main__":
    main()
