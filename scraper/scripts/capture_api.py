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
import re
import sys
import time
import urllib.request
from urllib.parse import urlparse

from websocket import create_connection


_JSONP = re.compile(r"^[A-Za-z_$][\w$.]*\s*\(")


def strip_jsonp(text):
    """Unwrap `callback({...});` to `{...}` (see API_SHAPE.md). No-op otherwise."""
    s = text.strip()
    m = _JSONP.match(s)
    if not m:
        return s
    end = s.rstrip().rstrip(";").rstrip()
    if not end.endswith(")"):
        return s
    return end[m.end():-1].strip()


def main():
    endpoint = sys.argv[1]
    page_url = sys.argv[2]
    out_dir = sys.argv[3]
    tag = sys.argv[4] if len(sys.argv) > 4 else "capture"
    wait = int(sys.argv[5]) if len(sys.argv) > 5 else 50
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
    bodies = {}      # requestId -> (url, mimeType)
    pending = {}     # getResponseBody message id -> source url
    manifest = []    # [{file, url, kind}] so we can trace a payload back to its host
    captured = 0
    deadline = time.time() + wait
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
            bodies[r] = (resp.get("url", ""), resp.get("mimeType", ""))
            print(f"   [net] {resp.get('status','?')} {resp.get('mimeType','')} {resp.get('url','')[:100]}")

        elif method == "Network.loadingFinished":
            r = params.get("requestId")
            url, mime = bodies.get(r, ("", ""))
            # Do NOT filter on URL: the envelope is served from a host that
            # contains neither "fantasy" nor "yahoo" (see API_SHAPE.md). Ask for
            # every text-ish body and match on the JSON envelope after decoding.
            if any(t in mime for t in ("json", "javascript", "text/plain")):
                # Remember which URL this body reply will belong to; the reply
                # carries only our message id, not the requestId.
                pending[send("Network.getResponseBody", {"requestId": r}, sid=session_id)] = url

        elif rid and method is None and "result" in msg and "body" in msg["result"]:
            res = msg["result"]
            b64 = res["body"]
            data = base64.b64decode(b64) if res.get("base64Encoded") else b64.encode()
            text = data.decode("utf-8", "replace")
            body = strip_jsonp(text)
            if not (body.startswith("{") or body.startswith("[")):
                continue
            # Flag the payloads that actually carry league data, so a capture of
            # 200 unrelated JSON blobs still tells us which file to open.
            kind = "api"
            try:
                doc = json.loads(body)
                if isinstance(doc, dict):
                    leagues = doc.get("service", {}).get("leagues")
                    if isinstance(leagues, dict) and leagues:
                        kind = "envelope"
                    elif "fantasy_content" in doc:
                        kind = "fantasy_content"
            except Exception:
                pass
            src = pending.get(rid, "")
            fn = os.path.join(out_dir, f"{tag}.{kind}.{captured}.json")
            with open(fn, "w") as f:
                f.write(body)
            manifest.append({"file": os.path.basename(fn), "kind": kind, "url": src})
            captured += 1
            print(f"   captured [{captured}] {kind} ({len(body)} bytes) -> {fn}")
            if kind != "api":
                print(f"      FROM {src}")

        if not attached and time.time() > deadline - 5:
            print("   (warning: never attached to target; retry)")

    mf = os.path.join(out_dir, f"{tag}.manifest.json")
    with open(mf, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f">> done. captured {captured} JSON response(s) in {out_dir}; manifest -> {mf}")
    try:
        conn.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
