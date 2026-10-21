from __future__ import annotations

import os
import shutil
import time
import unittest
import uuid
from pathlib import Path

import packaged_apps
from packaged_apps import PackagedApp, freshness, source_files


BASE_DIR = Path(__file__).resolve().parent


class PackagedAppsTests(unittest.TestCase):
    def test_wincross_sources_cover_every_bundled_module(self) -> None:
        names = {path.name for path in source_files(packaged_apps.APPS_BY_KEY["wincross"])}

        for expected in (
            "survey_pipeline_gui.py",
            "survey_pipeline.py",
            "surveyConvertJSON.py",
            "wincrossTableCompile.py",
            "wincrossBannerCompile.py",
            "wincrossCoverCompile.py",
            "survey_unformatter.py",
            "survey_tool_cli.py",
            "survey_pipeline_gui.spec",
        ):
            self.assertIn(expected, names)
        self.assertFalse(any(name.startswith("test_") for name in names))
        self.assertNotIn("golden_compare.py", names)

    def test_freshness_follows_imported_sibling_modules(self) -> None:
        folder = BASE_DIR / ".tmp_tests" / "packaged_apps" / uuid.uuid4().hex
        (folder / "dist").mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(folder, ignore_errors=True))
        (folder / "tool.spec").write_text("a = Analysis(\n    ['tool_gui.py'],\n)\n", encoding="utf-8")
        (folder / "tool_gui.py").write_text("import tool_core\n", encoding="utf-8")
        (folder / "tool_core.py").write_text("VALUE = 1\n", encoding="utf-8")
        (folder / "unrelated.py").write_text("VALUE = 2\n", encoding="utf-8")
        app = PackagedApp("tool", "Tool", folder, ("tool.spec",), ("tool.exe",), "build.bat")

        self.assertEqual(freshness(app).status, "missing")

        exe = folder / "dist" / "tool.exe"
        exe.write_bytes(b"exe")
        now = time.time()
        for path in folder.glob("*.*"):
            os.utime(path, (now - 100, now - 100))
        os.utime(exe, (now - 50, now - 50))
        self.assertEqual(freshness(app).status, "fresh")

        os.utime(folder / "unrelated.py", (now, now))
        self.assertEqual(freshness(app).status, "fresh")

        os.utime(folder / "tool_core.py", (now, now))
        state = freshness(app)
        self.assertEqual(state.status, "stale")
        self.assertEqual(state.newest_source, (folder / "tool_core.py").resolve())


if __name__ == "__main__":
    unittest.main()
