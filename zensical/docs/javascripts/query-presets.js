// Preset queries, as ASTs. Presets are data, not code: they load into the same
// verb stack the user edits, so every preset is a starting point rather than a
// fixed report.

export const PRESETS = [
  {
    id: "blowouts",
    label: "Biggest blowouts",
    ast: {
      from: "matchups",
      filter: [{ field: "phase", op: "=", value: "regular" }],
      arrange: [{ field: "margin", dir: "desc" }],
      limit: 25,
    },
  },
  {
    id: "nailbiters",
    label: "One-score games",
    ast: {
      from: "matchups",
      filter: [
        { field: "phase", op: "=", value: "regular" },
        { field: "margin", op: "between", value: [0.01, 1] },
      ],
      arrange: [{ field: "margin", dir: "asc" }],
      limit: 25,
    },
  },
  {
    id: "points-in-loss",
    label: "Most points in a loss",
    ast: {
      from: "matchups",
      filter: [{ field: "won", op: "=", value: false }],
      arrange: [{ field: "score", dir: "desc" }],
      limit: 25,
    },
  },
  {
    id: "points-in-win",
    label: "Fewest points in a win",
    ast: {
      from: "matchups",
      filter: [{ field: "won", op: "=", value: true }],
      arrange: [{ field: "score", dir: "asc" }],
      limit: 25,
    },
  },
  {
    id: "bench-heroes",
    label: "Highest-scoring benched players",
    ast: {
      from: "player_weeks",
      filter: [{ field: "started", op: "=", value: false }],
      arrange: [{ field: "points", dir: "desc" }],
      limit: 50,
    },
  },
  {
    id: "best-weeks",
    label: "Best single weeks",
    ast: {
      from: "player_weeks",
      filter: [{ field: "started", op: "=", value: true }],
      arrange: [{ field: "points", dir: "desc" }],
      limit: 50,
    },
  },
  {
    id: "bench-waste",
    label: "Points left on the bench, by owner",
    ast: {
      from: "player_weeks",
      filter: [{ field: "started", op: "=", value: false }],
      groupBy: ["owner"],
      summarise: [{ fn: "sum", field: "points", as: "bench_points" }],
      arrange: [{ field: "bench_points", dir: "desc" }],
      limit: 25,
    },
  },
  {
    id: "position-scoring",
    label: "Scoring by position",
    ast: {
      from: "player_weeks",
      filter: [{ field: "started", op: "=", value: true }],
      groupBy: ["position"],
      summarise: [
        { fn: "avg", field: "points", as: "avg_points" },
        { fn: "count", as: "starts" },
      ],
      arrange: [{ field: "avg_points", dir: "desc" }],
      limit: 25,
    },
  },
  {
    id: "best-records",
    label: "Best regular-season records",
    ast: {
      from: "team_seasons",
      arrange: [{ field: "wins", dir: "desc" }],
      limit: 25,
    },
  },
  {
    id: "weak-champions",
    label: "Champions with the fewest points",
    ast: {
      from: "team_seasons",
      filter: [{ field: "champion", op: "=", value: true }],
      arrange: [{ field: "pf", dir: "asc" }],
      limit: 25,
    },
  },
  {
    id: "owner-careers",
    label: "Career totals by owner",
    ast: {
      from: "team_seasons",
      groupBy: ["owner"],
      summarise: [
        { fn: "sum", field: "wins", as: "wins" },
        { fn: "sum", field: "losses", as: "losses" },
        { fn: "count", as: "seasons" },
      ],
      arrange: [{ field: "wins", dir: "desc" }],
      limit: 25,
    },
  },
  {
    id: "first-picks",
    label: "First-round picks",
    ast: {
      from: "draft",
      filter: [{ field: "round", op: "=", value: 1 }],
      arrange: [{ field: "year", dir: "desc" }],
      limit: 100,
    },
  },
];
