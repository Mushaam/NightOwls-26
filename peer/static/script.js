(() => {
  const $ = (sel, root = document) => root.querySelector(sel);

  function setStatus(el, message, kind) {
    if (!el) return;
    el.textContent = message;
    el.classList.remove("ok", "err", "warn");
    if (kind) el.classList.add(kind);
  }

  function formatBytes(n) {
    if (n == null || Number.isNaN(n)) return "—";
    const units = ["B", "KB", "MB", "GB"];
    let v = Number(n);
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
      v /= 1024;
      i += 1;
    }
    return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
  }

  function plural(n, one, many) {
    return Number(n) === 1 ? one : many;
  }

  /* ---- Upload page ---- */
  const dropzone = $("#dropzone");
  const fileInput = $("#file-input");
  const uploadBtn = $("#upload-btn");
  const uploadStatus = $("#upload-status");
  let selectedFile = null;

  if (dropzone && fileInput) {
    const pick = () => fileInput.click();
    dropzone.addEventListener("click", pick);
    dropzone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        pick();
      }
    });

    ["dragenter", "dragover"].forEach((evt) => {
      dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzone.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach((evt) => {
      dropzone.addEventListener(evt, (e) => {
        e.preventDefault();
        dropzone.classList.remove("dragover");
      });
    });
    dropzone.addEventListener("drop", (e) => {
      const file = e.dataTransfer?.files?.[0];
      if (file) chooseFile(file);
    });
    fileInput.addEventListener("change", () => {
      const file = fileInput.files?.[0];
      if (file) chooseFile(file);
    });
  }

  function chooseFile(file) {
    selectedFile = file;
    if (uploadBtn) uploadBtn.disabled = false;
    setStatus(
      uploadStatus,
      `Selected: ${file.name} (${formatBytes(file.size)})`,
      null
    );
  }

  if (uploadBtn) {
    uploadBtn.addEventListener("click", async () => {
      if (!selectedFile) return;
      uploadBtn.disabled = true;
      setStatus(uploadStatus, "Chunking, hashing, and registering with tracker…");
      const body = new FormData();
      body.append("file", selectedFile);
      try {
        const res = await fetch("/api/upload", { method: "POST", body });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Upload failed");
        setStatus(
          uploadStatus,
          `Seeded “${data.filename}” as file #${data.file_id} (${data.chunk_count} chunks).`,
          "ok"
        );
      } catch (err) {
        setStatus(uploadStatus, err.message || String(err), "err");
        uploadBtn.disabled = false;
      }
    });
  }

  /* ---- Browse search ---- */
  const fileGrid = $("#file-grid");
  const searchInput = $("#file-search");
  if (fileGrid && searchInput) {
    const cards = Array.from(fileGrid.querySelectorAll(".card"));
    const metaEl = $("#file-search-meta");
    const emptyEl = $("#file-search-empty");
    const clearBtn = $("#file-search-clear");
    const resetBtn = $("#file-search-reset");
    const originals = new Map(
      cards.map((card, i) => {
        const name = card.getAttribute("data-name") || "";
        const title = card.querySelector(".card-title, h2");
        if (title) title.dataset.raw = name;
        return [card, i];
      })
    );

    let composing = false;
    let raf = 0;

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
        if (!tok) continue;
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
      out += escapeHtml(name.slice(cursor));
      return out;
    }

    function scoreCard(card, query, toks) {
      const name = normalize(card.getAttribute("data-name"));
      const id = String(card.getAttribute("data-file-id") || "");
      const hash = normalize(card.getAttribute("data-hash"));
      const ext = normalize(card.getAttribute("data-ext"));
      const size = normalize(card.getAttribute("data-size"));
      const seeders = String(card.getAttribute("data-seeders") || "");
      const chunks = String(card.getAttribute("data-chunks") || "");
      const hay = `${name} ${id} ${hash} ${ext} ${size} ${seeders} ${chunks}`;

      if (!query) return { score: 0, match: true };

      let score = 0;

      // Exact / prefix filename wins
      if (name === query) score += 1000;
      else if (name.startsWith(query)) score += 800;
      else if (name.includes(query)) score += 500;

      // File id
      if (id === query) score += 900;
      else if (id.startsWith(query)) score += 450;

      // Extension: "pdf" or ".pdf"
      const qExt = query.startsWith(".") ? query.slice(1) : query;
      if (ext && (ext === qExt || `.${ext}` === query)) score += 420;

      // Hash prefix (at least 4 chars to avoid noise)
      if (query.length >= 4 && hash.startsWith(query)) score += 380;

      // Token AND: every token must hit somewhere useful
      if (toks.length) {
        let all = true;
        for (const tok of toks) {
          const inName = name.includes(tok);
          const namePrefix = name.split(/[\s._\-]+/).some((p) => p.startsWith(tok));
          const elsewhere =
            id.includes(tok) ||
            hash.includes(tok) ||
            ext === tok ||
            size.includes(tok) ||
            seeders === tok ||
            chunks === tok ||
            hay.includes(tok);
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

      // Prefer shorter names / more seeders slightly when tied
      score += Math.min(40, Number(seeders) || 0);
      score -= Math.min(30, Math.floor(name.length / 8));

      return { score, match: score >= 0 };
    }

    function applySearch(raw) {
      const query = normalize(raw).trim();
      const toks = tokens(query);
      const ranked = cards.map((card) => {
        const { score, match } = scoreCard(card, query, toks);
        return { card, score, match };
      });

      ranked.sort((a, b) => {
        if (a.match !== b.match) return a.match ? -1 : 1;
        if (query) {
          if (b.score !== a.score) return b.score - a.score;
        }
        return originals.get(a.card) - originals.get(b.card);
      });

      let shown = 0;
      const frag = document.createDocumentFragment();
      for (const { card, match } of ranked) {
        const title = card.querySelector(".card-title, h2");
        const rawName = title?.dataset.raw || card.getAttribute("data-name") || "";
        if (title) {
          title.innerHTML = match && query ? highlight(rawName, toks.length ? toks : [query]) : escapeHtml(rawName);
        }
        card.classList.toggle("is-hidden", !match);
        if (match) {
          shown += 1;
          frag.appendChild(card);
        } else {
          frag.appendChild(card);
        }
      }
      fileGrid.appendChild(frag);

      if (clearBtn) clearBtn.hidden = !query;
      if (emptyEl) emptyEl.hidden = shown !== 0;
      if (metaEl) {
        if (!query) {
          metaEl.textContent = `${cards.length} file${cards.length === 1 ? "" : "s"}`;
        } else {
          metaEl.textContent = `${shown} of ${cards.length} match${shown === 1 ? "" : "es"}`;
        }
      }
    }

    function scheduleApply() {
      if (composing) return;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => applySearch(searchInput.value));
    }

    searchInput.addEventListener("compositionstart", () => {
      composing = true;
    });
    searchInput.addEventListener("compositionend", () => {
      composing = false;
      scheduleApply();
    });
    searchInput.addEventListener("input", scheduleApply);

    function clearSearch() {
      searchInput.value = "";
      applySearch("");
      searchInput.focus();
    }
    if (clearBtn) clearBtn.addEventListener("click", clearSearch);
    if (resetBtn) resetBtn.addEventListener("click", clearSearch);

    document.addEventListener("keydown", (e) => {
      if (e.key === "/" && document.activeElement !== searchInput && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const tag = (document.activeElement && document.activeElement.tagName) || "";
        if (tag === "INPUT" || tag === "TEXTAREA") return;
        e.preventDefault();
        searchInput.focus();
        searchInput.select();
      }
      if (e.key === "Escape" && document.activeElement === searchInput) {
        clearSearch();
      }
    });

    applySearch("");
  }

  /* ---- Download page ---- */
  const panel = document.querySelector(".panel[data-file-id]");
  const startBtn = $("#start-download");
  if (panel && startBtn) {
  const fileId = panel.getAttribute("data-file-id");
  const bar = $("#progress-bar");
  const percentEl = $("#progress-percent");
  const textEl = $("#progress-text");
  const statusEl = $("#download-status");
  const peerCountEl = $("#peer-count");
  const alreadyComplete = panel.getAttribute("data-already-complete") === "1";
  let pollTimer = null;
  let lastPeers = null;
  let downloadActive = false;

  const savePathEl = $("#save-path");
  const saveBox = $("#save-box");
  const expectedPath = panel.getAttribute("data-expected-path") || "";

  const ACTIVE = new Set([
    "starting",
    "running",
    "chunk_ok",
    "skip_existing",
    "no_peers",
    "chunk_failed",
  ]);

  function showSavePath(path) {
    if (!savePathEl || !path) return;
    savePathEl.textContent = path;
    if (saveBox) saveBox.classList.add("ready");
  }

  function bumpPeerCount(n) {
    if (!peerCountEl || n == null) return;
    const value = String(n);
    if (peerCountEl.textContent !== value) {
      peerCountEl.textContent = value;
      peerCountEl.classList.remove("bump");
      // Force reflow so the animation retriggers when peers change.
      void peerCountEl.offsetWidth;
      peerCountEl.classList.add("bump");
    }
    lastPeers = n;
  }

  function statusCopy(data) {
    const pct = Number(data.percent || 0);
    const peers = data.peers_known ?? 0;
    const have = data.chunks_have || 0;
    const total = data.chunks_total || "?";
    const status = data.status || "idle";

    if (status === "complete") {
      return { text: "Complete — file saved to the path above.", kind: "ok" };
    }
    if (status === "error") {
      return {
        text: data.error || "Download failed. Other peers may still have chunks — try again.",
        kind: "err",
      };
    }
    if (data.warning || status === "no_peers" || status === "chunk_failed") {
      const warn =
        data.warning ||
        "A peer dropped mid-download. Retrying other seeders…";
      return {
        text: `${pct}% complete · ${warn}`,
        kind: "warn",
      };
    }
    if (status === "starting") {
      return { text: "Starting swarm download…", kind: null };
    }
    if (status === "idle") {
      return {
        text: alreadyComplete
          ? "Already on disk — open the path above, or download again to refresh."
          : "Ready — download will start automatically, or click Start download.",
        kind: null,
      };
    }
    return {
      text: `${pct}% complete, fetching from ${peers} ${plural(peers, "peer", "peers")} (${have}/${total} chunks)`,
      kind: null,
    };
  }

  function applyProgress(data) {
    const pct = Number(data.percent || 0);
    const status = data.status || "idle";
    if (bar) bar.style.width = `${pct}%`;
    if (percentEl) percentEl.textContent = `${pct}%`;
    if (textEl) {
      const peers = data.peers_known ?? 0;
      textEl.textContent = `${data.chunks_have || 0}/${data.chunks_total || "?"} chunks · ${pct}% · ${peers} ${plural(peers, "peer", "peers")}`;
    }
    bumpPeerCount(data.peers_known);

    if (data.path) {
      showSavePath(data.path);
    }

    const copy = statusCopy(data);
    setStatus(statusEl, copy.text, copy.kind);

    if (status === "complete") {
      showSavePath(data.path || expectedPath || "local store");
      stopPoll();
      downloadActive = false;
      startBtn.disabled = false;
      startBtn.textContent = "Download again";
    } else if (status === "error") {
      stopPoll();
      downloadActive = false;
      startBtn.disabled = false;
      startBtn.textContent = "Retry download";
    } else if (ACTIVE.has(status)) {
      startBtn.disabled = true;
      startBtn.textContent = "Downloading…";
    }
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function pollOnce() {
    try {
      const res = await fetch(`/progress/${fileId}`);
      const data = await res.json();
      applyProgress(data);
      return data;
    } catch (err) {
      setStatus(
        statusEl,
        `Progress poll failed: ${err.message || err}. Retrying…`,
        "warn"
      );
      return null;
    }
  }

  function startPoll() {
    stopPoll();
    pollOnce();
    pollTimer = setInterval(pollOnce, 1000);
  }

  async function startDownload() {
    if (downloadActive) return;
    downloadActive = true;
    startBtn.disabled = true;
    startBtn.textContent = "Downloading…";
    setStatus(statusEl, "Starting swarm download…");
    try {
      const res = await fetch(`/api/download/${fileId}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not start download");
      startPoll();
    } catch (err) {
      downloadActive = false;
      setStatus(statusEl, err.message || String(err), "err");
      startBtn.disabled = false;
      startBtn.textContent = "Start download";
    }
  }

  startBtn.addEventListener("click", () => {
    startDownload();
  });

  // Step 7: hydrate from /progress, then auto-start if not already complete.
  (async () => {
    const snapshot = await pollOnce();
    if (!snapshot) return;
    if (ACTIVE.has(snapshot.status)) {
      downloadActive = true;
      startPoll();
      return;
    }
    if (snapshot.status === "complete" || alreadyComplete) {
      return;
    }
    startDownload();
  })();
  }
})();
