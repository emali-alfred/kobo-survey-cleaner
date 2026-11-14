"use strict";

const $ = (id) => document.getElementById(id);
const chosen = { data: [], form: null, rules: null };
const NAME_REQUIRED = "Error: Output file name is required before export.";
const ILLEGAL = /[\\/:*?"<>|\x00-\x1f]/g;
const FORMAT_HELP = {
  xlsx: "One workbook with 4 sheets: the clean data (named after your file), Outliers, Rule Violations and the Data Quality Report (including all checks & suggestions).",
  csv: "The clean data only. Missing values are empty cells.",
  rds: "The clean data only, for R. Labelled answers become factors; missing values are NA.",
  RData: "The clean data only, for R. Labelled answers become factors; missing values are NA.",
  dta: "The clean data only, for Stata. Codes keep their value labels and questions their variable labels; missing numbers are '.'.",
  sav: "The clean data only, for SPSS, with value and variable labels.",
  html: "The clean data only, as a table that opens in any web browser.",
};

let engineReady = false;
let busy = false;
let formats = [];
let analysis = null;
let uploadFindings = [];
let variables = [];
let renames = {};
let keep = new Set();
let downloadUrl = null;

// ---- Engine (Python in a background worker) ------------------------------------
const worker = new Worker("worker.js");

function setStatus(text, { progress, state } = {}) {
  $("status-text").textContent = text;
  const box = $("status");
  box.classList.toggle("error", state === "error");
  box.classList.toggle("done", state === "done");
  if (progress != null) $("bar").style.width = Math.round(progress * 100) + "%";
}

function send(type, payload, transfer) {
  busy = true;
  refresh();
  worker.postMessage({ type, ...payload }, transfer || []);
}

worker.onmessage = (e) => {
  const m = e.data;
  if (m.type === "status") return setStatus(m.text, { progress: m.progress });
  if (m.type === "ready") {
    engineReady = true;
    formats = m.formats;
    buildFormats();
    $("version").textContent = "v" + m.version;
    $("first-time").hidden = true;
    setStatus("Ready. Choose your data export, or try the demo survey.", { state: "done" });
    return refresh();
  }
  if (m.type === "fatal") {
    return setStatus("Could not start the engine: " + m.text + ". Check your internet connection and reload.",
                     { state: "error" });
  }
  busy = false;
  if (m.type === "error") {
    setStatus(m.text.startsWith("Error") ? m.text : "Error: " + m.text, { state: "error" });
    if (m.step === "preview") $("rename-error").textContent = m.text;
    return refresh();
  }
  if (m.type === "result") {
    ({ analyse: onAnalysed, level_check: onLevelChecked, clean: onCleaned, preview: onPreview,
       export_check: onExportChecked, export: onExported })[m.step](m.data);
  }
  refresh();
};

// ---- Checks & suggestions ------------------------------------------------------------
function findingHTML(f) {
  return `<div class="finding ${esc(f.severity)}"><b>${esc(f.title)}</b>${f.detail ? " " + esc(f.detail) : ""}` +
    (f.suggestion ? `<span class="tip">${esc(f.suggestion)}</span>` : "") + "</div>";
}

function showFindings(id, groups, emptyText) {
  const box = $(id);
  const all = groups.flatMap((g) => g.items);
  box.querySelector(".flist").innerHTML = all.length
    ? groups.filter((g) => g.items.length).map((g) => (g.heading ? `<h4>${esc(g.heading)}</h4>` : "") +
        g.items.map(findingHTML).join("")).join("")
    : `<div class="finding ok">${esc(emptyText)}</div>`;
  // One compact line: counts per severity; details open on click.
  const icon = { problem: "✖", warning: "▲", note: "ℹ" };
  const chips = ["problem", "warning", "note"].map((sev) => {
    const n = all.filter((f) => f.severity === sev).length;
    return n ? `<span class="chip ${sev}">${icon[sev]} ${n} ${sev}${n === 1 ? "" : "s"}</span>` : "";
  }).join("");
  box.querySelector(".chips").innerHTML = chips || '<span class="chip ok">✔ All good</span>';
  box.hidden = false;
}

function setStepCount(step, findings) {
  const li = document.querySelector(`.stepper [data-step="${step}"]`);
  li.querySelector(".count")?.remove();
  const n = findings.filter((f) => f.severity !== "note").length;
  if (n) li.insertAdjacentHTML("beforeend", `<span class="count" title="${n} to check">(${n}⚠)</span>`);
}

// ---- Steps ---------------------------------------------------------------------------
function show(step) {
  for (let i = 1; i <= 4; i++) {
    $("step" + i).hidden = i > step;
    const li = document.querySelector(`.stepper [data-step="${i}"]`);
    li.classList.toggle("on", i === step);
    li.classList.toggle("past", i < step);
  }
  $("step" + step).scrollIntoView({ behavior: "smooth", block: "start" });
}

function keepList() {
  return document.querySelector('input[name="keepmode"]:checked').value === "all"
    ? null : variables.map((v) => v.original).filter((c) => keep.has(c));
}

function refresh() {
  $("next1").disabled = !engineReady || busy || chosen.data.length === 0;
  $("next2").disabled = busy;
  $("next3").disabled = busy;
  const nameOk = cleanName($("name").value) !== "";
  $("name-error").textContent = nameOk ? "" : NAME_REQUIRED;
  const k = keepList();
  $("export").disabled = busy || !nameOk || !selectedFormat() || (k !== null && k.length === 0);
  updateTarget();
}

document.querySelectorAll("[data-back]").forEach((b) => b.addEventListener("click", () => show(+b.dataset.back)));

// 1 Upload ------------------------------------------------------------------------------
for (const drop of document.querySelectorAll(".drop")) {
  const slot = drop.dataset.slot;
  const input = drop.querySelector("input");
  const label = drop.querySelector(".drop-file");
  const original = label.textContent;
  const take = (files) => {
    const list = [...files];
    chosen[slot] = slot === "data" ? list : list[0] || null;
    drop.classList.toggle("has", list.length > 0);
    label.textContent = list.length ? list.map((f) => f.name).join(", ") : original;
    refresh();
  };
  input.addEventListener("change", () => take(input.files));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    if (e.dataTransfer.files.length) take(e.dataTransfer.files);
  });
}

