#!/usr/bin/env python3
"""Capture Yahoo Fantasy API response bodies via CDP Network interception.

Tuning/inspection tool (not the scraper). Connects to the user's logged-in
Edge/Chrome on the CDP port, opens a tab, navigates to a Yahoo Fantasy URL,
enables the Network domain, and saves every JSON response body whose URL looks
like a fantasy API call. This lets us learn the EXACT JSON shape Yahoo returns
so the Rust scraper can parse clean structured data instead of guessing at
hashed-class DOM.

Ban-safe: we only OBSERVE responses the page already fetches. We fire no extra
HTTP requests of our own.

Run with uv (no stray venv):
  uv run --with websocket-client python3 scripts/capture_api.py \
    http://127.0.0.1:9222 \
    https://football.fantasysports.yahoo.com/f1/447010/2016/standings \
    dump 2016-standings
"""
import base64
import json
import sys
import time
import urllib.request
from urllib.parse import urlparse

from websocket import create_connection


def main():
    endpoint = sys.argv[1]
    page_url = sys.argv[2]
    out_dir = sys.argv[3]
    tag = sys.argv[4] if len(sys.argv) > 4 else "capture"
    import os
    os.makedirs(out_dir, exist_ok=True)

    # Resolve ws endpoint from http(s) debugger URL.
    if endpoint.startswith("http"):
        with urllib.request.urlopen(endpoint.rstrip("/") + "/json/version", timeout=10) as r:
            ws = json.load(r)["webSocketDebuggerUrl"]
    else:
        ws = endpoint
    print(f">> connecting to {ws}")

    conn = create_connection(ws, timeout=60)
    conn.settimeout(60)
    msg_id = 0
    sessions = {}  # targetId -> sessionId

    def send(method, params=None, sid=None):
        nonlocal msg_id
        msg_id += 1
        msg = {"id": msg_id, "method": method, "params": params or {}}
        if sid:
            msg["sessionId"] = sid
        conn.send(json.dumps(msg))
        return msg_id

    # 1) create a fresh tab; the targetId comes back in the RESULT of this send.
    create_id = send("Target.createTarget", {"url": "about:blank"})
    target_id = None
    session_id = None

    # Process the handshake replies, then drive the session.
    bodies = {}      # requestId -> url
    captured = 0
    deadline = time.time() + 50
    attached = False
    while time.time() < deadline:
        try:
            raw = conn.recv()
        except Exception:
            continue
        if not raw:
            continue
        msg = json.loads(raw)
        method = msg.get("method")
        params = msg.get("params", {})
        sid = msg.get("sessionId")
        rid = msg.get("id")

        # Grab targetId from createTarget result, then attach to it.
        if rid == create_id and msg.get("result"):
            target_id = msg["result"].get("targetId")
            if target_id:
                send("Target.attachToTarget", {"targetId": target_id, "flatten": True})

        elif method == "Target.attachedToTarget":
            session_id = params.get("sessionId")
            # Enable Network + navigate ON the session.
            send("Network.enable", {}, sid=session_id)
            send("Page.enable", {}, sid=session_id)
            send("Page.navigate", {"url": page_url}, sid=session_id)
            attached = True

        elif method == "Network.responseReceived":
            r = params.get("requestId")
            resp = params.get("response", {})
            bodies[r] = resp.get("url", "")
            print(f"   [net] {resp.get('status','?')} {resp.get('url','')[:110]}")

        elif method == "Network.loadingFinished":
            r = params.get("requestId")
            url = bodies.get(r, "")
            if "fantasy" in url or "yahoo" in url:
                send("Network.getResponseBody", {"requestId": r}, sid=session_id)

        elif rid and method is None and "result" in msg and "body" in msg["result"]:
            res = msg["result"]
            b64 = res["body"]
            data = base64.b64decode(b64) if res.get("base64Encoded") else b64.encode()
            text = data.decode("utf-8", "replace")
            if text.lstrip().startswith("{") or text.lstrip().startswith("["):
                fn = os.path.join(out_dir, f"{tag}.api.{captured}.json")
                with open(fn, "w") as f:
                    f.write(text)
                captured += 1
                print(f"   captured [{captured}] ({len(text)} bytes) -> {fn}")

        if not attached and time.time() > deadline - 5:
            print("   (warning: never attached to target; retry)")

    print(f">> done. captured {captured} JSON response(s) in {out_dir}")
    try:
        conn.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
