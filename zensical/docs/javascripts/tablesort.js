// Sortable standings/records tables.
//
// Uses the `document$` observable per the zensical-setup skill so it
// re-initializes on every instant-nav page swap.
//
// This is a self-contained implementation - the site does NOT load the
// tablesort library from a CDN. Each header's label is wrapped in a real
// <button> so sorting is reachable by keyboard and announced as a control, and
// the sorted column carries aria-sort so its state is exposed too.

document$.subscribe(function () {
  document.querySelectorAll("article table:not([class])").forEach(function (table) {
    if (table.dataset.sortableReady) return;
    table.dataset.sortableReady = "1";

    // A scrollable region must be reachable by keyboard (WCAG 2.1.1). The
    // theme's wrapper is what scrolls; give it a tab stop and a name.
    var scroller = table.closest(".md-typeset__scrollwrap");
    if (scroller && !scroller.hasAttribute("tabindex")) {
      scroller.setAttribute("tabindex", "0");
      scroller.setAttribute("role", "region");
      scroller.setAttribute("aria-label", "Scrollable table");
    }

    var headRow = table.tHead && table.tHead.rows[0];
    if (!headRow || !table.tBodies[0]) return;

    Array.prototype.forEach.call(headRow.cells, function (th, index) {
      var label = th.textContent.trim();
      if (!label) return;

      var button = document.createElement("button");
      button.type = "button";
      button.className = "sort-toggle";
      button.textContent = label;
      button.setAttribute("aria-label", "Sort by " + label);

      th.textContent = "";
      th.appendChild(button);
      th.setAttribute("aria-sort", "none");

      button.addEventListener("click", function () {
        var ascending = th.getAttribute("aria-sort") !== "ascending";

        Array.prototype.forEach.call(headRow.cells, function (other) {
          other.setAttribute("aria-sort", "none");
        });
        th.setAttribute("aria-sort", ascending ? "ascending" : "descending");

        sortTable(table, index, ascending);
      });
    });
  });
});

function parseNum(text) {
  var cleaned = (text || "").replace(/[^0-9.\-]/g, "");
  var value = parseFloat(cleaned);
  return isNaN(value) ? null : value;
}

// Rows can be short when a cell spans columns; treat a missing cell as empty
// rather than throwing on `.textContent` of undefined.
function cellText(row, index) {
  var cell = row.cells[index];
  return cell ? cell.textContent.trim() : "";
}

function sortTable(table, column, ascending) {
  var body = table.tBodies[0];
  var rows = Array.prototype.slice.call(body.rows);

  var numeric = rows.every(function (row) {
    return parseNum(cellText(row, column)) !== null;
  });

  rows.sort(function (a, b) {
    var left = cellText(a, column);
    var right = cellText(b, column);

    if (numeric) {
      left = parseNum(left);
      right = parseNum(right);
    } else {
      left = left.toLowerCase();
      right = right.toLowerCase();
    }

    if (left < right) return ascending ? -1 : 1;
    if (left > right) return ascending ? 1 : -1;
    return 0;
  });

  var fragment = document.createDocumentFragment();
  rows.forEach(function (row) {
    fragment.appendChild(row);
  });
  body.appendChild(fragment);
}
