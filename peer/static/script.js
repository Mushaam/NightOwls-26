(() => {
  const $ = (sel, root = document) => root.querySelector(sel);

  function setStatus(el, message, kind) {
    if (!el) return;
    el.textContent = message;
    el.classList.remove("ok", "err");
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
  const panel = document.querySelector("[data-file-id]");
  const startBtn = $("#start-download");
  if (!panel || !startBtn) return;

  const fileId = panel.getAttribute("data-file-id");
  const bar = $("#progress-bar");
  const percentEl = $("#progress-percent");
  const textEl = $("#progress-text");
  const statusEl = $("#download-status");
  const peerCountEl = $("#peer-count");
  let pollTimer = null;

  const savePathEl = $("#save-path");
  const saveBox = $("#save-box");
  const expectedPath = panel.getAttribute("data-expected-path") || "";

  function showSavePath(path) {
    if (!savePathEl || !path) return;
    savePathEl.textContent = path;
    if (saveBox) saveBox.classList.add("ready");
  }

  function applyProgress(data) {
    const pct = Number(data.percent || 0);
    if (bar) bar.style.width = `${pct}%`;
    if (percentEl) percentEl.textContent = `${pct}%`;
    if (textEl) {
      textEl.textContent = `${data.chunks_have || 0}/${data.chunks_total || "?"} chunks · ${data.status || ""}`;
    }
    if (peerCountEl && data.peers_known != null) {
      peerCountEl.textContent = String(data.peers_known);
    }
    if (data.path) {
      showSavePath(data.path);
    }
    if (data.status === "complete") {
      const saved = data.path || expectedPath || "local store";
      showSavePath(saved);
      setStatus(statusEl, `Complete — file saved to the path above.`, "ok");
      stopPoll();
      startBtn.disabled = false;
      startBtn.textContent = "Download again";
    } else if (data.status === "error") {
      setStatus(statusEl, data.error || "Download failed", "err");
      stopPoll();
      startBtn.disabled = false;
    } else {
      setStatus(
        statusEl,
        `${pct}% complete, fetching from ${data.peers_known ?? "?"} peers`,
        null
      );
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
    } catch (err) {
      setStatus(statusEl, `Progress poll failed: ${err.message || err}`, "err");
    }
  }

  function startPoll() {
    stopPoll();
    pollOnce();
    // Step 7 will keep this 1s polling; present now so the download UI works.
    pollTimer = setInterval(pollOnce, 1000);
  }

  startBtn.addEventListener("click", async () => {
    startBtn.disabled = true;
    startBtn.textContent = "Downloading…";
    setStatus(statusEl, "Starting swarm download…");
    try {
      const res = await fetch(`/api/download/${fileId}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not start download");
      startPoll();
    } catch (err) {
      setStatus(statusEl, err.message || String(err), "err");
      startBtn.disabled = false;
      startBtn.textContent = "Start download";
    }
  });
})();
