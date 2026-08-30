// Sortable standings/records tables. Uses the `document$` observable per the
// zensical-setup skill so it re-initializes on every instant-nav page swap.
document$.subscribe(function () {
  var tables = document.querySelectorAll("article table:not([class])");
  tables.forEach(function (table) {
    if (table.dataset.sortableReady) return;
    table.dataset.sortableReady = "1";
    var headers = table.tHead && table.tHead.rows[0];
    if (!headers) return;
    Array.prototype.forEach.call(headers.cells, function (th, i) {
      th.style.cursor = "pointer";
      th.title = "Click to sort";
      th.addEventListener("click", function () {
        var asc = !(th.dataset.asc === "1");
        th.dataset.asc = asc ? "1" : "0";
        sortTable(table, i, asc);
      });
    });
  });
});

function parseNum(s) {
  var t = (s || "").replace(/[^0-9.\-]/g, "");
  var n = parseFloat(t);
  return isNaN(n) ? null : n;
}

function sortTable(table, col, asc) {
  var rows = Array.prototype.slice.call(table.tBodies[0].rows);
  var isNum = rows.every(function (r) {
    return parseNum(r.cells[col].textContent) !== null;
  });
  rows.sort(function (a, b) {
    var av = a.cells[col].textContent,
      bv = b.cells[col].textContent;
    if (isNum) {
      av = parseNum(av);
      bv = parseNum(bv);
    } else {
      av = av.toLowerCase();
      bv = bv.toLowerCase();
    }
    if (av < bv) return asc ? -1 : 1;
    if (av > bv) return asc ? 1 : -1;
    return 0;
  });
  rows.forEach(function (r) {
    table.tBodies[0].appendChild(r);
  });
}
