/* Runs the surveyclean Python package inside the browser with Pyodide.
   Nothing is uploaded: files are read into this worker's memory only.

   Messages in:  analyse {files|demo} -> clean {level, k, enum} -> preview {rename, labels}
                 -> export {name, fmt, rename, labels}
   Messages out: status, ready {version, formats}, result {step, data}, error {step, text}, fatal */

const PYODIDE_VERSION = "0.27.2";
const INDEX_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
importScripts(INDEX_URL + "pyodide.js");

const GLUE = `
import json, shutil
from pathlib import Path
import pandas as pd
import surveyclean as sc
from surveyclean.advisor import check_export, check_reshape, check_upload
from surveyclean.cli import demo_files
from surveyclean.export import FORMATS, export_file, prepare, variable_table
from surveyclean.pipeline import load_form_checked

STATE = {}

def _err(exc):
    return json.dumps({"error": str(exc)})

def _f(findings):
    return [f.as_dict() for f in findings]

def formats():
    return json.dumps([{"key": f.key, "label": f.label, "ext": f.ext, "available": f.available}
                       for f in FORMATS.values()])

def analyse(spec_json):
    spec = json.loads(spec_json)
    if spec.get("demo"):
        d = demo_files()
        spec = {"data": [str(d["data"])], "form": str(d["form"]), "rules": str(d["rules"])}
    try:
        form = load_form_checked(spec.get("form"))
        s = sc.inspect(spec["data"], form)
    except sc.SurveyCleanError as exc:
        return _err(exc)
    STATE.clear()
    STATE.update(spec=spec, survey=s, form=form)
    disp = lambda n: "submission" if n == s.main else n
    levels = [{"name": s.main, "label": "Submission (one row per submission)", "path": [s.main]}]
    levels += [{"name": r.name, "label": f"{r.name}: long format ({' → '.join(disp(p) for p in s.path_to(r.name))})",
                "path": [disp(p) for p in s.path_to(r.name)]} for r in s.repeats]
    default = s.default_level()
    return json.dumps({"tables": s.describe(), "levels": levels, "default": default, "main": s.main,
                       "notes": s.notes, "upload": _f(check_upload(s, form)),
                       "reshape": _f(check_reshape(s, default, form))})

def level_check(opts_json):
    o = json.loads(opts_json)
    return json.dumps({"reshape": _f(check_reshape(STATE["survey"], o["level"], STATE["form"]))})

def clean(opts_json):
    o = json.loads(opts_json)
    spec = STATE["spec"]
    try:
        res = sc.run(spec["data"], form=spec.get("form"), rules=spec.get("rules"), level=o["level"],
                     outlier_k=float(o.get("k") or 3), enumerator_col=o.get("enum") or None)
    except sc.SurveyCleanError as exc:
        return _err(exc)
    STATE["res"] = res
    return json.dumps({
        "summary": {"received": int(res.raw_shape[0]), "duplicates": int(len(res.duplicates)),
                    "submissions": int(res.submissions), "rows": int(len(res.data)),
                    "variables": int(res.data.shape[1]), "outliers": int(len(res.outliers)),
                    "violations": int(len(res.rule_violations)),
                    "recoded": int(sum(res.recoded_missing.values())),
                    "long": len(res.level_path) > 1, "level": res.level},
        "variables": variable_table(res).to_dict("records"),
        "has_labels": bool(res.form.choices),
        "findings": _f([f for f in res.findings if f.step == "preview"]),
    })

def preview(opts_json):
    o = json.loads(opts_json)
    try:
        df = prepare(STATE["res"], "csv", o.get("rename"), o.get("labels", True), o.get("keep")).data.head(30)
    except sc.SurveyCleanError as exc:
        return _err(exc)
    rows = [[None if pd.isna(v) else str(v) for v in r] for r in df.itertuples(index=False)]
    return json.dumps({"columns": [str(c) for c in df.columns], "rows": rows})

def export_check(opts_json):
    o = json.loads(opts_json)
    return json.dumps({"export": _f(check_export(STATE["res"], o["fmt"], o.get("keep"), o.get("rename")))})

def export(opts_json):
    o = json.loads(opts_json)
    out = Path("/tmp/out")
    shutil.rmtree(out, ignore_errors=True)
    try:
        path, notes = export_file(STATE["res"], out, o.get("name"), o["fmt"], rename=o.get("rename"),
                                  use_labels=o.get("labels", True), keep=o.get("keep"))
    except sc.SurveyCleanError as exc:
        return _err(exc)
    return json.dumps({"file": path.name, "path": str(path), "notes": notes})
`;

