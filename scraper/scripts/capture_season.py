#!/usr/bin/env python3
"""PHF capture tool — drives a logged-in Edge (CDP) to capture rendered Yahoo Fantasy
pages for ONE historical season, via IN-APP NAV CLICKS (direct URL nav 404s for
matchups/scoreboard). Saves innerText + table HTML to dump/.

Ban-safe: never logs in, never prompts credentials, sequential with human-like waits.
Anti-ban: observes only; fires no extra requests.

Usage:
  uv run --with websocket-client python3 scripts/capture_season.py <edge> <year> <league_id> [outdir]

Example:
  uv run --with websocket-client python3 scripts/capture_season.py http://127.0.0.1:9222 2025 484479
"""
import json
import os
import re
import sys
import time
import urllib.request
from websocket import create_connection

# in-app nav labels -> file suffix
VIEWS = {
    "Standings": "standings",
    "Draft Results": "draftresults",
    "Matchups": "matchups",
}


def connect(base):
    ver = json.load(urllib.request.urlopen(f"{base}/json/version", timeout=10))
    return create_connection(ver["webSocketDebuggerUrl"], timeout=90)


_SEND_ID = [0]


def send(conn, method, params=None, sid=None, timeout=40):
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


def capture_view(conn, sid, year, lid, label, suffix, outdir):
    # Click the in-app nav link. Prefer links whose href is league-scoped
    # (contains /f1/<league>) so we don't grab the global NFL nav. Try several
    # label variants since Yahoo's nav text varies (e.g. "Matchups" vs "Matchup").
    label_variants = [label, label.rstrip("s"), label + "s", label.replace(" Results", "")]
    click = f"""(() => {{
      const links=[...document.querySelectorAll('a')];
      const leaguePath='/f1/{lid}';
      // 1) league-scoped link whose text matches a variant
      let el=links.find(a => a.getAttribute('href') && a.getAttribute('href').includes(leaguePath)
                          && ({label_variants!r}).some(v => a.textContent.trim()===v));
      // 2) any league-scoped link with a matching variant substring
      if(!el) el=links.find(a => a.getAttribute('href') && a.getAttribute('href').includes(leaguePath)
                          && ({label_variants!r}).some(v => a.textContent.trim().includes(v)));
      // 3) any link with matching text (fallback)
      if(!el) el=links.find(a => ({label_variants!r}).some(v => a.textContent.trim()===v));
      if(!el) return 'NO_LINK:'+{label!r};
      el.click();
      return 'CLICKED:'+el.getAttribute('href');
    }})()"""
    r = send(conn, "Runtime.evaluate", {"expression": click, "returnByValue": True}, sid)
    clicked = (r.get("result", {}) or {}).get("value", "")
    print(f"  [{label}] {clicked}")
    time.sleep(11)
    txt = send(conn, "Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True}, sid)
    text = (txt.get("result", {}).get("value", "") or "")
    fn = f"{outdir}/{year}-{lid}-{suffix}.innerText.txt"
    with open(fn, "w") as f:
        f.write(text)
    # also dump the standings table HTML when present (for parser tuning)
    tbl = send(conn, "Runtime.evaluate", {"expression":
        "(()=>{const t=document.querySelector('#standings-table table')||document.querySelector('table');"
        "return t?t.outerHTML.slice(0,6000):'';})()", "returnByValue": True}, sid).get("result", {}).get("value", "")
    if tbl:
        with open(f"{outdir}/{year}-{lid}-{suffix}.table1.html", "w") as f:
            f.write(tbl)
    print(f"  -> {fn} ({len(text)}c)")


def main():
    base = sys.argv[1]
    year = sys.argv[2]
    lid = sys.argv[3]
    outdir = sys.argv[4] if len(sys.argv) > 4 else "dump"
    os.makedirs(outdir, exist_ok=True)
    home = f"https://football.fantasysports.yahoo.com/{year}/f1/{lid}"
    conn = connect(base)
    tid = send(conn, "Target.createTarget", {"url": "about:blank"})["targetId"]
    sid = send(conn, "Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
    send(conn, "Page.enable", {}, sid)
    send(conn, "Runtime.enable", {}, sid)
    send(conn, "Page.navigate", {"url": home}, sid)
    time.sleep(9)
    for label, suffix in VIEWS.items():
        try:
            capture_view(conn, sid, year, lid, label, suffix, outdir)
        except Exception as e:
            import traceback
            print(f"  [{label}] ERROR {e}")
            traceback.print_exc()
    send(conn, "Target.closeTarget", {"targetId": tid})
    conn.close()
    print("DONE. Files in", outdir)


if __name__ == "__main__":
    main()