async function read(file) {
  return { name: file.name, bytes: await file.arrayBuffer() };
}

$("next1").addEventListener("click", async () => {
  const files = { data: await Promise.all(chosen.data.map(read)) };
  if (chosen.form) files.form = await read(chosen.form);
  if (chosen.rules) files.rules = await read(chosen.rules);
  const transfer = [...files.data.map((f) => f.bytes), files.form?.bytes, files.rules?.bytes].filter(Boolean);
  setStatus("Reading and checking the export…", { progress: 0.5 });
  send("analyse", { files }, transfer);
});

$("demo").addEventListener("click", () => {
  if (!engineReady || busy) return;
  setStatus("Loading the demo survey (synthetic households with a household-member repeat group)…", { progress: 0.5 });
  send("analyse", { demo: true });
});

// 2 Reshape -----------------------------------------------------------------------------
function table(el, headers, rows) {
  const thead = `<thead><tr>${headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>`;
  const body = rows.map((r) => `<tr>${r.map((v) => `<td>${v == null ? "" : esc(String(v))}</td>`).join("")}</tr>`).join("");
  el.innerHTML = thead + `<tbody>${body}</tbody>`;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function onAnalysed(a) {
  analysis = a;
  uploadFindings = a.upload;
  showFindings("f1", [{ items: a.upload }], "The files look fine.");
  setStepCount(1, a.upload);
  table($("tables"), ["Table", "Linked to", "Rows", "Columns"], a.tables.map((t) => [
    t.name, t.parent ? `repeat group of ${t.parent === a.main ? "the submission" : t.parent}` : "main table (submissions)",
    t.rows.toLocaleString(), t.columns]));
  $("level").innerHTML = a.levels.map((l) => `<option value="${esc(l.name)}">${esc(l.label)}</option>`).join("");
  $("level").value = a.default;
  explainLevel();
  onLevelChecked({ reshape: a.reshape });
  const n = a.tables.length - 1;
  const serious = a.upload.filter((f) => f.severity !== "note").length;
  setStatus([`Found the main table and ${n} repeat group${n === 1 ? "" : "s"}.`,
             serious ? `${serious} thing${serious === 1 ? "" : "s"} to check (see Checks & suggestions).` : "",
             "Choose the row level."].filter(Boolean).join(" "), { state: "done" });
  show(2);
}

function explainLevel() {
  const l = analysis.levels.find((x) => x.name === $("level").value);
  $("level-help").textContent = l.path.length === 1
    ? "One row per submission." + (analysis.levels.length > 1 ? " Each repeat group is summarised as a count column (n_<group>)." : "")
    : `Long format: one row per '${l.name}' record, with the answers of the ${l.path.slice(0, -1).join(" and ")} repeated on each of its rows. Submissions without any record are kept, with those columns empty.`;
}

$("level").addEventListener("change", () => {
  explainLevel();
  send("level_check", { options: { level: $("level").value } });
});

function onLevelChecked(r) {
  showFindings("f2", [
    { heading: "Your files (step 1)", items: uploadFindings.filter((f) => f.severity !== "note") },
    { heading: "This row level", items: r.reshape },
  ], "No problems found for this row level.");
  setStepCount(2, r.reshape);
}

$("next2").addEventListener("click", () => {
  setStatus("Cleaning and checking…", { progress: 0.5 });
  send("clean", { options: { level: $("level").value, k: $("k").value, enum: $("enum").value.trim() } });
});

// 3 Preview, choose & rename --------------------------------------------------------------
function stat(label, value, cls = "") {
  return `<div class="stat ${cls}"><b>${Number(value).toLocaleString()}</b><span>${esc(label)}</span></div>`;
}

function onCleaned(c) {
  const s = c.summary;
  const flag = (n) => (n ? "flag" : "ok");
  $("stats").innerHTML = [
    stat("Submissions kept", s.submissions),
    stat("Duplicates removed", s.duplicates, flag(s.duplicates)),
    stat(s.long ? `Rows (one per ${s.level})` : "Rows", s.rows),
    stat("Rule violations", s.violations, flag(s.violations)),
    stat("Possible outliers", s.outliers, flag(s.outliers)),
    stat("Missing codes recoded", s.recoded),
  ].join("");
  $("warnings").innerHTML = "";
  showFindings("f3", [{ items: c.findings }], "The cleaned data look fine.");
  setStepCount(3, c.findings);
  $("labels").checked = c.has_labels;
  $("labels").disabled = !c.has_labels;
  variables = c.variables;
  renames = {};
  keep = new Set(variables.map((v) => v.original));
  document.querySelector('input[name="keepmode"][value="all"]').checked = true;
  $("var-search").value = "";
  buildRenameTable();
  requestPreview();
  setStatus("Check the preview and the suggestions. Choosing and renaming variables is optional.", { state: "done" });
  show(3);
}

function buildRenameTable() {
  const all = keepList() === null;
  const needle = $("var-search").value.trim().toLowerCase();
  const head = "<thead><tr><th>Keep</th><th>Original Variable Name</th><th>Label / Question Text</th><th>New Variable Name</th></tr></thead>";
  const body = variables.map((v, i) => {
    if (needle && !v.original.toLowerCase().includes(needle) && !(v.label || "").toLowerCase().includes(needle)) return "";
    const on = all || keep.has(v.original);
    return `<tr class="${on ? "" : "off"}"><td><input type="checkbox" data-k="${i}" ${on ? "checked" : ""} aria-label="Keep ${esc(v.original)}"></td>
      <td><code>${esc(v.original)}</code></td><td>${esc(v.label || "")}</td>
      <td><input type="text" data-i="${i}" value="${esc(renames[v.original] || v.original)}" aria-label="New name for ${esc(v.original)}"></td></tr>`;
  }).join("");
  $("rename").innerHTML = head + `<tbody>${body}</tbody>`;
  const n = all ? variables.length : variables.filter((v) => keep.has(v.original)).length;
  $("keep-count").textContent = `${n} of ${variables.length} selected`;
  $("keep-count").classList.toggle("error", n === 0);
}

function selectionChanged() {
  buildRenameTable();
  requestPreview();
  refresh();
}

function useSelected() {
  document.querySelector('input[name="keepmode"][value="selected"]').checked = true;
}

$("rename").addEventListener("change", (e) => {
  const box = e.target.closest("input[data-k]");
  if (box) {
    if (keepList() === null) { keep = new Set(variables.map((v) => v.original)); useSelected(); }
    const orig = variables[+box.dataset.k].original;
    if (box.checked) keep.add(orig); else keep.delete(orig);
    return selectionChanged();
  }
  const input = e.target.closest("input[data-i]");
  if (!input) return;
  const orig = variables[+input.dataset.i].original;
  const value = input.value.trim();
  const proposal = { ...renames };
  if (!value || value === orig) delete proposal[orig];
  else proposal[orig] = value;
  const names = variables.map((v) => proposal[v.original] || v.original);
  const clash = value && names.filter((n) => n === value).length > 1;
  $("rename-error").textContent = clash ? `'${value}' is already used by another variable.` : "";
  input.classList.toggle("bad", !!clash);
  if (clash) return;
  if (!value) input.value = orig;
  renames = proposal;
  requestPreview();
});

document.querySelectorAll('input[name="keepmode"]').forEach((r) => r.addEventListener("change", () => {
  if (keepList() !== null) $("rename-box").open = true;
  selectionChanged();
}));
$("var-search").addEventListener("input", buildRenameTable);
$("select-all").addEventListener("click", () => {
  useSelected();
  document.querySelectorAll("#rename input[data-k]").forEach((b) => keep.add(variables[+b.dataset.k].original));
  selectionChanged();
});
$("select-none").addEventListener("click", () => {
  if (keepList() === null) keep = new Set(variables.map((v) => v.original));
  useSelected();
  document.querySelectorAll("#rename input[data-k]").forEach((b) => keep.delete(variables[+b.dataset.k].original));
  selectionChanged();
});
$("reset-names").addEventListener("click", () => {
  renames = {};
  $("rename-error").textContent = "";
  buildRenameTable();
  requestPreview();
});
$("labels").addEventListener("change", requestPreview);

function requestPreview() {
  const k = keepList();
  if (k !== null && k.length === 0) {
    $("preview").innerHTML = "";
    $("rename-error").textContent = "Choose at least one variable to export.";
    return;
  }
  $("rename-error").textContent = "";
  send("preview", { options: { rename: renames, labels: $("labels").checked, keep: k } });
}

function onPreview(p) {
  table($("preview"), p.columns, p.rows);
  $("preview-note").textContent = `(first ${p.rows.length} rows)`;
}

$("next3").addEventListener("click", () => {
  show(4);
  $("name").focus();
  checkExport();
});

// 4 Name & Export -------------------------------------------------------------------------
function cleanName(raw) {
  let t = String(raw || "").replace(ILLEGAL, "").trim().replace(/[. ]+$/, "").trim();
  for (const f of formats) {
    if (t.toLowerCase().endsWith(f.ext.toLowerCase())) { t = t.slice(0, -f.ext.length).replace(/[. ]+$/, "").trim(); break; }
  }
  return t;
}

function selectedFormat() {
  const r = document.querySelector('input[name="fmt"]:checked');
  return r ? formats.find((f) => f.key === r.value) : null;
}

function buildFormats() {
  $("formats").innerHTML = formats.map((f, i) => `
    <label class="fmt ${f.available ? "" : "off"}">
      <input type="radio" name="fmt" value="${f.key}" ${f.available ? "" : "disabled"} ${i === 0 ? "checked" : ""}>
      ${esc(f.label)}${f.available ? "" : ' <span class="muted">(Windows app only)</span>'}
    </label>`).join("");
  $("formats").addEventListener("change", () => { refresh(); checkExport(); });
}

function checkExport() {
  const f = selectedFormat();
  if (!f || !variables.length) return;
  send("export_check", { options: { fmt: f.key, keep: keepList(), rename: renames } });
}

function onExportChecked(r) {
  showFindings("f4", [{ items: r.export }], "Ready to export.");
  setStepCount(4, r.export);
}

function updateTarget() {
  const f = selectedFormat();
  $("format-help").textContent = f ? FORMAT_HELP[f.key] : "";
  const base = cleanName($("name").value);
  $("target").textContent = f && base ? `Will download as: ${base}${f.ext}` : "";
}

$("name").addEventListener("input", refresh);

$("export").addEventListener("click", () => {
  const base = cleanName($("name").value);
  if (!base) { $("name-error").textContent = NAME_REQUIRED; refresh(); return; }
  $("name").value = base; // strip the characters file names cannot contain
  setStatus("Writing the file…", { progress: 0.6 });
  send("export", { options: { name: base, fmt: selectedFormat().key, rename: renames,
                              labels: $("labels").checked, keep: keepList() } });
});

function onExported(x) {
  if (downloadUrl) URL.revokeObjectURL(downloadUrl);
  downloadUrl = URL.createObjectURL(new Blob([x.bytes], { type: "application/octet-stream" }));
  const a = document.createElement("a");
  a.href = downloadUrl;
  a.download = x.file;
  a.className = "download";
  a.textContent = `Download ${x.file}`;
  const notes = x.notes.map((n) => `<p class="hint">${esc(n)}</p>`).join("");
  $("done").innerHTML = `<p><strong>Ready: 1 file.</strong> If the download did not start, use the button.</p>`;
  $("done").append(a);
  $("done").insertAdjacentHTML("beforeend", notes);
  $("done").hidden = false;
  a.click();
  setStatus(`Done. ${x.file} is ready.`, { state: "done" });
}

refresh();

// ---- Light / dark / system theme (remembered in this browser) -------------------------
function applyTheme(choice) {
  const root = document.documentElement;
  if (choice === "light" || choice === "dark") root.dataset.theme = choice;
  else delete root.dataset.theme;
  document.querySelectorAll("[data-theme-choice]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.themeChoice === (choice || "system"))));
}
let savedTheme = "system";
try { savedTheme = localStorage.getItem("sc-theme") || "system"; } catch { /* private mode: default */ }
applyTheme(savedTheme);
document.querySelectorAll("[data-theme-choice]").forEach((b) => b.addEventListener("click", () => {
  applyTheme(b.dataset.themeChoice);
  try { localStorage.setItem("sc-theme", b.dataset.themeChoice); } catch { /* not remembered */ }
}));

// ---- Offline support --------------------------------------------------------------------
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => { /* works without it, just not offline */ });
  });
}
