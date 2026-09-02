#!/usr/bin/env python3
"""Harvest Pine Hills league data from the Yahoo Fantasy v2 read-only API.

Uses the `pub-api-ro.fantasysports.yahoo.com` host discovered by observing the
league page's own traffic (see probe_v2.py). Requests are issued from the fantasy
page's JS context so session cookies and Origin match what Yahoo expects.

Fetches, per season: one `standings` call, plus a `scoreboard;week=N` and a
`teams/roster;week=N/players/stats` call for each week in the league's real
start_week..end_week range (2018 starts at week 3). Roster payloads are large
(~1.8 MB per week), so expect dump/v2 to reach a few hundred MB. It is
gitignored.

RESUMABLE: an output file that already exists and parses as JSON is skipped, so a
re-run after an interruption only fetches what is missing.

Read-only GETs, strictly sequential, with spacing between calls.

Usage:
  uv run --with websocket-client python3 scripts/harvest_v2.py <edge> <outdir> [league_name]
"""
import json
import os
import sys
import time
import urllib.request

from websocket import create_connection

API_BASE = "https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2"
ORIGIN_PAGE = "https://football.fantasysports.yahoo.com/f1/447010"
DELAY = 5.0          # seconds between requests
SKIP_SEASONS = {"2026"}   # current season, still in progress

_SEND_ID = [0]


def send(conn, method, params=None, sid=None, timeout=60):
    _SEND_ID[0] += 1
    msg = {"id": _SEND_ID[0], "method": method, "params": params or {}}
    if sid:
        msg["sessionId"] = sid
    conn.send(json.dumps(msg))
    dl = time.time() + timeout
    while time.time() < dl:
        try:
            raw = conn.recv()
        except Exception:
            continue
        if not raw:
            continue
        try:
            m = json.loads(raw)
        except Exception:
            continue
        if m.get("id") == msg["id"]:
            return m.get("result", {})
    return {}


def fetch(conn, sid, url):
    expr = """(async () => {
      try {
        const r = await fetch(%s, { credentials: 'include' });
        const t = await r.text();
        return JSON.stringify({ status: r.status, len: t.length, body: t });
      } catch (e) {
        return JSON.stringify({ status: -1, len: 0, body: 'FETCH_THREW: ' + e });
      }
    })()""" % json.dumps(url)
    r = send(conn, "Runtime.evaluate",
             {"expression": expr, "returnByValue": True, "awaitPromise": True}, sid, timeout=90)
    val = (r.get("result", {}) or {}).get("value")
    if not val:
        return {"status": -2, "len": 0, "body": ""}
    return json.loads(val)


def already_have(path):
    """True if this file exists and is complete JSON (guards truncated writes)."""
    if not os.path.exists(path):
        return False
    try:
        with open(path) as f:
            json.load(f)
        return True
    except Exception:
        return False


def get(conn, sid, path, out_path, stats):
    if already_have(out_path):
        print(f"   skip (have) {os.path.basename(out_path)}")
        stats["skipped"] += 1
        return True
    url = f"{API_BASE}/{path}?format=json_f"
    res = fetch(conn, sid, url)
    status, body = res.get("status"), res.get("body", "")
    if status != 200:
        print(f"   FAIL {status} {path}")
        stats["failed"].append((path, status))
        time.sleep(DELAY)
        return False
    try:
        json.loads(body)
    except Exception as e:
        print(f"   BAD JSON {path}: {e}")
        stats["failed"].append((path, "bad-json"))
        time.sleep(DELAY)
        return False
    with open(out_path, "w") as f:
        f.write(body)
    print(f"   ok {len(body):>8}b -> {os.path.basename(out_path)}")
    stats["fetched"] += 1
    time.sleep(DELAY)
    return True


def main():
    base = sys.argv[1]
    outdir = sys.argv[2]
    want_name = sys.argv[3] if len(sys.argv) > 3 else "Pine Hills"
    os.makedirs(outdir, exist_ok=True)

    ver = json.load(urllib.request.urlopen(f"{base}/json/version", timeout=10))
    conn = create_connection(ver["webSocketDebuggerUrl"], timeout=120)
    tid = send(conn, "Target.createTarget", {"url": "about:blank"})["targetId"]
    sid = send(conn, "Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
    send(conn, "Page.enable", {}, sid)
    send(conn, "Runtime.enable", {}, sid)
    send(conn, "Page.navigate", {"url": ORIGIN_PAGE}, sid)
    time.sleep(9)

    stats = {"fetched": 0, "skipped": 0, "failed": []}

    # 1) League index (cached on disk like everything else).
    idx_path = os.path.join(outdir, "leagues.json")
    if not get(conn, sid, "users;use_login=1/games;game_codes=nfl/leagues", idx_path, stats):
        print("FATAL: could not fetch league index")
        sys.exit(1)

    with open(idx_path) as f:
        doc = json.load(f)
    seasons = []
    for g in doc["fantasy_content"]["users"][0]["user"].get("games", []):
        g = g.get("game", g)
        season = str(g.get("season"))
        if season in SKIP_SEASONS:
            continue
        for l in g.get("leagues", []):
            l = l.get("league", l)
            if l.get("name") != want_name:
                continue
            seasons.append({
                "season": season,
                "key": l.get("league_key"),
                "start": int(l.get("start_week") or 1),
                "end": int(l.get("end_week") or 17),
            })
    seasons.sort(key=lambda s: s["season"])

    total = len(seasons) + 2 * sum(s["end"] - s["start"] + 1 for s in seasons)
    print(f">> {len(seasons)} seasons of {want_name!r}; {total} requests max (cached ones skipped)")

    for s in seasons:
        print(f">> {s['season']} {s['key']} weeks {s['start']}-{s['end']}")
        get(conn, sid, f"league/{s['key']}/standings",
            os.path.join(outdir, f"{s['season']}-{s['key']}-standings.json"), stats)
        for wk in range(s["start"], s["end"] + 1):
            get(conn, sid, f"league/{s['key']}/scoreboard;week={wk}",
                os.path.join(outdir, f"{s['season']}-{s['key']}-scoreboard-wk{wk:02d}.json"), stats)
            # Every team's roster AND that week's player points in one response.
            # Shape confirmed by scripts/probe_rosters.py; ~1.8 MB per week.
            get(conn, sid,
                f"league/{s['key']}/teams/roster;week={wk}/players/stats;type=week;week={wk}",
                os.path.join(outdir, f"{s['season']}-{s['key']}-rosters-wk{wk:02d}.json"), stats)

    send(conn, "Target.closeTarget", {"targetId": tid})
    conn.close()
    print(f"\nDONE. fetched={stats['fetched']} skipped={stats['skipped']} failed={len(stats['failed'])}")
    for p, why in stats["failed"]:
        print(f"  FAILED {why} {p}")
    if stats["failed"]:
        print("Re-run to retry only the failures (successful files are cached).")


if __name__ == "__main__":
    main()
