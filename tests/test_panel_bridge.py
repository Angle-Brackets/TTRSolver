"""The JS call sites must match the Python Api they call.

Two bugs shipped through this gap in one session: `main()` importing a
module that does not exist, and the bridge passing an argument to
zero-argument methods (`Api.ask_now() takes 1 positional argument but 2
were given`). The Api is tested directly and the page is tested by
screenshot; nothing crossed the boundary between them.
"""
import inspect
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
APP = ROOT / "overlay_ui" / "src" / "App.jsx"


class TestPanelBridge(unittest.TestCase):

    def _api(self):
        from solver.live import panel
        return {name: len(inspect.signature(fn).parameters) - 1
                for name, fn in inspect.getmembers(panel.Api,
                                                   inspect.isfunction)
                if not name.startswith("_")}

    def test_main_imports(self):
        """`python -m solver.live.panel --help` must not die on import."""
        from solver.live import panel
        with self.assertRaises(SystemExit):
            panel.main(["--help"])

    def test_every_call_site_exists_with_the_right_arity(self):
        source = APP.read_text(encoding="utf-8")
        api = self._api()
        # call('name'), call('name', a), call('name', a, b) -- count the
        # top-level commas in the argument list rather than looking for
        # one, since `name_cog` takes two.
        for match in re.finditer(r"call\(\s*'([a-z_0-9]+)'([^)]*)\)", source):
            name, rest = match.group(1), match.group(2)
            self.assertIn(name, api, f"App.jsx calls Api.{name}, which "
                                     f"does not exist")
            depth, given = 0, 0
            for ch in rest:
                if ch in "([{":
                    depth += 1
                elif ch in ")]}":
                    depth -= 1
                elif ch == "," and depth == 0:
                    given += 1
            self.assertEqual(given, api[name],
                             f"App.jsx calls Api.{name} with {given} "
                             f"argument(s), but it takes {api[name]}")

    def test_model_json_covers_what_the_page_reads(self):
        """Every model field the page destructures must be posted."""
        import json
        from solver.live import overlay, panel
        posted = set(json.loads(panel.model_json(overlay.Model())))
        source = APP.read_text(encoding="utf-8")
        for field in re.findall(r"model\.([a-z_0-9]+)", source):
            self.assertIn(field, posted,
                          f"App.jsx reads model.{field}, which "
                          f"model_json does not send")


if __name__ == "__main__":
    unittest.main()
