/**
 * NightOwls browse catalog — schema-driven search / views / sort.
 *
 * MAINTAINABILITY: add a metadata category by:
 *   1. Exposing it as data-* on each .card in peer/templates/index.html
 *      (enrich in peer/app.py _enrich_files if needed)
 *   2. Appending one object to FILE_FIELDS below
 *   3. Flags: list (table column), sortable, searchable, primary (title highlight)
 *
 * Do not hard-code column lists elsewhere — read from FILE_FIELDS / helpers.
 */
(() => {
  const STORAGE_VIEW = "nightowls.browse.view";
  const STORAGE_SORT = "nightowls.browse.sort";

  /** @typedef {"string"|"number"} FieldType */

  /**
   * @type {Array<{
   *   id: string,
   *   label: string,
   *   type: FieldType,
   *   list?: boolean,
   *   sortable?: boolean,
   *   searchable?: boolean,
   *   primary?: boolean,
   *   getDisplay: (el: Element) => string,
   *   getSortValue: (el: Element) => string|number,
   *   getSearchValues?: (el: Element) => string[],
   * }>}
   */
  const FILE_FIELDS = [
    {
      id: "name",
      label: "Name",
      type: "string",
      list: true,
      sortable: true,
      searchable: true,
      primary: true,
      getDisplay: (el) => el.getAttribute("data-name") || "",
      getSortValue: (el) => (el.getAttribute("data-name") || "").toLowerCase(),
      getSearchValues: (el) => [el.getAttribute("data-name") || ""],
    },
    {
      id: "ext",
      label: "Type",
      type: "string",
      list: true,
      sortable: true,
      searchable: true,
      getDisplay: (el) => {
        const ext = (el.getAttribute("data-ext") || "").trim();
        return ext ? ext.toUpperCase() : "—";
      },
      getSortValue: (el) => (el.getAttribute("data-ext") || "").toLowerCase(),
      getSearchValues: (el) => {
        const ext = (el.getAttribute("data-ext") || "").toLowerCase();
        return ext ? [ext, `.${ext}`] : [];
      },
    },
    {
      id: "size",
      label: "Size",
      type: "number",
      list: true,
      sortable: true,
      searchable: true,
      getDisplay: (el) => el.getAttribute("data-size") || "—",
      getSortValue: (el) => Number(el.getAttribute("data-size-bytes") || 0),
      getSearchValues: (el) => [el.getAttribute("data-size") || ""],
    },
    {
      id: "seeders",
      label: "Seeders",
      type: "number",
      list: true,
      sortable: true,
      searchable: true,
      getDisplay: (el) => el.getAttribute("data-seeders") || "0",
      getSortValue: (el) => Number(el.getAttribute("data-seeders") || 0),
      getSearchValues: (el) => [el.getAttribute("data-seeders") || ""],
    },
    {
      id: "chunks",
      label: "Chunks",
      type: "number",
      list: true,
      sortable: true,
      searchable: true,
      getDisplay: (el) => el.getAttribute("data-chunks") || "0",
      getSortValue: (el) => Number(el.getAttribute("data-chunks") || 0),
      getSearchValues: (el) => [el.getAttribute("data-chunks") || ""],
    },
    {
      id: "id",
      label: "ID",
      type: "number",
      list: true,
      sortable: true,
      searchable: true,
      getDisplay: (el) => el.getAttribute("data-file-id") || "",
      getSortValue: (el) => Number(el.getAttribute("data-file-id") || 0),
      getSearchValues: (el) => [el.getAttribute("data-file-id") || ""],
    },
    {
      id: "hash",
      label: "Hash",
      type: "string",
      // Hidden from default list (noisy); still searchable/sortable when enabled later.
      list: false,
      sortable: true,
      searchable: true,
      getDisplay: (el) => {
        const h = el.getAttribute("data-hash") || "";
        return h ? `${h.slice(0, 10)}…` : "—";
      },
      getSortValue: (el) => (el.getAttribute("data-hash") || "").toLowerCase(),
      getSearchValues: (el) => [el.getAttribute("data-hash") || ""],
    },
    {
      id: "created",
      label: "Added",
      type: "string",
      list: false,
      sortable: true,
      searchable: false,
      getDisplay: (el) => el.getAttribute("data-created") || "—",
      getSortValue: (el) => el.getAttribute("data-created") || "",
    },
  ];

  const listFields = () => FILE_FIELDS.filter((f) => f.list);
  const sortableFields = () => FILE_FIELDS.filter((f) => f.sortable);
  const fieldById = (id) => FILE_FIELDS.find((f) => f.id === id);

  const $ = (sel, root = document) => root.querySelector(sel);

  const grid = $("#file-grid");
  const searchInput = $("#file-search");
  if (!grid || !searchInput) return;

  const cards = Array.from(grid.querySelectorAll(".card"));
  if (!cards.length) return;

  const metaEl = $("#file-search-meta");
  const emptyEl = $("#file-search-empty");
  const clearBtn = $("#file-search-clear");
  const resetBtn = $("#file-search-reset");
  const listWrap = $("#file-list-wrap");
  const table = $("#file-table");
  const viewToggle = $("#view-toggle");
  const sortSelect = $("#browse-sort");

  const originals = new Map(
    cards.map((card, i) => {
      const name = card.getAttribute("data-name") || "";
      const title = card.querySelector(".card-title, h2");
      if (title) title.dataset.raw = name;
      return [card, i];
    })
  );

  /** @type {Map<Element, HTMLTableRowElement>} */
  const rowByCard = new Map();

  let composing = false;
  let raf = 0;
  let viewMode = loadView();
  let sortState = loadSort();
  let lastQuery = "";

  /* ---------- utils ---------- */

  function loadView() {
    try {
      const v = localStorage.getItem(STORAGE_VIEW);
      return v === "list" ? "list" : "card";
    } catch {
      return "card";
    }
  }

  function saveView(v) {
    try {
      localStorage.setItem(STORAGE_VIEW, v);
    } catch {
      /* ignore */
    }
  }

  function loadSort() {
    try {
      const raw = localStorage.getItem(STORAGE_SORT);
      if (!raw) return { field: "id", dir: "asc" };
      const parsed = JSON.parse(raw);
      if (!fieldById(parsed.field)?.sortable) return { field: "id", dir: "asc" };
      return {
        field: parsed.field,
        dir: parsed.dir === "desc" ? "desc" : "asc",
      };
    } catch {
      return { field: "id", dir: "asc" };
    }
  }

  function saveSort(state) {
    try {
      localStorage.setItem(STORAGE_SORT, JSON.stringify(state));
    } catch {
      /* ignore */
    }
  }

  function normalize(s) {
    return String(s || "")
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "");
  }

  function tokens(q) {
    return normalize(q)
      .split(/[\s/_.,:;+\-]+/)
      .map((t) => t.trim())
      .filter(Boolean);
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function highlight(name, toks) {
    if (!toks.length) return escapeHtml(name);
    const lower = normalize(name);
    const ranges = [];
    for (const tok of toks) {
      let from = 0;
      while (from < lower.length) {
        const at = lower.indexOf(tok, from);
        if (at < 0) break;
        ranges.push([at, at + tok.length]);
        from = at + tok.length;
      }
    }
    if (!ranges.length) return escapeHtml(name);
    ranges.sort((a, b) => a[0] - b[0] || b[1] - a[1]);
    const merged = [];
    for (const r of ranges) {
      const last = merged[merged.length - 1];
      if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
      else merged.push([...r]);
    }
    let out = "";
    let cursor = 0;
    for (const [a, b] of merged) {
      out += escapeHtml(name.slice(cursor, a));
      out += `<mark>${escapeHtml(name.slice(a, b))}</mark>`;
      cursor = b;
    }
    return out + escapeHtml(name.slice(cursor));
  }

  function downloadHref(card) {
    const a = card.querySelector(".card-actions a[href]");
    return a ? a.getAttribute("href") : `#`;
  }

  /* ---------- Phase 1: list table from schema ---------- */

  function buildListTable() {
    if (!table || !listWrap) return;
    const cols = listFields();
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const field of cols) {
      const th = document.createElement("th");
      th.scope = "col";
      th.dataset.field = field.id;
      if (field.sortable) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "th-sort";
        btn.dataset.field = field.id;
        btn.innerHTML = `<span>${escapeHtml(field.label)}</span><span class="sort-ind" aria-hidden="true"></span>`;
        th.appendChild(btn);
      } else {
        th.textContent = field.label;
      }
      headRow.appendChild(th);
    }
    const actionTh = document.createElement("th");
    actionTh.scope = "col";
    actionTh.className = "col-actions";
    actionTh.textContent = "";
    headRow.appendChild(actionTh);
    thead.appendChild(headRow);

    const tbody = document.createElement("tbody");
    tbody.id = "file-table-body";
    for (const card of cards) {
      const tr = document.createElement("tr");
      tr.dataset.fileId = card.getAttribute("data-file-id") || "";
      for (const field of cols) {
        const td = document.createElement("td");
        td.dataset.field = field.id;
        if (field.primary) {
          td.className = "col-name";
          td.innerHTML = `<span class="list-name">${escapeHtml(field.getDisplay(card))}</span>`;
        } else {
          td.textContent = field.getDisplay(card);
        }
        if (field.id === "hash" || field.id === "id") td.classList.add("mono");
        tr.appendChild(td);
      }
      const act = document.createElement("td");
      act.className = "col-actions";
      act.innerHTML = `<a class="btn btn-primary btn-compact" href="${escapeHtml(downloadHref(card))}">Download</a>`;
      tr.appendChild(act);
      tbody.appendChild(tr);
      rowByCard.set(card, tr);
    }

    table.replaceChildren(thead, tbody);

    table.addEventListener("click", (e) => {
      const btn = e.target.closest("button.th-sort");
      if (!btn) return;
      const field = btn.dataset.field;
      if (!fieldById(field)?.sortable) return;
      if (sortState.field === field) {
        sortState = { field, dir: sortState.dir === "asc" ? "desc" : "asc" };
      } else {
        sortState = { field, dir: fieldById(field)?.type === "string" ? "asc" : "desc" };
      }
      saveSort(sortState);
      syncSortControls();
      render();
    });
  }

  /* ---------- search scoring (schema-backed haystack) ---------- */

  function searchBag(card) {
    const values = [];
    for (const field of FILE_FIELDS) {
      if (!field.searchable) continue;
      const getter = field.getSearchValues || ((el) => [field.getDisplay(el)]);
      for (const v of getter(card)) values.push(normalize(v));
    }
    return values.filter(Boolean);
  }

  function scoreCard(card, query, toks) {
    const name = normalize(card.getAttribute("data-name"));
    const id = String(card.getAttribute("data-file-id") || "");
    const hash = normalize(card.getAttribute("data-hash"));
    const ext = normalize(card.getAttribute("data-ext"));
    const bag = searchBag(card);
    const hay = bag.join(" ");

    if (!query) return { score: 0, match: true };

    let score = 0;
    if (name === query) score += 1000;
    else if (name.startsWith(query)) score += 800;
    else if (name.includes(query)) score += 500;

    if (id === query) score += 900;
    else if (id.startsWith(query)) score += 450;

    const qExt = query.startsWith(".") ? query.slice(1) : query;
    if (ext && (ext === qExt || `.${ext}` === query)) score += 420;
    if (query.length >= 4 && hash.startsWith(query)) score += 380;

    if (toks.length) {
      let all = true;
      for (const tok of toks) {
        const inName = name.includes(tok);
        const namePrefix = name.split(/[\s._\-]+/).some((p) => p.startsWith(tok));
        const elsewhere = bag.some((v) => v.includes(tok)) || hay.includes(tok);
        if (!inName && !namePrefix && !elsewhere) {
          all = false;
          break;
        }
        if (namePrefix) score += 120;
        else if (inName) score += 80;
        else score += 25;
      }
      if (!all) return { score: -1, match: false };
    } else if (score <= 0 && !hay.includes(query)) {
      return { score: -1, match: false };
    }

    score += Math.min(40, Number(card.getAttribute("data-seeders") || 0));
    score -= Math.min(30, Math.floor(name.length / 8));
    return { score, match: score >= 0 };
  }

  /* ---------- Phase 2: sorting ---------- */

  function compareCards(a, b) {
    const field = fieldById(sortState.field) || fieldById("id");
    const dir = sortState.dir === "desc" ? -1 : 1;
    const av = field.getSortValue(a);
    const bv = field.getSortValue(b);
    let cmp = 0;
    if (typeof av === "number" && typeof bv === "number") {
      cmp = av - bv;
    } else {
      cmp = String(av).localeCompare(String(bv), undefined, {
        numeric: true,
        sensitivity: "base",
      });
    }
    if (cmp !== 0) return cmp * dir;
    return originals.get(a) - originals.get(b);
  }

  function syncSortControls() {
    if (sortSelect) {
      const key = `${sortState.field}:${sortState.dir}`;
      if ([...sortSelect.options].some((o) => o.value === key)) {
        sortSelect.value = key;
      }
    }
    if (!table) return;
    table.querySelectorAll("button.th-sort").forEach((btn) => {
      const active = btn.dataset.field === sortState.field;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-sort", active ? (sortState.dir === "asc" ? "ascending" : "descending") : "none");
      const ind = btn.querySelector(".sort-ind");
      if (ind) ind.textContent = active ? (sortState.dir === "asc" ? "↑" : "↓") : "";
    });
  }

  function populateSortSelect() {
    if (!sortSelect) return;
    sortSelect.replaceChildren();
    for (const field of sortableFields()) {
      for (const dir of ["asc", "desc"]) {
        const opt = document.createElement("option");
        opt.value = `${field.id}:${dir}`;
        const arrow = dir === "asc" ? "↑" : "↓";
        opt.textContent = `${field.label} ${arrow}`;
        sortSelect.appendChild(opt);
      }
    }
    sortSelect.addEventListener("change", () => {
      const [field, dir] = sortSelect.value.split(":");
      if (!fieldById(field)?.sortable) return;
      sortState = { field, dir: dir === "desc" ? "desc" : "asc" };
      saveSort(sortState);
      syncSortControls();
      render();
    });
  }

  /* ---------- view mode ---------- */

  function applyViewMode() {
    const isList = viewMode === "list";
    document.body.classList.toggle("view-list", isList);
    document.body.classList.toggle("view-card", !isList);
    grid.hidden = isList;
    if (listWrap) listWrap.hidden = !isList;
    if (viewToggle) {
      viewToggle.querySelectorAll("[data-view]").forEach((btn) => {
        const on = btn.getAttribute("data-view") === viewMode;
        btn.classList.toggle("is-active", on);
        btn.setAttribute("aria-pressed", on ? "true" : "false");
      });
    }
  }

  function setView(mode) {
    viewMode = mode === "list" ? "list" : "card";
    saveView(viewMode);
    applyViewMode();
  }

  /* ---------- render pipeline ---------- */

  function render() {
    const query = normalize(lastQuery).trim();
    const toks = tokens(query);
    const ranked = cards.map((card) => {
      const { score, match } = scoreCard(card, query, toks);
      return { card, score, match };
    });

    ranked.sort((a, b) => {
      if (a.match !== b.match) return a.match ? -1 : 1;
      if (query) {
        if (b.score !== a.score) return b.score - a.score;
        return compareCards(a.card, b.card);
      }
      return compareCards(a.card, b.card);
    });

    let shown = 0;
    const gridFrag = document.createDocumentFragment();
    const body = table && table.querySelector("tbody");
    const bodyFrag = document.createDocumentFragment();

    for (const { card, match } of ranked) {
      const title = card.querySelector(".card-title, h2");
      const rawName = title?.dataset.raw || card.getAttribute("data-name") || "";
      if (title) {
        title.innerHTML =
          match && query ? highlight(rawName, toks.length ? toks : [query]) : escapeHtml(rawName);
      }
      card.classList.toggle("is-hidden", !match);
      gridFrag.appendChild(card);

      const row = rowByCard.get(card);
      if (row) {
        row.hidden = !match;
        const nameCell = row.querySelector(".list-name");
        if (nameCell) {
          nameCell.innerHTML =
            match && query ? highlight(rawName, toks.length ? toks : [query]) : escapeHtml(rawName);
        }
        bodyFrag.appendChild(row);
      }
      if (match) shown += 1;
    }

    grid.appendChild(gridFrag);
    if (body) body.appendChild(bodyFrag);

    if (clearBtn) clearBtn.hidden = !query;
    if (emptyEl) emptyEl.hidden = shown !== 0;
    if (metaEl) {
      const sortLabel = fieldById(sortState.field)?.label || sortState.field;
      const dirMark = sortState.dir === "asc" ? "↑" : "↓";
      if (!query) {
        metaEl.textContent = `${cards.length} file${cards.length === 1 ? "" : "s"} · ${sortLabel} ${dirMark}`;
      } else {
        metaEl.textContent = `${shown} of ${cards.length} match${shown === 1 ? "" : "es"} · ${sortLabel} ${dirMark}`;
      }
    }
  }

  function scheduleRender() {
    if (composing) return;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => {
      lastQuery = searchInput.value;
      render();
    });
  }

  /* ---------- wire UI ---------- */

  buildListTable();
  populateSortSelect();
  syncSortControls();
  applyViewMode();

  if (viewToggle) {
    viewToggle.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-view]");
      if (!btn) return;
      setView(btn.getAttribute("data-view"));
    });
  }

  searchInput.addEventListener("compositionstart", () => {
    composing = true;
  });
  searchInput.addEventListener("compositionend", () => {
    composing = false;
    scheduleRender();
  });
  searchInput.addEventListener("input", scheduleRender);

  function clearSearch() {
    searchInput.value = "";
    lastQuery = "";
    render();
    searchInput.focus();
  }
  if (clearBtn) clearBtn.addEventListener("click", clearSearch);
  if (resetBtn) resetBtn.addEventListener("click", clearSearch);

  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement !== searchInput && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const tag = (document.activeElement && document.activeElement.tagName) || "";
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      e.preventDefault();
      searchInput.focus();
      searchInput.select();
    }
    if (e.key === "Escape" && document.activeElement === searchInput) {
      clearSearch();
    }
  });

  // Expose schema for debugging / future admin tools
  window.NightOwlsFileCatalog = {
    FILE_FIELDS,
    listFields,
    sortableFields,
    fieldById,
  };

  lastQuery = searchInput.value;
  render();
})();
