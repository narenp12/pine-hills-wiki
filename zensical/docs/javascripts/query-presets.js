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
  // The two presets built on `swung`, the column that carries the measure four
  // of the seven awards are defined by. Deliberately the ranking the Awards
  // pages print, so a reader can start from a number they have already seen and
  // then change the grouping -- by owner, by position, by year -- to ask the
  // questions those pages do not answer.
  {
    id: "swung-seasons",
    label: "Wins swung, by season",
    ast: {
      from: "player_weeks",
      filter: [{ field: "swung", op: "=", value: true }],
      groupBy: ["year", "player"],
      summarise: [{ fn: "count", as: "wins_swung" }],
      arrange: [{ field: "wins_swung", dir: "desc" }],
      limit: 50,
    },
  },
  {
    id: "swung-careers",
    label: "Wins swung, career",
    ast: {
      from: "player_weeks",
      filter: [{ field: "swung", op: "=", value: true }],
      groupBy: ["player"],
      summarise: [
        { fn: "count", as: "wins_swung" },
        { fn: "count_distinct", field: "owner", as: "owners" },
      ],
      arrange: [{ field: "wins_swung", dir: "desc" }],
      limit: 50,
    },
  },
  {
    id: "swung-by-owner",
    label: "Wins swung, by owner",
    ast: {
      from: "player_weeks",
      filter: [{ field: "swung", op: "=", value: true }],
      groupBy: ["owner"],
      summarise: [{ fn: "count", as: "wins_swung" }],
      arrange: [{ field: "wins_swung", dir: "desc" }],
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
  // The two derived tables. Every award the Awards and Hall of Fame pages hand
  // out is a row here, so the questions those pages cannot ask -- who won most,
  // which manager's roster collected them, which position the Hall favours --
  // are one grouping away.
  {
    id: "most-decorated",
    label: "Most decorated players",
    ast: {
      from: "awards",
      groupBy: ["player"],
      summarise: [
        { fn: "count", as: "awards" },
        { fn: "count_distinct", field: "year", as: "seasons" },
      ],
      arrange: [{ field: "awards", dir: "desc" }],
      limit: 50,
    },
  },
  {
    id: "award-winners",
    label: "Every award winner",
    ast: {
      from: "awards",
      filter: [{ field: "award", op: "!=", value: "Team of the Season" }],
      arrange: [{ field: "year", dir: "desc" }],
      limit: 100,
    },
  },
  {
    id: "awards-by-owner",
    label: "Awards collected, by owner",
    ast: {
      from: "awards",
      groupBy: ["owner"],
      summarise: [{ fn: "count", as: "awards" }],
      arrange: [{ field: "awards", dir: "desc" }],
      limit: 25,
    },
  },
  {
    id: "hall-of-fame",
    label: "The Hall of Fame",
    ast: {
      from: "hall_of_fame",
      arrange: [{ field: "score", dir: "desc" }],
      limit: 50,
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
