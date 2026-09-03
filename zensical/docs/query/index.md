---
title: Stat Search
icon: lucide/search
description: Query the league's matchups, rosters, team seasons and draft picks in the browser.
---

# Stat Search

Ad hoc queries over the four captured tables: one row per team per game, one per
roster slot per week, one per team per season and one per draft pick. The tables
are downloaded and queried in the browser, so a query is answered on the reader's
own machine and nothing is sent anywhere.

<div id="phfl-query" data-query-base="../query/">
  <p>Stat Search runs in the browser and needs JavaScript enabled. The
  league's standing marks are on <a href="../records/index.md">Records</a>,
  and the postseason ones on <a href="../playoffs.md">Playoffs</a>.</p>
</div>

<script type="module" src="../javascripts/query.js"></script>
