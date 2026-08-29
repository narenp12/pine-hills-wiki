# Yahoo Fantasy API response shape (CONFIRMED from live capture)

Captured 2026-08-29 from a logged-in Edge session via CDP `Network.getResponseBody`
on the 2016 standings page. File: `dump/2016-standings.api.11.json` (92 KB).

## Envelope

```
service
  user { guid, nickName }
  leagues
    "447010"                         # league id (string)
      id, gameCode:"nfl", name:"Pine Hills", scoringType, positions[], ...
      teams
        "1"                         # team id (string)
          id            (int)
          name          "Save Me"   # team name
          rank          ""          # (string; filled on scored standings)
          wins          (int)
          losses        (int)
          ties          (int)
          pf            (points for)
          pa            (points against)
          streak
          managers { "1": { id, nickName: "Naren" } }
          players [ { id, position:"QB", eligiblePositionSlots[], ... }, ... ]
          remainingGames, previousSeasonTeamRank, seasonTotalPoints, projectedPoints
```

## Notes for the extractor rebuild
- This is the **team roster / metadata** view: `players[]` present but slots are
  empty pre-draft (`id:null`). The *scored* standings (numeric `points_for`,
  final `rank`) arrive from a sibling sub-call in the same payload family — the
  scored `points_for`/`points_against` keys map to `pf`/`pa` here.
- The request host did NOT contain "fantasy" or "yahoo" in the URL, which is why
  the first capture (URL-filtered) missed it. Capture ALL response bodies, then
  match on the JSON envelope (`service.leagues.<id>.teams`), not the URL.
- Parse as JSON (it may be JSONP-wrapped: `callback({...})`); strip the wrapper
  before `json.loads`.
- The same envelope family serves standings / draft / matchups / rosters — each
  page triggers a different sub-resource. Capture per page, key on the envelope
  node that's populated.

## Anti-ban
Pure observation: we only read responses the page itself fetches. Zero extra
requests. Sequential, one season/page, human-like waits. Reuse the logged-in
session; never log in programmatically.
