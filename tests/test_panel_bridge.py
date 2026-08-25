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


def _all_sources() -> str:
    """Every component, not just App.jsx -- the cog picker is its own
    file and holds call sites too."""
    return chr(10).join(f.read_text(encoding="utf-8")
                        for f in sorted(SRC.glob("*.jsx")))
SRC = ROOT / "overlay_ui" / "src"
APP = SRC / "App.jsx"


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
        # Every source file, not just App.jsx -- the cog picker is its
        # own component and its call sites must match too.
        source = _all_sources()
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
        source = _all_sources()
        for field in re.findall(r"model\.([a-z_0-9]+)", source):
            self.assertIn(field, posted,
                          f"App.jsx reads model.{field}, which "
                          f"model_json does not send")


if __name__ == "__main__":
    unittest.main()


class TestNoUndefinedIdentifiers(unittest.TestCase):
    """A handler that throws reaches Python with nothing to show for it.

    `call` was defined inside App() while `CogRow` is a module-level
    component, so every button in a cog row raised "call is not defined"
    on click. The page rendered perfectly and screenshots looked right;
    only clicking revealed it. tools/click_panel.py does that against a
    browser -- this is the cheap static half.
    """

    def test_helpers_used_across_components_are_module_scope(self):
        app = (SRC / "App.jsx").read_text(encoding="utf-8")
        # `call` must not be declared inside the App component, or the
        # other components in this file cannot see it.
        body = app[app.index("export default function App("):]
        self.assertNotIn("const call = ", body,
                         "`call` is scoped to App() but CogRow uses it -- "
                         "every button in a cog row will throw")

    def test_every_component_that_calls_has_it_in_scope(self):
        """Components in their own files must receive it as a prop."""
        for path in sorted(SRC.glob("*.jsx")):
            source = path.read_text(encoding="utf-8")
            if "call(" not in source:
                continue
            declared = ("const call = " in source
                        or "import" in source and path.name == "App.jsx")
            self.assertTrue(declared or "onPick" in source,
                            f"{path.name} uses call() without declaring it "
                            f"or receiving a handler prop")
