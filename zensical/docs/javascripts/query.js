// Stat Search UI. Owns the DOM and the AST; delegates SQL to query-compile.mjs
// and execution to query-engine.js.

import { compileAst, renderSql, MAX_LIMIT } from "./query-compile.mjs";
import { distinctValues, runSql, startEngine } from "./query-engine.js";
import { PRESETS } from "./query-presets.js";

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

// Which operators each column kind offers. The menu used to be the whole list
// on every column, which put "contains" on a DOUBLE and "more than" on a
// BOOLEAN -- both compile, and both answer a question nobody asked. The types
// come from schema.json, which build_query_db.py declares rather than infers
// precisely so this menu can be built from them.
const OPERATORS_BY_KIND = {
  numeric: ["=", "!=", ">", ">=", "<", "<=", "between", "in", "not_in", "is_null"],
  text: ["=", "!=", "contains", "in", "not_in", "is_null"],
  boolean: ["=", "!=", "is_null"],
};

const NO_VALUE = new Set(["is_null"]);
const MULTI_VALUE = new Set(["in", "not_in", "between"]);

const AGGREGATES = [
  "count",
  "count_distinct",
  "sum",
  "avg",
  "min",
  "max",
  "median",
  "stddev",
];

// Columns whose values name a page on this wiki. `player_slug` is preferred
// over slugifying the display name where the row carries it, because that slug
// is the one the player pages were written to.
const LINKED = {
  owner: (row, key) => `owners/${slugify(row[key])}/`,
  opp_owner: (row) => `owners/${slugify(row.opp_owner)}/`,
  player: (row) => `players/${row.player_slug ?? slugify(row.player)}/`,
};

export function kindOf(type) {
  const name = String(type ?? "").toUpperCase();
  if (name.includes("BOOL")) return "boolean";
  if (/INT|DOUBLE|DECIMAL|FLOAT|REAL|HUGEINT|NUMERIC/.test(name)) return "numeric";
  return "text";
}

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

// A connective word between two controls, so a verb row reads as a sentence
// rather than as three anonymous boxes. Decorative to a screen reader, which
// gets the same information from each control's own label.
function joiner(text) {
  const node = element("span", "phfl-query__joiner", text);
  node.setAttribute("aria-hidden", "true");
  return node;
}

function labelledSelect(ariaLabel, className) {
  const node = document.createElement("select");
  node.setAttribute("aria-label", ariaLabel);
  if (className) node.className = className;
  return node;
}

function fillOptions(select, values, selected) {
  select.innerHTML = "";
  for (const entry of values) {
    const [value, label] = Array.isArray(entry) ? entry : [entry, entry];
    const option = element("option", null, label);
    option.value = value;
    option.selected = value === selected;
    select.append(option);
  }
}

