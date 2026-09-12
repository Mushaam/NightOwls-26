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
      if (data.status === "already_have" && data.redirect) {
        window.location.href = data.redirect;
        return;
      }
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

  /* ---- Library / file manager ---- */
  const libraryVerify = $("#library-verify");
  const libraryClear = $("#library-clear-zombies");
  const libraryStatus = $("#library-status");
  const focusRow = document.querySelector(".library-row.is-focus");
  if (focusRow) {
    if (libraryStatus) {
      libraryStatus.hidden = false;
      libraryStatus.classList.add("ok");
    }
    focusRow.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  if (libraryVerify || libraryClear) {
    async function postLibrary(url, okMessage) {
      setStatus(libraryStatus, "Working…");
      if (libraryStatus) libraryStatus.hidden = false;
      try {
        const res = await fetch(url, { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Request failed");
        setStatus(
          libraryStatus,
          okMessage(data),
          data.zombies ? "warn" : "ok"
        );
        // Refresh so zombie styling / buttons match DB.
        window.setTimeout(() => window.location.reload(), 600);
      } catch (err) {
        setStatus(libraryStatus, err.message || String(err), "err");
      }
    }

    if (libraryVerify) {
      libraryVerify.addEventListener("click", () => {
        postLibrary(
          "/api/library/verify",
          (d) =>
            `Verified ${d.checked} file(s): ${d.ok} ok, ${d.missing} missing, ${d.corrupt} corrupt.`
        );
      });
    }
    if (libraryClear) {
      libraryClear.addEventListener("click", () => {
        if (!window.confirm("Remove all missing/corrupt library entries and leftover files?")) {
          return;
        }
        postLibrary(
          "/api/library/clear-zombies",
          (d) => `Cleared ${d.cleared_count || 0} zombie(s). Library re-validated.`
        );
      });
    }

    document.querySelectorAll(".lib-open").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id");
        setStatus(libraryStatus, "Opening with system viewer…");
        if (libraryStatus) libraryStatus.hidden = false;
        try {
          const res = await fetch(`/api/library/${id}/open`, { method: "POST" });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || "Open failed");
          setStatus(libraryStatus, `Opened ${data.path}`, "ok");
        } catch (err) {
          setStatus(libraryStatus, err.message || String(err), "err");
        }
      });
    });

    document.querySelectorAll(".lib-delete").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id");
        const name = btn.getAttribute("data-name") || `#${id}`;
        if (
          !window.confirm(
            `Delete “${name}” from this peer?\n\nRemoves the library record and local files (complete, meta, chunks).`
          )
        ) {
          return;
        }
        btn.disabled = true;
        setStatus(libraryStatus, `Deleting ${name}…`);
        if (libraryStatus) libraryStatus.hidden = false;
        try {
          const res = await fetch(`/api/library/${id}/delete`, { method: "POST" });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || "Delete failed");
          setStatus(libraryStatus, `Deleted “${data.filename || name}”.`, "ok");
          const row = document.getElementById(`lib-${id}`);
          if (row) row.remove();
          window.setTimeout(() => window.location.reload(), 500);
        } catch (err) {
          btn.disabled = false;
          setStatus(libraryStatus, err.message || String(err), "err");
        }
      });
    });
  }
})();
