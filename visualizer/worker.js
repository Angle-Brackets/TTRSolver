/*
 * The solver, off the main thread.
 *
 * Pyodide is single-threaded and its calls are synchronous, so running it
 * in the page means every search freezes the UI for as long as it takes --
 * about a second for a depth-2 root expansion, ten for depth 3. Dragging a
 * slider fires one of those per pixel, which is what made the settings
 * unusable rather than merely slow.
 *
 * Here it runs in a worker instead. The page posts {id, fn, payload} and
 * gets {id, result} back whenever it is ready; nothing it does can block
 * rendering. The page is then free to supersede requests it no longer
 * cares about, which is what makes a slider feel immediate: only the last
 * position it settles on has to matter.
 */
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

let bridge = null;

async function boot() {
  post({type: "status", text: "Downloading Python runtime…"});
  const pyodide = await loadPyodide();

  post({type: "status", text: "Loading solver source…"});
  const manifest = await (await fetch("/api/manifest")).json();
  for (const rel of manifest.files) {
    const src = await (await fetch("/" + rel)).text();
    const full = "/app/" + rel;
    pyodide.FS.mkdirTree(full.slice(0, full.lastIndexOf("/")));
    pyodide.FS.writeFile(full, src);
  }

  post({type: "status", text: "Importing solver…"});
  pyodide.runPython(`
import sys
for p in ("/app", "/app/visualizer"):
    if p not in sys.path:
        sys.path.insert(0, p)
import bridge
`);
  bridge = pyodide.pyimport("bridge");
  post({type: "ready", catalogue: bridge.api_catalogue()});
}

function post(message) {
  self.postMessage(message);
}

self.onmessage = (event) => {
  const {id, fn, payload} = event.data;
  if (!bridge) {
    post({type: "result", id, error: "solver not ready"});
    return;
  }
  try {
    post({type: "result", id, result: bridge[fn](JSON.stringify(payload))});
  } catch (err) {
    post({type: "result", id, error: String(err)});
  }
};

boot().catch(err => post({type: "fatal", error: String(err)}));
