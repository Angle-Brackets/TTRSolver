"""
Serve the visualizer: `python -m visualizer.serve`

Starts a local server rooted at the repo, opens the page, and answers the
page's solver calls at `POST /api/call`.

THE SOLVER RUNS HERE, NOT IN THE BROWSER. This process is CPython in the
repo: numpy is installed, `solver/rl/ppo_facility.json` is on disk, and
`bridge` imports directly. That matters for three things the old
Pyodide arrangement could not do:

  * `hybrid.climb` -- the PPO policy, which is the engine the overlay
    panel actually plays with. In the browser it was doubly blocked:
    numpy was never `loadPackage`d, and the manifest globbed `*.py` so
    the 7.7 MB policy export never reached the browser filesystem.
  * Speed. The search is CPU-bound against a seconds budget, so an
    interpreter penalty comes straight off the depth it reaches.
  * First load. Pyodide is ~10 MB before anything works.

The property Pyodide was there for is kept and is in fact stronger: the
page still holds no copy of the battle rules, because every answer comes
from `bridge` calling the same `solver` package the tests import. A JSON
call over HTTP is a shorter path to that than shipping the interpreter.

`/api/manifest` remains for the old page, which mounts the sources into
Pyodide itself. It can go when that page does.
"""
import argparse
import http.server
import json
import pathlib
import socketserver
import threading
import webbrowser

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
# Packages whose .py files get mounted into the browser's filesystem.
SOURCE_ROOTS = ("solver", "visualizer")


def python_manifest():
    """Every .py file the page needs, repo-relative, with `solver/` first so
    the package exists before `bridge` imports it."""
    files = []
    for root in SOURCE_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            files.append(path.relative_to(REPO_ROOT).as_posix())
    return files


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPO_ROOT), **kwargs)

    def do_POST(self):
        """`{"fn": "api_root", "payload": {...}}` -> whatever `bridge`
        returns, which is already a JSON string.

        One endpoint rather than a route per call, so adding a bridge
        function needs no change here. Only names starting `api_` are
        callable: the module is full of helpers that take Python objects
        and would raise confusingly on a JSON payload.
        """
        if self.path.split("?")[0] != "/api/call":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            request = json.loads(self.rfile.read(length) or b"{}")
            name = str(request.get("fn", ""))
            if not name.startswith("api_"):
                raise ValueError(f"{name!r} is not a bridge API function")
            from visualizer import bridge

            fn = getattr(bridge, name, None)
            if fn is None:
                raise ValueError(f"no bridge function {name!r}")
            payload = request.get("payload")
            # `api_catalogue` takes nothing; the rest take a JSON string.
            body = (fn() if payload is None else fn(json.dumps(payload)))
        except Exception as exc:                      # noqa: BLE001
            # REPORTED, NOT RAISED. A 500 with an empty body tells the
            # page nothing, and the useful cases here are ordinary --
            # a loadout over the pouch cap, a [TODO] attack table.
            body = json.dumps({"error": f"{exc.__class__.__name__}: {exc}"})
        raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/manifest":
            body = json.dumps({"files": python_manifest()}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        # The page edits nothing, but stale .py in the browser cache would
        # silently show old game rules -- exactly the drift this replaces.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass    # the default logs every asset; too noisy to be useful


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://localhost:{args.port}/visualizer/index.html"
    with Server(("127.0.0.1", args.port), Handler) as httpd:
        print(f"Serving {REPO_ROOT}")
        print(f"Visualizer: {url}")
        print(f"{len(python_manifest())} Python files exposed to the page.")
        print("Ctrl-C to stop.")
        if not args.no_browser:
            threading.Timer(0.5, webbrowser.open, args=(url,)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
