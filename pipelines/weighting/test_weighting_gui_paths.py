"""Where the weighting app reads and writes when opened from the Survey Launcher."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import weighting_gui as gui  # noqa: E402


class LaunchPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "Data" / "NPA9999ts.csv"
        self.test_folder = self.tmp / "Job" / "OG Clean" / "NPA9999pt"
        self.data.parent.mkdir(parents=True)

    def _env(self, test_run: bool) -> dict[str, str]:
        return {
            "SURVEY_PLATFORM_WORK_DIR": str(self.data.parent),
            "SURVEY_PLATFORM_PROJECT_ROOT": str(self.tmp),
            "SURVEY_PLATFORM_OUTPUT_DIR": str(self.test_folder if test_run else self.data.parent),
            "SURVEY_PLATFORM_TEST_RUN": "1" if test_run else "",
        }

    def test_setup_sits_beside_the_data_outside_a_test_run(self):
        with mock.patch.dict(os.environ, self._env(test_run=False)):
            self.assertEqual(gui._config_path_for(str(self.data)), self.data.parent / "NPA9999ts_weighting.json")
            self.assertEqual(gui._setup_paths_to_read(str(self.data)), [self.data.parent / "NPA9999ts_weighting.json"])

    def test_test_run_saves_the_setup_in_the_test_folder_but_can_start_from_the_live_one(self):
        with mock.patch.dict(os.environ, self._env(test_run=True)):
            saved = gui._config_path_for(str(self.data))
            self.assertEqual(saved, self.test_folder / "NPA9999ts_weighting.json")
            self.assertTrue(self.test_folder.is_dir())  # created on demand by launch_paths.output_dir
            self.assertEqual(
                gui._setup_paths_to_read(str(self.data)),
                [saved, self.data.parent / "NPA9999ts_weighting.json"],
            )

    def test_save_dialog_starts_in_the_test_folder_during_a_test_run(self):
        with mock.patch.dict(os.environ, self._env(test_run=True)):
            self.assertEqual(gui.launch_paths.save_dir(gui.APP, str(self.data)), str(self.test_folder))

    def test_typed_save_names_get_a_data_extension(self):
        self.assertEqual(gui._with_data_extension(Path("out"), "CSV").name, "out.csv")
        self.assertEqual(gui._with_data_extension(Path("out"), "Excel").name, "out.xlsx")
        self.assertEqual(gui._with_data_extension(Path("out.xlsx"), "CSV").name, "out.xlsx")


if __name__ == "__main__":
    unittest.main()
