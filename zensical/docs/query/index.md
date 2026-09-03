---
title: Stat Search
icon: lucide/search
description: Query the league's matchups, rosters, team seasons and draft picks in the browser.
hide:
  - toc
---

# Stat Search

Ad hoc queries over six tables. Four hold captured data: one row per team per
game, one per roster slot per week, one per team per season, one per draft pick.
Two are derived: every [award](../awards.md) and every
[Hall of Fame](../hall-of-fame.md) inductee. Tables are downloaded and queried in
the browser; nothing is sent to a server.

!!! tip "Start from a preset"

    Pick a preset, then adjust filters. Click a column header to sort. Copy link
    shares the exact query.

The roster table adds a derived column, `swung`: the player started, their team
won outright, and they outscored the margin of victory, so removing them flips
the result. Four of the seven awards rank by it, and `sum(swung)` over any
grouping reproduces their totals.

<div id="phfl-query" data-query-base="../query/">
  <p>Stat Search requires JavaScript. Standing marks are on
  <a href="../records/index.md">Records</a>, postseason marks on
  <a href="../playoffs.md">Playoffs</a>.</p>
</div>

<script type="module" src="../javascripts/query.js"></script>
