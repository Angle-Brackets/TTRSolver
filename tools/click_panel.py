"""Drive the built panel in a browser and click its controls.

The panel had six real bugs fixed behind one that made all of them
invisible: `call` was defined inside App() while `CogRow` is its own
component, so every button in a cog row threw "call is not defined"
before reaching Python. Nothing arrived, so nothing could be debugged,
and each Python-side fix appeared to change nothing.

Screenshots cannot catch that -- they render the page without touching
it. This clicks, stubs `window.pywebview` with a recording proxy, and
reports both page errors and the calls that actually landed.

    python tools/click_panel.py
"""
import functools, http.server, json, pathlib, socketserver, threading
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(r"c:/Users/ankit/OneDrive/Desktop/Appu/Programs/TTRSolver")
OUT = pathlib.Path(r"C:/Users/ankit/AppData/Local/Temp/claude/scratch")
DIST = ROOT / "overlay_ui/dist"
handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                            directory=str(DIST))
srv = socketserver.TCPServer(("127.0.0.1", 0), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/index.html"

MODEL = {
    "in_battle": True, "status": "in battle", "turn": 1,
    "advice": "", "track": None, "gag_level": None,
    "objective": "balanced", "budget": 15, "allow_level_7": True,
    "rows": [{"name": "Sellbot", "level": 11, "health": 1.0,
              "identified": False, "art": None, "department": "sellbot",
              "index": 0, "lured": True,
              "choices": [{"key": "mr_hollywood", "display": "Mr. Hollywood",
                           "likely": True, "current": False},
                          {"key": "the_mingler", "display": "The Mingler",
                           "likely": True, "current": False},
                          {"key": "head_hunter", "display": "Head Hunter",
                           "likely": False, "current": False}]}],
    "problems": ["cog 1: a sellbot level 11, pick it from the dropdown"],
    "evidence": "see: 1 cog plate, gag menu",
    "can_confirm": True, "can_advise": True, "thinking": False,
}

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 430, "height": 340},
                    device_scale_factor=2)
    calls = []
    pg.expose_function("_record", lambda *a: calls.append(a))
    pg.add_init_script("""
        window.pywebview = { api: new Proxy({}, {
            get: (_t, name) => (...args) => window._record(name, args)
        })};
    """)
    pg.on("console", lambda m: print(f"   console[{m.type}] {m.text}"))
    pg.on("pageerror", lambda e: print(f"   pageerror: {e}"))
    pg.goto(URL)
    pg.wait_for_timeout(300)
    pg.evaluate("m => window.pushModel(m)", MODEL)
    pg.wait_for_timeout(300)

    before = pg.evaluate("document.getElementById('panel').scrollHeight")
    pg.get_by_title(re_ := "Unidentified — click to say which cog this is").click()
    pg.wait_for_timeout(300)
    after = pg.evaluate("document.getElementById('panel').scrollHeight")
    print(f"  panel height: {before} -> {after} with the list open")

    print("   buttons in list:",
          pg.eval_on_selector_all("#panel button",
                                  "els => els.map(e => e.textContent.trim())"))
    item = pg.get_by_text("Mr. Hollywood", exact=True)
    box = item.bounding_box()
    print(f"  'Mr. Hollywood' sits at y={box['y']:.0f}, panel is {after} tall"
          f"  -> {'INSIDE' if box['y'] + box['height'] <= after else 'OUTSIDE'}")

    pg.set_viewport_size({"width": 430, "height": int(after)})
    pg.wait_for_timeout(150)
    print("   item tag:", item.evaluate("e => e.tagName"))
    item.click()
    pg.wait_for_timeout(200)
    named = [c for c in calls if c[0] == "name_cog"]
    print(f"  clicking it called: {named if named else 'NOTHING'}")
    pg.screenshot(path=str(OUT / "panel_open.png"))
    b.close()
srv.shutdown()