function formatBytes(bytes) {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export class StatSearch {
  constructor(root, base) {
    this.root = root;
    this.base = base;
    // Links out of the results are built from the mount's own base rather than
    // a hard-coded `../`, so a result row still points at the right page if the
    // builder is ever mounted from a path other than /query/.
    this.siteBase = new URL(`${base}../`, window.location.href);
    this.ast = structuredClone(PRESETS[0].ast);
    this.schema = null;
    this.valueLists = new Map();
    this.runToken = 0;
  }

  async start() {
    this.renderShell();
    try {
      const { schema } = await startEngine(this.base, (fraction, loaded) => {
        if (fraction === null) {
          this.progress.removeAttribute("value");
          this.status.textContent = `Loading query engine, ${formatBytes(loaded)}`;
          return;
        }
        this.progress.value = Math.min(fraction, 1);
        this.status.textContent = `Loading query engine ${Math.round(fraction * 100)}%`;
      });
      this.schema = schema;
      this.types = new Map();
      for (const [table, entry] of Object.entries(schema.tables)) {
        for (const column of entry.columns) {
          this.types.set(`${table}.${column.name}`, column.type);
        }
      }
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
      element("p", null, "Curated numbers:"),
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
    // The engine boot, the row count and every error land in this one element,
    // so a screen reader is told the query is running and what came back. It
    // used to be silent: `results.textContent = "Running…"` replaced the table
    // with no announcement at all.
    this.status.setAttribute("role", "status");
    this.status.setAttribute("aria-live", "polite");
    this.progress = document.createElement("progress");
    this.progress.max = 1;
    this.progress.value = 0;
    this.progress.setAttribute("aria-label", "Query engine download");

    this.builder = element("div", "phfl-query__builder");
    this.results = element("div", "phfl-query__results");
    this.sqlPanel = document.createElement("details");
    this.sqlPanel.className = "phfl-query__sql";
    this.sqlPanel.append(element("summary", null, "Show query"));
    this.sqlCode = document.createElement("pre");
    this.sqlPanel.append(this.sqlCode);

    const output = element("div", "phfl-query__output");
    output.append(this.results, this.sqlPanel);
    const panels = element("div", "phfl-query__panels");
    panels.append(this.builder, output);

    this.root.append(this.status, this.progress, panels);
  }

  columnsFor(table) {
    return this.schema.tables[table].columns.map((column) => column.name);
  }

  // Every column the current query can name: the driving table's, plus the ones
  // a join brings in. The controls used to offer only the driving table's, so a
  // join selected and displayed columns that could not then be filtered on,
  // sorted by, or clicked in the header - which is most of the reason to join.
  availableColumns() {
    const columns = this.columnsFor(this.ast.from);
    if (!this.ast.join) return columns;
    const joined = this.columnsFor(this.ast.join.table).filter(
      (name) => !columns.includes(name),
    );
    return [...columns, ...joined];
  }

  // Which table a column belongs to, so its type and its value list are read
  // from the right one. A name both tables carry resolves to the driving table,
  // matching how the compiler qualifies it.
  tableOf(field) {
    if (this.columnsFor(this.ast.from).includes(field)) return this.ast.from;
    if (this.ast.join && this.columnsFor(this.ast.join.table).includes(field)) {
      return this.ast.join.table;
    }
    return this.ast.from;
  }

  kindFor(field) {
    return kindOf(this.types.get(`${this.tableOf(field)}.${field}`));
  }

  // Every structural edit routes through here, and every value edit avoids it.
  // Rebuilding on a keystroke used to blow away the element the caret was in,
  // so typing an alias and tabbing out lost focus mid-form.
  refresh({ rerun = true } = {}) {
    this.renderBuilder();
    if (rerun) this.run();
  }

  renderBuilder() {
    this.builder.innerHTML = "";

    // Dataset first, then the questions that dataset can answer. Nineteen
    // preset chips in one wall filled most of a 19rem column and told the
    // reader nothing about which table each one reached; scoped to the
    // selected dataset it is at most seven, and the pairing is legible.
    const datasets = element("div", "phfl-query__datasets");
    datasets.setAttribute("role", "group");
    datasets.setAttribute("aria-label", "Dataset");
    for (const table of Object.keys(this.schema.tables)) {
      const rowCount = this.schema.tables[table].row_count;
      const button = element("button", "phfl-query__dataset", table.replaceAll("_", " "));
      button.type = "button";
      button.title = `${rowCount.toLocaleString()} rows`;
      button.disabled = table === this.ast.from;
      button.setAttribute("aria-pressed", String(table === this.ast.from));
      button.addEventListener("click", () => {
        // The dataset's first preset rather than a bare table: an empty query
        // over 19,881 roster rows answers nothing, and the reader came here
        // with a question, not with a table.
        const opening = PRESETS.find((preset) => preset.ast.from === table);
        this.ast = opening
          ? structuredClone(opening.ast)
          : { from: table, filter: [], arrange: [], limit: 200 };
        this.refresh();
      });
      datasets.append(button);
    }
    this.builder.append(datasets);

    const scoped = PRESETS.filter((preset) => preset.ast.from === this.ast.from);
    if (scoped.length) {
      const chips = element("div", "phfl-query__presets");
      chips.setAttribute("role", "group");
      chips.setAttribute("aria-label", `Starting questions for ${this.ast.from}`);
      for (const preset of scoped) {
        const button = element("button", "phfl-query__chip", preset.label);
        button.type = "button";
        button.addEventListener("click", () => {
          this.ast = structuredClone(preset.ast);
          this.refresh();
        });
        chips.append(button);
      }
      this.builder.append(chips);
    }

    this.builder.append(this.renderJoin());
    this.builder.append(this.renderFilters());
    this.builder.append(this.renderAggregation());
    this.builder.append(this.renderHaving());
    this.builder.append(this.renderSort());
    this.builder.append(this.renderLimit());

    const run = element("button", "phfl-query__run", "Run query");
    run.type = "button";
    run.addEventListener("click", () => this.run());
    const copy = element("button", "phfl-query__copy", "Copy link");
    copy.type = "button";
    copy.addEventListener("click", async () => {
      this.writeUrl();
      const url = window.location.href;
      try {
        await navigator.clipboard.writeText(url);
        copy.textContent = "Copied";
      } catch {
        window.prompt("Copy this link:", url);
        return;
      }
      setTimeout(() => {
        copy.textContent = "Copy link";
      }, 2000);
    });
    const actions = element("div", "phfl-query__actions");
    actions.append(run, copy);
    this.builder.append(actions);
  }

  // The value control for one clause: a yes/no menu on a boolean, a list-backed
  // text box everywhere else. Returned as a fresh element each time so changing
  // the field or the operator can swap the control rather than leave a text box
  // asking for "true".
  valueControl(clause) {
    const kind = this.kindFor(clause.field);
    if (NO_VALUE.has(clause.op)) {
      // "is blank" takes no value. A placeholder keeps the row's shape so the
      // swap back to a real control lands in the same slot.
      const blank = element("span", "phfl-query__novalue", "(no value)");
      blank.setAttribute("aria-hidden", "true");
      return blank;
    }
    if (kind === "boolean" && !MULTI_VALUE.has(clause.op)) {
      const select = labelledSelect("Filter value");
      fillOptions(select, [["true", "yes"], ["false", "no"]], String(clause.value));
      clause.value = select.value === "true";
      select.addEventListener("change", () => {
        clause.value = select.value === "true";
        this.run();
      });
      return select;
    }
    const input = document.createElement("input");
    input.setAttribute("aria-label", "Filter value");
    input.value = Array.isArray(clause.value) ? clause.value.join(", ") : clause.value;
    input.placeholder = MULTI_VALUE.has(clause.op) ? "comma separated" : "";
    input.addEventListener("change", () => {
      clause.value = parseValue(input.value, clause.op);
      this.run();
    });
    this.attachValueList(input, clause.field);
    return input;
  }

  // Autocomplete. The enum lists ship in schema.json already and were, until
  // now, downloaded on every visit and read by nothing. Columns with no enum --
  // `player`, `team` -- are asked of the engine once and cached, which is
  // affordable because the parquet is already on the reader's machine.
  attachValueList(input, field) {
    const enums = this.schema.enums?.[field];
    if (enums?.length) {
      this.bindList(input, `phfl-enum-${field}`, enums);
      return;
    }
    // A HAVING clause names a summary alias, not a column of the table, so
    // there is nothing to scan for it.
    const table = this.tableOf(field);
    if (!this.types.has(`${table}.${field}`)) return;
    if (this.kindFor(field) !== "text") return;
    const key = `${table}.${field}`;
    const cached = this.valueLists.get(key);
    if (cached) {
      if (cached instanceof Promise) return;
      this.bindList(input, `phfl-values-${slugify(key)}`, cached);
      return;
    }
    const pending = distinctValues(this.base, table, field)
      .then((values) => {
        this.valueLists.set(key, values);
        this.bindList(input, `phfl-values-${slugify(key)}`, values);
        return values;
      })
      .catch(() => {
        // Autocomplete is a convenience. A column the scan cannot answer just
        // leaves the reader typing the value, which is what they did before.
        this.valueLists.delete(key);
        return [];
      });
    this.valueLists.set(key, pending);
  }

  bindList(input, id, values) {
    let list = this.root.querySelector(`#${CSS.escape(id)}`);
    if (!list) {
      list = document.createElement("datalist");
      list.id = id;
      for (const value of values) {
        const option = document.createElement("option");
        option.value = value;
        list.append(option);
      }
      this.root.append(list);
    }
    input.setAttribute("list", id);
  }

  clauseRow(clause, remove, extraFields = []) {
    const row = element("div", "phfl-query__verb");
    const fields = [...this.availableColumns(), ...extraFields];

    const field = labelledSelect("Filter field");
    fillOptions(field, fields, clause.field);

    const op = labelledSelect("Filter operator");
    const operatorsFor = (name) =>
      (extraFields.includes(name)
        ? OPERATORS_BY_KIND.numeric
        : OPERATORS_BY_KIND[this.kindFor(name)]
      ).map((value) => [value, OPERATOR_LABELS[value]]);
    fillOptions(op, operatorsFor(clause.field), clause.op);

    let value = this.valueControl(clause);

    const swapValue = () => {
      const next = this.valueControl(clause);
      value.replaceWith(next);
      value = next;
    };

    field.addEventListener("change", () => {
      clause.field = field.value;
      // A value carried over from the old column is nearly always wrong -- the
      // `won is false` filter kept its `false` when the field became `score` --
      // and an operator the new column does not offer is worse than wrong.
      const allowed = operatorsFor(clause.field);
      fillOptions(op, allowed, clause.op);
      if (!allowed.some(([candidate]) => candidate === clause.op)) {
        clause.op = allowed[0][0];
        op.value = clause.op;
      }
      clause.value = "";
      swapValue();
      this.run();
    });

    op.addEventListener("change", () => {
      clause.op = op.value;
      swapValue();
      this.run();
    });

    const removeButton = element("button", "phfl-query__remove", "Remove");
    removeButton.type = "button";
    removeButton.setAttribute("aria-label", `Remove filter on ${clause.field}`);
    removeButton.addEventListener("click", remove);

    row.append(field, op, value, removeButton);
    return row;
  }

  // The columns worth joining on, in the order a default should prefer them.
  // A shared NAME is not a shared MEANING: `player_weeks` and `awards` both
  // carry `slot` and `points`, but one is a roster slot and a week's score and
  // the other is a Team of the Season slot and a season total. Opening on every
  // shared column joined on those too and matched nothing at all, so the first
  // join a reader ever built returned zero rows.
  static JOIN_KEYS = ["player", "player_slug", "owner", "team", "year", "week"];

  // One entity and one time key: `player` and `year` for the roster tables,
  // `owner` and `year` for the team ones. Everything else stays on offer as a
  // checkbox, unticked.
  //
  // Empty when the two tables share no identity column. It used to fall back to
  // `shared.slice(0, 1)`, which guesses -- and a guess landing on a measure like
  // `points` joins on a number that means something different on each side and
  // matches nothing, which is the zero-row failure this method already exists to
  // prevent. joinTargets drops a table with no usable key rather than offering
  // one that cannot work.
  defaultJoinKeys(shared) {
    const ranked = StatSearch.JOIN_KEYS.filter((name) => shared.includes(name));
    const entity = ranked.find((name) => !["year", "week"].includes(name));
    const time = ranked.find((name) => ["year", "week"].includes(name));
    return [entity, time].filter(Boolean);
  }

  // Which tables can be joined to the current one, and on what. Only columns
  // both tables carry are offered, because that is the only join the compiler
  // builds: an inner join on equal names.
  joinTargets() {
    const mine = new Set(this.columnsFor(this.ast.from));
    return Object.keys(this.schema.tables)
      .filter((table) => table !== this.ast.from)
      .map((table) => ({
        table,
        shared: this.columnsFor(table).filter((name) => mine.has(name)),
      }))
      .filter((entry) => this.defaultJoinKeys(entry.shared).length > 0);
  }

  // Every verb that names a column the query no longer has. Dropping a join
  // takes its columns away, and a `filter`, `groupBy` or `summarise` left
  // pointing at one compiles to `unknown column` on every later edit -- the
  // builder wedges, and the reader has no way to tell which control is at
  // fault because the offending menu no longer lists the value it holds. Sort
  // heals itself in renderSort; these do not, so they are pruned here.
  dropMissingColumns() {
    const known = new Set(this.availableColumns());
    this.ast.filter = (this.ast.filter ?? []).filter((c) => known.has(c.field));
    this.ast.groupBy = (this.ast.groupBy ?? []).filter((name) => known.has(name));
    const kept = (this.ast.summarise ?? []).filter(
      (spec) => !spec.field || known.has(spec.field),
    );
    // A summary that goes takes its HAVING clauses with it, the same rule the
    // Remove button applies.
    const aliases = new Set(kept.map((spec) => spec.as).filter(Boolean));
    this.ast.having = (this.ast.having ?? []).filter(
      (clause) => aliases.has(clause.field) || known.has(clause.field),
    );
    this.ast.summarise = kept;
  }

  // The compiler has always built joins; there was no control for one, so the
  // capability shipped dead. It also shipped broken -- `SELECT *` across two
  // tables returned duplicate column names that collapsed into each other --
  // which is why the select list is explicit now.
  renderJoin() {
    const wrapper = element("section", "phfl-query__verbs");
    wrapper.append(element("h3", null, "Combine with"));
    const targets = this.joinTargets();
    const current = this.ast.join;

    const table = labelledSelect("Table to combine with");
    fillOptions(
      table,
      [["", "(nothing)"], ...targets.map((entry) => [entry.table, entry.table.replaceAll("_", " ")])],
      current?.table ?? "",
    );

    const row = element("div", "phfl-query__verb");
    row.append(table);

    if (current) {
      const entry = targets.find((candidate) => candidate.table === current.table);
      const shared = entry?.shared ?? [];
      row.append(joiner("matching on"));
      for (const name of shared) {
        const label = element("label", "phfl-query__group");
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = (current.on ?? []).includes(name);
        box.addEventListener("change", () => {
          const on = box.checked
            ? [...(this.ast.join.on ?? []).filter((n) => n !== name), name]
            : (this.ast.join.on ?? []).filter((n) => n !== name);
          this.ast.join.on = on;
          // A join with no key is every row against every row, which the
          // compiler refuses; drop the join rather than show that error.
          if (!on.length) this.ast.join = undefined;
          this.refresh();
        });
        label.append(box, document.createTextNode(` ${name}`));
        row.append(label);
      }
    }

    table.addEventListener("change", () => {
      if (!table.value) {
        this.ast.join = undefined;
      } else {
        const entry = targets.find((candidate) => candidate.table === table.value);
        this.ast.join = {
          table: table.value,
          on: this.defaultJoinKeys(entry.shared),
        };
      }
      // A join changes which columns exist, so a verb naming one from the old
      // shape has to go with it.
      this.ast.arrange = [];
      this.dropMissingColumns();
      this.refresh();
    });

    wrapper.append(row);
    if (!targets.length) wrapper.hidden = true;
    return wrapper;
  }

  renderFilters() {
    const wrapper = element("section", "phfl-query__verbs");
    wrapper.append(element("h3", null, "Filters"));
    this.ast.filter ??= [];
    this.ast.filter.forEach((clause, index) => {
      wrapper.append(
        this.clauseRow(clause, () => {
          this.ast.filter.splice(index, 1);
          this.refresh();
        }),
      );
    });

    const add = element("button", "phfl-query__add", "Add filter");
    add.type = "button";
    add.addEventListener("click", () => {
      const field = this.columnsFor(this.ast.from)[0];
      const op = OPERATORS_BY_KIND[this.kindFor(field)][0];
      this.ast.filter.push({ field, op, value: "" });
      // Not re-run: a blank value against a numeric column is a cast error, not
      // an empty result, and "Query failed" is a worse answer than a prompt.
      // The status line says so rather than leaving the SQL panel silently
      // describing the previous query.
      this.refresh({ rerun: false });
      this.status.textContent = "Set a value for the new filter to run the query.";
    });
    wrapper.append(add);
    return wrapper;
  }

  renderAggregation() {
    const wrapper = element("section", "phfl-query__verbs");
    wrapper.append(element("h3", null, "Group and summarise"));
    this.ast.groupBy ??= [];
    this.ast.summarise ??= [];

    // Thirteen checkboxes in a row was most of the reason the results table sat
    // a screenful below the controls that build it. Collapsed unless the query
    // already groups by something.
    const box = document.createElement("details");
    box.className = "phfl-query__groupbox";
    box.open = this.ast.groupBy.length > 0;
    const summary = element(
      "summary",
      null,
      this.ast.groupBy.length
        ? `Group by: ${this.ast.groupBy.join(", ")}`
        : "Group by (none)",
    );
    box.append(summary);

    const group = element("div", "phfl-query__verb");
    for (const name of this.availableColumns()) {
      const label = element("label", "phfl-query__group");
      const check = document.createElement("input");
      check.type = "checkbox";
      check.checked = this.ast.groupBy.includes(name);
      check.addEventListener("change", () => {
        this.ast.groupBy = check.checked
          ? [...this.ast.groupBy.filter((n) => n !== name), name]
          : this.ast.groupBy.filter((n) => n !== name);
        this.refresh();
      });
      label.append(check, document.createTextNode(` ${name}`));
      group.append(label);
    }
    box.append(group);
    wrapper.append(box);

    this.ast.summarise.forEach((spec, index) => {
      const row = element("div", "phfl-query__verb");

      const fn = labelledSelect("Summary function");
      fillOptions(fn, AGGREGATES, spec.fn);

      const field = labelledSelect("Summary column");
      const columnChoices = [["", "(all rows)"], ...this.availableColumns()];
      fillOptions(field, columnChoices, spec.field ?? "");

      const alias = document.createElement("input");
      alias.setAttribute("aria-label", "Summary name");
      alias.value = spec.as ?? "";
      alias.className = "phfl-query__alias";

      // The alias names a column the Sort menu can order by, so that menu is
      // patched in place. It used to trigger a full rebuild, which discarded
      // the input the reader had just typed into.
      const syncAlias = () => {
        spec.as = alias.value.trim() || `${spec.fn}_${spec.field ?? "all"}`;
        alias.value = spec.as;
        this.syncSortOptions();
      };

      fn.addEventListener("change", () => {
        spec.fn = fn.value;
        // `count` is the only aggregate that reads as a question without a
        // column; the rest would compile to `sum(NULL)` and answer nothing, so
        // an unset field picks up the first number in the table.
        if (spec.fn !== "count" && !spec.field) {
          spec.field =
            this.availableColumns().find(
              (name) => this.kindFor(name) === "numeric",
            ) ?? this.availableColumns()[0];
          field.value = spec.field;
        }
        if (!alias.dataset.edited) {
          alias.value = `${spec.fn}_${spec.field ?? "all"}`;
          syncAlias();
        }
        this.run();
      });
      field.addEventListener("change", () => {
        spec.field = field.value || undefined;
        if (!alias.dataset.edited) {
          alias.value = `${spec.fn}_${spec.field ?? "all"}`;
          syncAlias();
        }
        this.run();
      });
      alias.addEventListener("input", () => {
        alias.dataset.edited = "1";
      });
      alias.addEventListener("change", () => {
        syncAlias();
        this.run();
      });

      const remove = element("button", "phfl-query__remove", "Remove");
      remove.type = "button";
      remove.setAttribute("aria-label", `Remove summary ${spec.as ?? spec.fn}`);
      remove.addEventListener("click", () => {
        const [removed] = this.ast.summarise.splice(index, 1);
        // The HAVING clauses that named this alias go with it. Left behind they
        // resolve to nothing, so every later compile threw `unknown column` and
        // the builder stayed wedged until the reader worked out which clause to
        // delete. renderSort self-heals the same way for `arrange`.
        if (removed?.as) {
          this.ast.having = (this.ast.having ?? []).filter(
            (clause) => clause.field !== removed.as,
          );
        }
        this.refresh();
      });

      // `sum of points as bench_points`. The joiners are what label the alias
      // box: it used to sit unlabelled between two menus with nothing saying
      // what the reader was meant to type into it.
      row.append(fn, joiner("of"), field, joiner("as"), alias, remove);
      wrapper.append(row);
    });

    const add = element("button", "phfl-query__add", "Add summary");
    add.type = "button";
    add.addEventListener("click", () => {
      this.ast.summarise.push({ fn: "count", as: "rows" });
      this.refresh();
    });
    wrapper.append(add);
    return wrapper;
  }

  // HAVING has always compiled; it just had no control. Without it a grouped
  // query cannot say "owners with more than 20 swung wins", which is the first
  // thing a reader wants after grouping at all.
  renderHaving() {
    const wrapper = element("section", "phfl-query__verbs");
    wrapper.hidden = !(this.ast.groupBy?.length || this.ast.summarise?.length);
    wrapper.append(element("h3", null, "Filter the summaries"));
    this.ast.having ??= [];
    const aliases = (this.ast.summarise ?? []).map((spec) => spec.as).filter(Boolean);

    this.ast.having.forEach((clause, index) => {
      wrapper.append(
        this.clauseRow(
          clause,
          () => {
            this.ast.having.splice(index, 1);
            this.refresh();
          },
          aliases,
        ),
      );
    });

    const add = element("button", "phfl-query__add", "Add summary filter");
    add.type = "button";
    add.disabled = aliases.length === 0;
    add.addEventListener("click", () => {
      // `> 0` is a valid clause on any aggregate, so unlike a fresh filter this
      // one can run immediately and keep the SQL panel honest.
      this.ast.having.push({ field: aliases[0], op: ">", value: 0 });
      this.refresh();
    });
    wrapper.append(add);
    return wrapper;
  }

  sortOptions() {
    const aliases = (this.ast.summarise ?? []).map((spec) => spec.as).filter(Boolean);
    const grouped = this.ast.groupBy ?? [];
    // A grouped query can only order by a grouping column or an aggregate; the
    // full column list would offer keys the SQL rejects.
    return grouped.length || aliases.length
      ? [...grouped, ...aliases]
      : this.availableColumns();
  }

  syncSortOptions() {
    if (!this.sortField) return;
    const options = this.sortOptions();
    const current = this.ast.arrange?.[0]?.field;
    fillOptions(this.sortField, options, options.includes(current) ? current : options[0]);
    this.applySort();
  }

  applySort() {
    if (!this.sortField?.value) {
      this.ast.arrange = [];
      return;
    }
    this.ast.arrange = [{ field: this.sortField.value, dir: this.sortDir.value }];
  }

  renderSort() {
    const wrapper = element("section", "phfl-query__verbs");
    wrapper.append(element("h3", null, "Sort"));
    const options = this.sortOptions();
    const current = this.ast.arrange?.[0];
    const field = options.includes(current?.field) ? current.field : options[0];
    const dir = current?.dir === "asc" ? "asc" : "desc";

    this.sortField = labelledSelect("Sort column");
    fillOptions(this.sortField, options, field);
    this.sortDir = labelledSelect("Sort direction");
    fillOptions(this.sortDir, [["desc", "high to low"], ["asc", "low to high"]], dir);

    // Written back on render, not only on change. The menu used to display a
    // sort the AST did not carry: switching dataset left `arrange: []` while
    // the control read "year, high to low", so the SQL had no ORDER BY at all
    // and LIMIT took an arbitrary slice of the table.
    this.applySort();

    const apply = () => {
      this.applySort();
      this.run();
    };
    this.sortField.addEventListener("change", apply);
    this.sortDir.addEventListener("change", apply);

    const row = element("div", "phfl-query__verb");
    row.append(this.sortField, this.sortDir);
    wrapper.append(row);
    return wrapper;
  }

  renderLimit() {
    const wrapper = element("section", "phfl-query__verbs");
    wrapper.append(element("h3", null, "Rows"));
    const input = document.createElement("input");
    input.type = "number";
    input.min = "1";
    input.max = String(MAX_LIMIT);
    input.step = "25";
    input.className = "phfl-query__limit";
    input.setAttribute("aria-label", `Maximum rows, up to ${MAX_LIMIT}`);
    input.value = String(this.ast.limit ?? 200);
    input.addEventListener("change", () => {
      const wanted = Math.trunc(Number(input.value)) || 200;
      this.ast.limit = Math.min(Math.max(wanted, 1), MAX_LIMIT);
      input.value = String(this.ast.limit);
      this.run();
    });
    const row = element("div", "phfl-query__verb");
    row.append(input);
    wrapper.append(row);
    return wrapper;
  }

  async run() {
    let compiled;
    try {
      compiled = compileAst(this.ast, this.schema);
    } catch (error) {
      this.results.innerHTML = "";
      this.status.textContent = `That query is not valid: ${error.message}`;
      return;
    }
    this.sqlCode.textContent = renderSql(compiled.sql, compiled.params);
    this.writeUrl();
    this.status.textContent = "Running…";
    // Every edit runs the query, so a slow one must not be able to paint over
    // the result of a later, faster one.
    const token = ++this.runToken;
    try {
      const [{ columns, rows }, counted] = await Promise.all([
        runSql(this.base, compiled.sql, compiled.params),
        runSql(this.base, compiled.countSql, compiled.params).catch(() => null),
      ]);
      if (token !== this.runToken) return;
      this.renderTable(columns, rows, counted?.rows?.[0]?.n ?? null);
    } catch (error) {
      if (token !== this.runToken) return;
      this.results.innerHTML = "";
      this.status.textContent = `Query failed: ${error.message}`;
    }
  }

  // A column the returned page has no value for anywhere. `round` is null on
  // every regular-season row, so the default matchups query spent one of the
  // five columns that fit on screen showing nothing at all. Dropped from the
  // render only -- the query still selects it, so sorting or filtering on it
  // stays available and it reappears the moment a row carries one.
  static nonEmpty(columns, rows) {
    const kept = columns.filter((column) =>
      rows.some((row) => row[column] !== null && row[column] !== undefined && row[column] !== ""),
    );
    // A grouped count over an all-null column is a legitimate empty result;
    // never render a table with no columns at all.
    return kept.length ? kept : columns;
  }

  renderTable(allColumns, rows, total) {
    this.results.innerHTML = "";
    // "200 rows" was the LIMIT, not the number of matches: an unfiltered draft
    // query reported 200 when 1,320 picks matched.
    this.status.textContent =
      total !== null && total > rows.length
        ? `Showing ${rows.length.toLocaleString()} of ${total.toLocaleString()} matching rows`
        : `${rows.length.toLocaleString()} rows`;
    if (rows.length === 0) {
      this.results.append(
        element("p", "phfl-query__empty", "No rows match. Adjust a filter, or try a preset."),
      );
      return;
    }
    const columns = StatSearch.nonEmpty(allColumns, rows);
    const table = document.createElement("table");
    const caption = element(
      "caption",
      "phfl-query__caption",
      `${this.ast.from.replaceAll("_", " ")}: ${this.status.textContent.toLowerCase()}`,
    );
    table.append(caption);
    const thead = document.createElement("thead");
    const head = document.createElement("tr");
    const sortable = new Set(this.sortOptions());
    const current = this.ast.arrange?.[0];
    for (const column of columns) {
      const th = document.createElement("th");
      th.scope = "col";
      if (!sortable.has(column)) {
        th.textContent = column;
        head.append(th);
        continue;
      }
      const active = current?.field === column;
      th.setAttribute("aria-sort", active ? (current.dir === "asc" ? "ascending" : "descending") : "none");
      const button = element("button", "phfl-query__sort", column);
      button.type = "button";
      button.setAttribute("aria-label", `Sort by ${column}`);
      // Sorting is pushed into the query rather than done to the DOM. Reordering
      // the returned page only reordered the LIMIT'd slice, and left the SQL
      // panel and the shared link describing an order nobody was looking at.
      button.addEventListener("click", () => {
        const dir = active && current.dir === "desc" ? "asc" : "desc";
        this.ast.arrange = [{ field: column, dir }];
        if (this.sortField) {
          this.sortField.value = column;
          this.sortDir.value = dir;
        }
        this.run();
      });
      th.append(button);
      head.append(th);
    }
    thead.append(head);
    table.append(thead);
    const tbody = document.createElement("tbody");
    const aliases = new Set((this.ast.summarise ?? []).map((s) => s.as));
    for (const row of rows) {
      const tr = document.createElement("tr");
      for (const column of columns) {
        const cell = document.createElement("td");
        const linker = LINKED[column];
        const text = formatCell(row[column]);
        // Team names run to 218px against a 57px `year`, so two of the twelve
        // columns took a third of the table. The cell is capped in CSS and the
        // full value moves to the tooltip rather than being lost.
        if (text) cell.title = text;
        if (linker && !aliases.has(column) && row[column]) {
          const link = element("a", null, String(row[column]));
          link.href = new URL(linker(row, column), this.siteBase).href;
          cell.append(link);
        } else {
          cell.textContent = text;
        }
        tr.append(cell);
      }
      tbody.append(tr);
    }
    table.append(tbody);
    this.results.append(table);

    // Thirteen columns are wider than the panel, and the column the rows are
    // ordered by is often one of the ones past its right edge -- the default
    // matchups query sorts by `margin`, which sat off-screen. Bring it into
    // view horizontally only: scrollIntoView would also jump the page.
    const sorted = head.children[columns.indexOf(current?.field)];
    if (sorted) {
      const gap = sorted.offsetLeft + sorted.offsetWidth - this.results.clientWidth;
      this.results.scrollLeft = gap > 0 ? gap + 8 : 0;
    }
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
        typeof parsed.from === "string" &&
        Object.hasOwn(this.schema.tables, parsed.from)
      ) {
        // Trial-compiled before it is adopted. Checking `from` alone let a
        // link whose `filter` was a string through to renderBuilder, which
        // runs before run()'s own compile and threw a TypeError that start()
        // turned into the fatal "could not start" panel. The compiler already
        // validates every verb's shape, so a throw here is the whole check.
        compileAst(parsed, this.schema);
        this.ast = parsed;
      }
    } catch {
      // A malformed link falls back to the default preset rather than erroring.
    }
  }
}

function parseValue(raw, op) {
  if (MULTI_VALUE.has(op)) {
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

export function formatCell(value) {
  if (typeof value === "number" && !Number.isInteger(value)) return value.toFixed(2);
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value ?? "");
}

// `navigation.instant` swaps the article without replacing the document, and a
// `type="module"` script is evaluated once per URL per document -- so the tag
// re-inserted on the way back to /query/ never ran, and the page showed its
// "needs JavaScript enabled" fallback to readers who had it enabled. document$
// fires on every instant navigation, which is the theme's own answer to this.
function mount() {
  const root = document.getElementById("phfl-query");
  if (!root || root.dataset.mounted === "1") return;
  root.dataset.mounted = "1";
  const base = root.dataset.queryBase ?? "../query/";
  new StatSearch(root, base).start();
}

// Guarded so the module can be imported outside a browser. Everything above is
// declarations; this block is the only statement that touches `window`, and an
// unguarded reference threw ReferenceError the moment a test tried to import
// the file -- which is why the builder had no unit tests and the compiler did.
if (typeof window !== "undefined") {
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(mount);
  } else {
    mount();
  }
}
