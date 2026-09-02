#!/usr/bin/env python3
"""Query the Yahoo Fantasy v2 read-only API from inside a logged-in browser context.

Background: HANDOFF.md claimed v2 is "blocked in-session (CORS / gated)". A capture
of the 2024 league page disproved that -- the page itself successfully calls:

    https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/users;use_login=1/profile?format=json_f

Note the dedicated read-only host (`pub-api-ro`) and the `json_f` (flattened) format.
The earlier attempt used the wrong host, which is why it saw error shells.

Requests are issued from the fantasy page's JS context so the session cookies and
Origin match what Yahoo expects. Read-only GETs, sequential, human-like spacing.

Usage:
  uv run --with websocket-client python3 scripts/probe_v2.py <edge> <outdir> <tag> <path>...

Paths are appended to the pub-api-ro /fantasy/v2 base, e.g.:
  'users;use_login=1/games;game_codes=nfl/leagues'
  'league/449.l.489811/standings'
  'league/449.l.489811/scoreboard;week=1'
"""
import json
import os
import sys
import time
import urllib.request

from websocket import create_connection

API_BASE = "https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2"
# Any league page works; it only sets the JS origin for the fetch.
ORIGIN_PAGE = "https://football.fantasysports.yahoo.com/f1/447010"

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


def fetch(conn, sid, url):
    """Cross-origin fetch from the page context. pub-api-ro is a different host
    than the page, so cookies need credentials:'include'."""
    expr = """(async () => {
      try {
        const r = await fetch(%s, { credentials: 'include' });
        const t = await r.text();
        return JSON.stringify({
          status: r.status,
          ct: r.headers.get('content-type') || '',
          len: t.length,
          body: t
        });
      } catch (e) {
        return JSON.stringify({ status: -1, ct: '', len: 0, body: 'FETCH_THREW: ' + e });
      }
    })()""" % json.dumps(url)
    r = send(conn, "Runtime.evaluate",
             {"expression": expr, "returnByValue": True, "awaitPromise": True}, sid, timeout=60)
    val = (r.get("result", {}) or {}).get("value")
    if not val:
        return {"status": -2, "ct": "", "len": 0, "body": f"NO_RESULT: {r}"}
    return json.loads(val)


def main():
    base, outdir, tag = sys.argv[1], sys.argv[2], sys.argv[3]
    paths = sys.argv[4:]
    if not paths:
        print("no paths given", file=sys.stderr)
        sys.exit(2)
    os.makedirs(outdir, exist_ok=True)

    ver = json.load(urllib.request.urlopen(f"{base}/json/version", timeout=10))
    conn = create_connection(ver["webSocketDebuggerUrl"], timeout=90)
    tid = send(conn, "Target.createTarget", {"url": "about:blank"})["targetId"]
    sid = send(conn, "Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
    send(conn, "Page.enable", {}, sid)
    send(conn, "Runtime.enable", {}, sid)
    send(conn, "Page.navigate", {"url": ORIGIN_PAGE}, sid)
    time.sleep(9)

    for i, path in enumerate(paths):
        url = f"{API_BASE}/{path}?format=json_f"
        print(f">> GET {url}")
        res = fetch(conn, sid, url)
        body = res.get("body", "")
        print(f"   status={res.get('status')} ct={res.get('ct')} len={res.get('len')}")
        print(f"   head: {body[:180]!r}")
        safe = path.replace("/", "_").replace(";", "_").replace("=", "-")
        fn = os.path.join(outdir, f"{tag}.{i}.{safe}.json")
        with open(fn, "w") as f:
            f.write(body)
        print(f"   -> {fn}")
        time.sleep(6)

    send(conn, "Target.closeTarget", {"targetId": tid})
    conn.close()
    print("DONE.")


if __name__ == "__main__":
    main()
