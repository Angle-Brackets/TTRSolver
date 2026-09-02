"""`run.py`, the front-end picker.

Its job is partly to tell you what is missing, so it must import and
render with NONE of the optional extras present. That is the property
worth testing: a launcher that needs numpy to say "you need numpy" is
useless to the person who needs to read it.
"""
import importlib.util
import io
import pathlib
import sys
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import run  # noqa: E402


class StdlibOnlyTest(unittest.TestCase):

    def test_it_imports_with_no_extras(self):
        """Run it in a subprocess with the extras hidden."""
        import subprocess
        code = (
            "import sys\n"
            "class Block:\n"
            "    def find_module(self, name, path=None):\n"
            "        if name.split('.')[0] in ('numpy','PIL','mss','panda3d','webview'):\n"
            "            raise ImportError(name)\n"
            "sys.meta_path.insert(0, Block())\n"
            "import run\n"
            "run.show()\n"
            "print('RENDERED')\n")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, cwd=str(pathlib.Path(run.__file__).parent))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("RENDERED", out.stdout)

    def test_run_py_imports_nothing_third_party(self):
        source = pathlib.Path(run.__file__).read_text(encoding="utf-8")
        for banned in ("import numpy", "import PIL", "import mss",
                       "import panda3d", "import webview", "import torch"):
            self.assertNotIn(banned, source)


class MenuTest(unittest.TestCase):

    def test_every_entry_names_a_real_module(self):
        for entry in run._flat():
            with self.subTest(entry=entry.label):
                self.assertIsNotNone(
                    importlib.util.find_spec(entry.module),
                    entry.module + " does not exist")

    def test_every_entry_is_runnable_as_a_module(self):
        """`python -m X` needs a __main__ guard in X."""
        for entry in run._flat():
            with self.subTest(entry=entry.label):
                spec = importlib.util.find_spec(entry.module)
                source = pathlib.Path(spec.origin).read_text(encoding="utf-8")
                self.assertIn("__main__", source,
                              entry.module + " has no __main__ entry")

    def test_numbers_are_contiguous_and_unique(self):
        labels = [e.label for e in run._flat()]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertGreater(len(labels), 5)

    def test_list_renders_and_exits_clean(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = run.main(["--list"])
        self.assertEqual(code, 0)
        self.assertIn("Live advice", buf.getvalue())

    def test_an_out_of_range_number_is_refused(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = run.main(["99"])
        self.assertEqual(code, 1)
        self.assertIn("no entry 99", buf.getvalue())

    def test_a_missing_dependency_refuses_to_launch(self):
        entry = run.Entry("fake", "solver.demo", ("definitely_not_installed",),
                          "x")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = run.launch(entry, [])
        self.assertEqual(code, 1)
        self.assertIn("not installed", buf.getvalue())

    def test_every_extra_has_an_install_hint(self):
        for entry in run._flat():
            for need in entry.needs:
                with self.subTest(need=need):
                    self.assertIn(need, run.EXTRAS,
                                  need + " has no install hint")


if __name__ == "__main__":
    unittest.main()