let pyodide = null;

function status(text, progress) {
  postMessage({ type: "status", text, progress });
}

async function writePackage() {
  const fresh = { cache: "no-cache" };
  const manifest = await (await fetch("surveyclean/files.json", fresh)).json();
  for (const rel of manifest.files) {
    const buf = new Uint8Array(await (await fetch("surveyclean/" + rel, fresh)).arrayBuffer());
    const full = "/home/pyodide/surveyclean/" + rel;
    pyodide.FS.mkdirTree(full.substring(0, full.lastIndexOf("/")));
    pyodide.FS.writeFile(full, buf);
  }
  return manifest.version;
}

async function init() {
  try {
    status("Loading the Python engine…", 0.1);
    pyodide = await loadPyodide({ indexURL: INDEX_URL });
    status("Loading pandas…", 0.35);
    await pyodide.loadPackage(["pandas", "pyyaml", "micropip"]);
    status("Loading Excel support…", 0.75);
    await pyodide.pyimport("micropip").install("openpyxl");
    status("Loading the cleaner…", 0.9);
    const version = await writePackage();
    pyodide.runPython(GLUE);
    const formats = JSON.parse(pyodide.globals.get("formats")());
    postMessage({ type: "ready", version, formats });
  } catch (err) {
    postMessage({ type: "fatal", text: String((err && err.message) || err) });
  }
}

const ready = init();

function writeInputs(files) {
  pyodide.runPython("import shutil; shutil.rmtree('/tmp/in', ignore_errors=True)");
  const spec = { data: [], form: null, rules: null };
  const put = (slot, file, i) => {
    const dir = `/tmp/in/${slot}${i ?? ""}`;
    pyodide.FS.mkdirTree(dir);
    const path = `${dir}/${file.name.replace(/[\\/]/g, "_")}`;
    pyodide.FS.writeFile(path, new Uint8Array(file.bytes));
    return path;
  };
  files.data.forEach((f, i) => spec.data.push(put("data", f, i)));
  if (files.form) spec.form = put("form", files.form);
  if (files.rules) spec.rules = put("rules", files.rules);
  return spec;
}

function call(fn, arg) {
  return JSON.parse(pyodide.globals.get(fn)(JSON.stringify(arg)));
}

onmessage = async (e) => {
  const msg = e.data;
  await ready;
  try {
    let out;
    if (msg.type === "analyse") {
      out = call("analyse", msg.demo ? { demo: true } : writeInputs(msg.files));
    } else if (["clean", "preview", "level_check", "export_check"].includes(msg.type)) {
      out = call(msg.type, msg.options);
    } else if (msg.type === "export") {
      out = call("export", msg.options);
      if (!out.error) {
        const bytes = pyodide.FS.readFile(out.path);
        postMessage({ type: "result", step: "export", data: { ...out, bytes: bytes.buffer } }, [bytes.buffer]);
        return;
      }
    } else {
      return;
    }
    if (out.error) postMessage({ type: "error", step: msg.type, text: out.error });
    else postMessage({ type: "result", step: msg.type, data: out });
  } catch (err) {
    // Python tracebacks are long: show the last line, keep the rest for the console.
    const text = String((err && err.message) || err);
    console.error(text);
    const lines = text.trim().split("\n");
    postMessage({ type: "error", step: msg.type, text: lines[lines.length - 1] });
  }
};
