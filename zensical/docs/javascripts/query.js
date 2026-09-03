// Stat Search UI. Owns the DOM and the AST; delegates SQL to query-compile.mjs
// and execution to query-engine.js.

import { compileAst, renderSql } from "./query-compile.mjs";
import { runSql, startEngine } from "./query-engine.js";
import { PRESETS } from "./query-presets.js";

const mount = document.getElementById("phfl-query");

const OPERATOR_LABELS = {
  "=": "is",
  "!=": "is not",
  ">": "more than",
  ">=": "at least",
  "<": "less than",
  "<=": "at most",
  between: "between",
  in: "any of",
  not_in: "none of",
  contains: "contains",
  is_null: "is blank",
};

const LINKED = {
  owner: (row, key) => `../owners/${slugify(row[key])}/`,
  opp_owner: (row) => `../owners/${slugify(row.opp_owner)}/`,
  player: (row) => `../players/${row.player_slug ?? slugify(row.player)}/`,
};

function slugify(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

class StatSearch {
  constructor(root, base) {
    this.root = root;
    this.base = base;
    this.ast = structuredClone(PRESETS[0].ast);
    this.schema = null;
  }

  async start() {
    this.renderShell();
    try {
      const { schema } = await startEngine(this.base, (fraction) => {
        this.progress.value = fraction;
        this.status.textContent = `Loading query engine ${Math.round(fraction * 100)}%`;
      });
      this.schema = schema;
      this.status.textContent = "";
      this.progress.hidden = true;
      this.readUrl();
      this.renderBuilder();
      await this.run();
    } catch (error) {
      this.fail(error);
    }
  }

  fail(error) {
    this.root.innerHTML = "";
    const box = element("div", "phfl-query__error");
    box.append(
      element("p", null, `Stat Search could not start: ${error.message}`),
      element("p", null, "The curated numbers are still available:"),
    );
    const list = element("ul");
    for (const [href, label] of [["../records/", "Records"], ["../playoffs/", "Playoffs"]]) {
      const item = element("li");
      const link = element("a", null, label);
      link.href = href;
      item.append(link);
      list.append(item);
    }
    box.append(list);
    this.root.append(box);
  }

  renderShell() {
    this.root.innerHTML = "";
    this.status = element("p", "phfl-query__status", "Loading query engine…");
    this.progress = document.createElement("progress");
    this.progress.max = 1;
    this.progress.value = 0;
    this.builder = element("div", "phfl-query__builder");
    this.results = element("div", "phfl-query__results");
    this.sqlPanel = document.createElement("details");
    this.sqlPanel.append(element("summary", null, "Show query"));
    this.sqlCode = document.createElement("pre");
    this.sqlPanel.append(this.sqlCode);
    this.root.append(this.status, this.progress, this.builder, this.results, this.sqlPanel);
  }

  columnsFor(table) {
    return this.schema.tables[table].columns.map((column) => column.name);
  }

  renderBuilder() {
    this.builder.innerHTML = "";

    const chips = element("div", "phfl-query__presets");
    for (const preset of PRESETS) {
      const button = element("button", "phfl-query__chip", preset.label);
      button.type = "button";
      button.addEventListener("click", () => {
        this.ast = structuredClone(preset.ast);
        this.renderBuilder();
        this.run();
      });
      chips.append(button);
    }
    this.builder.append(chips);

    const datasets = element("div", "phfl-query__datasets");
    for (const table of Object.keys(this.schema.tables)) {
      const button = element("button", "phfl-query__dataset", table.replace("_", " "));
      button.type = "button";
      button.disabled = table === this.ast.from;
      button.addEventListener("click", () => {
        this.ast = { from: table, filter: [], arrange: [], limit: 200 };
        this.renderBuilder();
        this.run();
      });
      datasets.append(button);
    }
    this.builder.append(datasets);

    this.builder.append(this.renderFilters());
    this.builder.append(this.renderAggregation());
    this.builder.append(this.renderSort());

    const run = element("button", "phfl-query__run", "Run query");
    run.type = "button";
    run.addEventListener("click", () => this.run());
    this.builder.append(run);
  }

  renderFilters() {
    const wrapper = element("div", "phfl-query__verbs");
    wrapper.append(element("h3", null, "Filters"));
    this.ast.filter ??= [];
    this.ast.filter.forEach((clause, index) => {
      const row = element("div", "phfl-query__verb");

      const field = document.createElement("select");
      for (const name of this.columnsFor(this.ast.from)) {
        const option = element("option", null, name);
        option.value = name;
        option.selected = name === clause.field;
        field.append(option);
      }
      field.addEventListener("change", () => {
        clause.field = field.value;
      });

      const op = document.createElement("select");
      for (const [value, label] of Object.entries(OPERATOR_LABELS)) {
        const option = element("option", null, label);
        option.value = value;
        option.selected = value === clause.op;
        op.append(option);
      }
      op.addEventListener("change", () => {
        clause.op = op.value;
      });

      const value = document.createElement("input");
      value.value = Array.isArray(clause.value) ? clause.value.join(", ") : clause.value;
      value.addEventListener("change", () => {
        clause.value = parseValue(value.value, clause.op);
      });

      const remove = element("button", "phfl-query__remove", "Remove");
      remove.type = "button";
      remove.addEventListener("click", () => {
        this.ast.filter.splice(index, 1);
        this.renderBuilder();
      });

      row.append(field, op, value, remove);
      wrapper.append(row);
    });

    const add = element("button", "phfl-query__add", "Add filter");
    add.type = "button";
    add.addEventListener("click", () => {
      this.ast.filter.push({
        field: this.columnsFor(this.ast.from)[0],
        op: "=",
        value: "",
      });
      this.renderBuilder();
    });
    wrapper.append(add);
    return wrapper;
  }

  renderAggregation() {
    const wrapper = element("div", "phfl-query__verbs");
    wrapper.append(element("h3", null, "Group and summarise"));
    this.ast.groupBy ??= [];
    this.ast.summarise ??= [];

    const group = element("div", "phfl-query__verb");
    for (const name of this.columnsFor(this.ast.from)) {
      const label = element("label", "phfl-query__group");
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = this.ast.groupBy.includes(name);
      box.addEventListener("change", () => {
        if (box.checked) this.ast.groupBy.push(name);
        else this.ast.groupBy = this.ast.groupBy.filter((n) => n !== name);
        this.renderBuilder();
      });
      label.append(box, document.createTextNode(` ${name}`));
      group.append(label);
    }
    wrapper.append(group);

    this.ast.summarise.forEach((spec, index) => {
      const row = element("div", "phfl-query__verb");

      const fn = document.createElement("select");
      for (const name of ["count", "count_distinct", "sum", "avg", "min", "max", "median", "stddev"]) {
        const option = element("option", null, name);
        option.value = name;
        option.selected = name === spec.fn;
        fn.append(option);
      }
      fn.addEventListener("change", () => {
        spec.fn = fn.value;
        this.renderBuilder();
      });

      const field = document.createElement("select");
      const blank = element("option", null, "(all rows)");
      blank.value = "";
      field.append(blank);
      for (const name of this.columnsFor(this.ast.from)) {
        const option = element("option", null, name);
        option.value = name;
        option.selected = name === spec.field;
        field.append(option);
      }
      field.addEventListener("change", () => {
        spec.field = field.value || undefined;
      });

      const alias = document.createElement("input");
      alias.value = spec.as ?? "";
      alias.addEventListener("change", () => {
        spec.as = alias.value.trim() || `${spec.fn}_${spec.field ?? "all"}`;
        this.renderBuilder();
      });

      const remove = element("button", "phfl-query__remove", "Remove");
      remove.type = "button";
      remove.addEventListener("click", () => {
        this.ast.summarise.splice(index, 1);
        this.renderBuilder();
      });

      row.append(fn, field, alias, remove);
      wrapper.append(row);
    });

    const add = element("button", "phfl-query__add", "Add summary");
    add.type = "button";
    add.addEventListener("click", () => {
      this.ast.summarise.push({ fn: "count", as: "rows" });
      this.renderBuilder();
    });
    wrapper.append(add);
    return wrapper;
  }

  renderSort() {
    const wrapper = element("div", "phfl-query__verbs");
    wrapper.append(element("h3", null, "Sort"));
    const aliases = (this.ast.summarise ?? []).map((spec) => spec.as);
    const options = [...this.columnsFor(this.ast.from), ...aliases];
    const current = this.ast.arrange?.[0] ?? { field: options[0], dir: "desc" };

    const field = document.createElement("select");
    for (const name of options) {
      const option = element("option", null, name);
      option.value = name;
      option.selected = name === current.field;
      field.append(option);
    }

    const dir = document.createElement("select");
    for (const [value, label] of [["desc", "high to low"], ["asc", "low to high"]]) {
      const option = element("option", null, label);
      option.value = value;
      option.selected = value === current.dir;
      dir.append(option);
    }

    const apply = () => {
      this.ast.arrange = [{ field: field.value, dir: dir.value }];
    };
    field.addEventListener("change", apply);
    dir.addEventListener("change", apply);

    wrapper.append(field, dir);
    return wrapper;
  }

  async run() {
    let compiled;
    try {
      compiled = compileAst(this.ast, this.schema);
    } catch (error) {
      this.results.textContent = `That query is not valid: ${error.message}`;
      return;
    }
    this.sqlCode.textContent = renderSql(compiled.sql, compiled.params);
    this.writeUrl();
    this.results.textContent = "Running…";
    try {
      const { columns, rows } = await runSql(this.base, compiled.sql, compiled.params);
      this.renderTable(columns, rows);
    } catch (error) {
      this.results.textContent = `Query failed: ${error.message}`;
    }
  }

  renderTable(columns, rows) {
    this.results.innerHTML = "";
    this.results.append(element("p", "phfl-query__count", `${rows.length} rows`));
    const table = document.createElement("table");
    const head = document.createElement("tr");
    for (const column of columns) head.append(element("th", null, column));
    table.append(head);
    const aliases = new Set((this.ast.summarise ?? []).map((s) => s.as));
    for (const row of rows) {
      const tr = document.createElement("tr");
      for (const column of columns) {
        const cell = document.createElement("td");
        const linker = LINKED[column];
        if (linker && !aliases.has(column) && row[column]) {
          const link = element("a", null, String(row[column]));
          link.href = linker(row, column);
          cell.append(link);
        } else {
          cell.textContent = formatCell(row[column]);
        }
        tr.append(cell);
      }
      table.append(tr);
    }
    this.results.append(table);
  }

  writeUrl() {
    const encoded = btoa(unescape(encodeURIComponent(JSON.stringify(this.ast))));
    const url = new URL(window.location.href);
    url.searchParams.set("q", encoded);
    window.history.replaceState(null, "", url);
  }

  readUrl() {
    const encoded = new URL(window.location.href).searchParams.get("q");
    if (!encoded) return;
    try {
      const parsed = JSON.parse(decodeURIComponent(escape(atob(encoded))));
      if (
        parsed &&
        typeof parsed === "object" &&
        !Array.isArray(parsed) &&
        typeof parsed.from === "string"
      ) {
        this.ast = parsed;
      }
    } catch {
      // A malformed link falls back to the default preset rather than erroring.
    }
  }
}

function parseValue(raw, op) {
  if (op === "between" || op === "in" || op === "not_in") {
    return raw.split(",").map((part) => coerce(part.trim()));
  }
  return coerce(raw.trim());
}

function coerce(raw) {
  if (raw === "true") return true;
  if (raw === "false") return false;
  if (raw !== "" && !Number.isNaN(Number(raw))) return Number(raw);
  return raw;
}

function formatCell(value) {
  if (typeof value === "number" && !Number.isInteger(value)) return value.toFixed(2);
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value ?? "");
}

if (mount) {
  const base = mount.dataset.queryBase ?? "../query/";
  new StatSearch(mount, base).start();
}
