"""
Serve the visualizer: `python -m visualizer.serve`

Starts a local static server rooted at the repo, opens the page, and lets
it pull the solver's own `.py` files into Pyodide. Nothing is built, copied
or transpiled ahead of time -- the browser runs the same source the tests
run, so the UI cannot drift from the model the way the old JavaScript port
did.

A server is needed (rather than just opening index.html) only because
`file://` blocks the fetches that load the Python source.
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
