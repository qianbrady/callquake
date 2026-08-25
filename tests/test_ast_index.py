"""AST-index edge cases: nesting, decorators, dynamic calls, junk dirs."""

from __future__ import annotations

import shutil
import unittest

from callquake.ast_index import scan_repository

from _harness import SAMPLE_FILES, fresh_dir, line_of, write_tree


class AstIndexTest(unittest.TestCase):
    def setUp(self):
        self.root = fresh_dir()
        self.addCleanup(shutil.rmtree, self.root, True)

    def scan(self, extra_files=None):
        files = dict(SAMPLE_FILES)
        if extra_files:
            files.update(extra_files)
        write_tree(self.root, files)
        return scan_repository(self.root)

    def test_simple_call_chain_with_lines(self):
        idx = self.scan()
        util_text = SAMPLE_FILES["pkg/util.py"]
        main_text = SAMPLE_FILES["app/main.py"]

        defs = idx.definitions_of("helper")
        self.assertEqual(
            [(d.file, d.line) for d in defs],
            [("pkg/util.py", line_of(util_text, "def helper"))],
        )

        sites = {(c.file, c.line) for c in idx.callsites_of("helper")}
        self.assertIn(("app/main.py", line_of(main_text, "return helper(21)")), sites)
        self.assertIn(("pkg/util.py", line_of(util_text, "return helper(1)")), sites)
        self.assertEqual(len(sites), 2)

    def test_method_definition_and_self_attribute_call(self):
        idx = self.scan()
        util_text = SAMPLE_FILES["pkg/util.py"]

        defs = idx.definitions_of("run")
        self.assertEqual([d.qualname for d in defs], ["Widget.run"])

        run_sites = [(c.file, c.line, c.dotted) for c in idx.callsites_of("run")]
        self.assertIn(("pkg/util.py", line_of(util_text, "return self.run()"), "self.run"), run_sites)

    def test_nested_class_method_qualname(self):
        idx = self.scan(
            {
                "pkg/nested.py": (
                    "class Outer:\n"
                    "    class Inner:\n"
                    "        def deep(self):\n"
                    "            return 1\n"
                )
            }
        )
        defs = idx.definitions_of("deep")
        self.assertEqual(len(defs), 1)
        self.assertEqual(defs[0].qualname, "Outer.Inner.deep")
        self.assertEqual(defs[0].file, "pkg/nested.py")

    def test_decorated_function_indexed_and_decorator_call_recorded(self):
        deco_text = (
            "import functools\n"
            "\n"
            "\n"
            "@functools.lru_cache(maxsize=128)\n"
            "def cached(x):\n"
            "    return x\n"
            "\n"
            "\n"
            "@staticmethod\n"
            "def bare():\n"  # noqa: attribute-style decorator, not a Call
            "    return 0\n"
        )
        idx = self.scan({"pkg/deco.py": deco_text})
        defs = idx.definitions_of("cached")
        self.assertEqual(len(defs), 1)
        self.assertEqual(defs[0].kind, "def")

        deco_sites = [(c.dotted, c.line) for c in idx.callsites_of("lru_cache")]
        expected_line = line_of(deco_text, "@functools.lru_cache")
        self.assertIn(("functools.lru_cache", expected_line), deco_sites)

    def test_dynamic_getattr_call_invisible(self):
        idx = self.scan()
        main_text = SAMPLE_FILES["app/main.py"]
        dyn_line = line_of(main_text, "getattr")

        main_sites = [c for c in idx.callsites_of("main")]
        self.assertFalse(
            any(c.file == "app/main.py" and c.line == dyn_line for c in main_sites),
            "getattr-based dynamic call must stay invisible",
        )

    def test_async_def_and_await_counted(self):
        async_text = (
            "async def fetch(url):\n"
            "    return url\n"
            "\n"
            "\n"
            "async def boss():\n"
            "    return await fetch('x')\n"
        )
        idx = self.scan({"pkg/asyncio_demo.py": async_text})
        defs = idx.definitions_of("fetch")
        self.assertEqual([d.kind for d in defs], ["async"])

        sites = {(c.file, c.line) for c in idx.callsites_of("fetch")}
        self.assertEqual(
            sites, {("pkg/asyncio_demo.py", line_of(async_text, "await fetch"))}
        )

    def test_syntax_error_file_skipped_rest_still_scanned(self):
        idx = self.scan({"pkg/broken.py": "def oops(:\n"})
        self.assertEqual(list(idx.files_skipped), ["pkg/broken.py"])
        self.assertEqual(idx.files_scanned, 3)
        self.assertTrue(idx.definitions_of("helper"))

    def test_junk_dirs_pruned(self):
        idx = self.scan(
            {
                "__pycache__/junk.py": "def hidden(): pass\n",
                "node_modules/junk.py": "def hidden(): pass\n",
                ".git/hooks/junk.py": "def hidden(): pass\n",
                "build/junk.py": "def hidden(): pass\n",
            }
        )
        self.assertEqual(idx.files_scanned, 2)
        self.assertFalse(any(c.file.startswith("__pycache__") for c in idx.callsites))

    def test_relative_posix_paths_and_repeatable_scan(self):
        first = self.scan()
        second = scan_repository(self.root)
        self.assertEqual(first.definitions, second.definitions)
        self.assertEqual(first.callsites, second.callsites)
        for record in [*first.definitions, *first.callsites]:
            self.assertNotIn("\\", record.file)


if __name__ == "__main__":
    unittest.main()
