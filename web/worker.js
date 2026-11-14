/* Runs the surveyclean Python package inside the browser with Pyodide.
   Nothing is uploaded: files are read into this worker's memory only. */

const PYODIDE_VERSION = "0.27.2";
const INDEX_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
importScripts(INDEX_URL + "pyodide.js");

const GLUE = `
import io, json, shutil, zipfile
from pathlib import Path
from surveyclean import run, write_outputs, SurveyCleanError
from surveyclean.cli import demo_files

OUT = Path("/tmp/out")

def demo_paths():
    return json.dumps({k: str(v) for k, v in demo_files().items()})

def do_run(opts_json):
    o = json.loads(opts_json)
    shutil.rmtree(OUT, ignore_errors=True)
    try:
        res = run(o["data"], form=o.get("form"), rules=o.get("rules"),
                  outlier_k=float(o.get("k") or 3), enumerator_col=o.get("enum") or None)
        paths = write_outputs(res, OUT, o.get("title") or "Data quality report")
    except SurveyCleanError as exc:
        return json.dumps({"error": str(exc)})
    zpath = OUT / "surveyclean_results.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths.values():
            z.write(p, p.name)
    summary = {
        "records_in": int(res.raw_shape[0]), "records_out": int(len(res.data)),
        "duplicates": int(len(res.duplicates)), "violations": int(len(res.rule_violations)),
        "outliers": int(len(res.outliers)), "recoded": int(sum(res.recoded_missing.values())),
        "unreadable": int(sum(res.type_failures.values())),
        "enumerators": int(len(res.enumerators)) if res.enumerator_col else 0,
    }
    files = [p.name for p in paths.values()] + [zpath.name]
    return json.dumps({"summary": summary, "warnings": res.warnings, "files": files})
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
    status("Loading pandas and Excel support…", 0.35);
    await pyodide.loadPackage(["pandas", "pyyaml", "micropip"]);
    status("Loading Excel support…", 0.75);
    const micropip = pyodide.pyimport("micropip");
    await micropip.install("openpyxl");
    status("Loading the cleaner…", 0.9);
    const version = await writePackage();
    pyodide.runPython(GLUE);
    postMessage({ type: "ready", version });
  } catch (err) {
    postMessage({ type: "fatal", text: String(err && err.message || err) });
  }
}

const ready = init();

function writeInput(slot, file) {
  pyodide.FS.mkdirTree("/tmp/in/" + slot);
  const safe = file.name.replace(/[\\/]/g, "_");
  const path = `/tmp/in/${slot}/${safe}`;
  pyodide.FS.writeFile(path, new Uint8Array(file.bytes));
  return path;
}

onmessage = async (e) => {
  const msg = e.data;
  if (msg.type !== "run") return;
  await ready;
  try {
    const opts = { title: msg.options.title, enum: msg.options.enumerator, k: msg.options.k };
    if (msg.demo) {
      Object.assign(opts, JSON.parse(pyodide.globals.get("demo_paths")()));
    } else {
      pyodide.runPython("import shutil; shutil.rmtree('/tmp/in', ignore_errors=True)");
      for (const slot of ["data", "form", "rules"]) {
        if (msg.files[slot]) opts[slot] = writeInput(slot, msg.files[slot]);
      }
    }
    const out = JSON.parse(pyodide.globals.get("do_run")(JSON.stringify(opts)));
    if (out.error) {
      postMessage({ type: "error", text: out.error });
      return;
    }
    const files = {};
    const transfer = [];
    for (const name of out.files) {
      const bytes = pyodide.FS.readFile("/tmp/out/" + name);
      files[name] = bytes.buffer;
      transfer.push(bytes.buffer);
    }
    postMessage({ type: "result", summary: out.summary, warnings: out.warnings, files }, transfer);
  } catch (err) {
    // Python tracebacks are long: show the last line, keep the rest for the console.
    const text = String(err && err.message || err);
    console.error(text);
    const lines = text.trim().split("\n");
    postMessage({ type: "error", text: lines[lines.length - 1] });
  }
};
