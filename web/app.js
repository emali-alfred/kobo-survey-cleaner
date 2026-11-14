"use strict";

const $ = (id) => document.getElementById(id);
const chosen = { data: null, form: null, rules: null };
const urls = [];
let engineReady = false;
let busy = false;

// ---- Engine (Python in a background worker) --------------------------------
const worker = new Worker("worker.js");

function setStatus(text, { progress, state } = {}) {
  $("status-text").textContent = text;
  const box = $("status");
  box.classList.toggle("error", state === "error");
  box.classList.toggle("done", state === "done");
  if (progress != null) $("bar").style.width = Math.round(progress * 100) + "%";
}

function refreshButton() {
  $("run").disabled = !engineReady || busy || !chosen.data;
}

worker.onmessage = (e) => {
  const m = e.data;
  if (m.type === "status") {
    setStatus(m.text, { progress: m.progress });
  } else if (m.type === "ready") {
    engineReady = true;
    $("version").textContent = "v" + m.version;
    $("first-time").hidden = true;
    setStatus(chosen.data ? "Ready." : "Ready. Choose a data export, or try the demo survey.", { state: "done" });
    refreshButton();
  } else if (m.type === "fatal") {
    setStatus("Could not start the engine: " + m.text + ". Check your internet connection and reload.",
              { state: "error" });
  } else if (m.type === "error") {
    busy = false;
    setStatus(m.text, { state: "error" });
    refreshButton();
  } else if (m.type === "result") {
    busy = false;
    showResults(m);
    setStatus("Done. Your results are below.", { state: "done" });
    refreshButton();
  }
};

// ---- File pickers -------------------------------------------------------------
for (const drop of document.querySelectorAll(".drop")) {
  const slot = drop.dataset.slot;
  const input = drop.querySelector("input");
  const label = drop.querySelector(".drop-file");
  const original = label.textContent;
  const take = (file) => {
    chosen[slot] = file || null;
    drop.classList.toggle("has", !!file);
    label.textContent = file ? file.name : original;
    if (slot === "data" && engineReady && !busy) setStatus("Ready.", { state: "done" });
    refreshButton();
  };
  input.addEventListener("change", () => take(input.files[0]));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    if (e.dataTransfer.files[0]) take(e.dataTransfer.files[0]);
  });
}

async function readFile(file) {
  return file ? { name: file.name, bytes: await file.arrayBuffer() } : null;
}

function options() {
  return { title: $("title").value.trim(), enumerator: $("enum").value.trim(), k: $("k").value };
}

function start(demo) {
  busy = true;
  refreshButton();
  $("results").hidden = true;
  setStatus(engineReady ? "Cleaning…" : "Cleaning as soon as the engine is ready…", { progress: 0.5 });
}

$("run").addEventListener("click", async () => {
  if (!chosen.data) return;
  start(false);
  const files = {};
  const transfer = [];
  for (const slot of Object.keys(chosen)) {
    const f = await readFile(chosen[slot]);
    if (f) { files[slot] = f; transfer.push(f.bytes); }
  }
  worker.postMessage({ type: "run", files, options: options() }, transfer);
});

$("demo").addEventListener("click", () => {
  if (busy) return;
  if ($("title").value === "Data quality report") {
    $("title").value = "Livestock household survey: data quality report (synthetic demo)";
  }
  start(true);
  worker.postMessage({ type: "run", demo: true, options: options() });
});

// ---- Results -----------------------------------------------------------------
const TYPES = {
  ".csv": "text/csv", ".md": "text/markdown", ".html": "text/html", ".zip": "application/zip",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};
const LABELS = {
  "surveyclean_results.zip": "Download everything (.zip)",
  "clean_data.xlsx": "Clean data (Excel)",
  "clean_data.csv": "Clean data (CSV)",
  "data_quality_report.html": "Report (HTML)",
  "data_quality_report.md": "Report (Markdown)",
  "rule_violations.csv": "Rule violations",
  "outliers.csv": "Outliers",
  "enumerator_summary.csv": "Enumerator summary",
};

function stat(label, value, cls = "") {
  const d = document.createElement("div");
  d.className = "stat " + cls;
  const b = document.createElement("b");
  b.textContent = value.toLocaleString();
  const s = document.createElement("span");
  s.textContent = label;
  d.append(b, s);
  return d;
}

function showResults(m) {
  urls.splice(0).forEach((u) => URL.revokeObjectURL(u));
  const s = m.summary;
  const flagged = (n) => (n ? "flag" : "ok");
  $("stats").replaceChildren(
    stat("Records after cleaning", s.records_out),
    stat("Duplicates removed", s.duplicates, flagged(s.duplicates)),
    stat("Rule violations", s.violations, flagged(s.violations)),
    stat("Possible outliers", s.outliers, flagged(s.outliers)),
    stat("Missing codes recoded", s.recoded),
    stat("Unreadable values", s.unreadable, flagged(s.unreadable)),
  );
  $("warnings").replaceChildren(...m.warnings.map((w) => {
    const d = document.createElement("div");
    d.className = "warn";
    d.textContent = w;
    return d;
  }));

  const order = Object.keys(LABELS).filter((n) => n in m.files);
  $("downloads").replaceChildren(...order.map((name) => {
    const ext = name.slice(name.lastIndexOf("."));
    const url = URL.createObjectURL(new Blob([m.files[name]], { type: TYPES[ext] || "application/octet-stream" }));
    urls.push(url);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.textContent = LABELS[name];
    if (name.endsWith(".zip")) a.className = "main";
    return a;
  }));

  const html = new TextDecoder().decode(m.files["data_quality_report.html"]);
  const frame = $("report");
  frame.onload = () => {
    try {
      frame.style.height = frame.contentDocument.documentElement.scrollHeight + 4 + "px";
    } catch { /* keep the default height */ }
  };
  frame.srcdoc = html;
  $("results").hidden = false;
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---- Offline support -------------------------------------------------------------
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => { /* works without it, just not offline */ });
  });
}
