"""Tests for the folders shared by apps opened from the Survey Launcher."""

import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import launch_paths  # noqa: E402

TMP_ROOT = THIS_DIR / ".tmp_tests_launch_paths"


class LaunchPathsTests(unittest.TestCase):
    def setUp(self):
        self.folder = TMP_ROOT / uuid.uuid4().hex
        self.project = self.folder / "NPA9999 Project"
        self.data = self.project / "Data"
        self.test_folder = self.project / "Job" / "OG Clean" / "NPA9999pt"
        self.data.mkdir(parents=True)
        self.settings = self.folder / "remembered.json"
        self.addCleanup(shutil.rmtree, self.folder, True)

    def env(self, *, test_run: bool):
        values = {
            "SURVEY_PLATFORM_PROJECT_ROOT": str(self.project),
            "SURVEY_PLATFORM_WORK_DIR": str(self.data),
            "SURVEY_PLATFORM_SURVEY_ID": "NPA9999",
            "SURVEY_PLATFORM_OUTPUT_DIR": str(self.test_folder if test_run else self.data),
            "SURVEY_PLATFORM_TEST_RUN": "1" if test_run else "",
        }
        return mock.patch.dict(os.environ, values)

    def test_output_folder_follows_the_test_run(self):
        with self.env(test_run=False):
            self.assertEqual(launch_paths.output_dir(), self.data.resolve())
            self.assertFalse(launch_paths.is_test_run())
            self.assertEqual(launch_paths.test_run_note(), "")
        with self.env(test_run=True):
            self.assertEqual(launch_paths.output_dir(), self.test_folder.resolve())
            self.assertTrue(self.test_folder.is_dir())  # created when needed
            self.assertIn("NPA9999pt", launch_paths.test_run_note())

    def test_save_dialogs_start_in_the_test_folder_during_a_test_run(self):
        elsewhere = self.folder / "elsewhere"
        elsewhere.mkdir()
        with self.env(test_run=True):
            self.assertEqual(launch_paths.save_dir("app", str(elsewhere / "x.csv"), settings_path=self.settings),
                             str(self.test_folder.resolve()))
        with self.env(test_run=False):
            self.assertEqual(launch_paths.save_dir("app", str(elsewhere / "x.csv"), settings_path=self.settings),
                             str(elsewhere.resolve()))
            self.assertEqual(launch_paths.save_dir("app", settings_path=self.settings), str(self.data.resolve()))

    def test_folders_are_remembered_per_project_and_app(self):
        picked = self.folder / "Sample"
        picked.mkdir()
        with self.env(test_run=False):
            self.assertEqual(launch_paths.input_dir("quota", "sample", settings_path=self.settings), str(self.data.resolve()))
            launch_paths.remember_dir("quota", "sample", picked / "pull.csv", settings_path=self.settings)
            self.assertEqual(launch_paths.input_dir("quota", "sample", settings_path=self.settings), str(picked.resolve()))
            self.assertIsNone(launch_paths.remembered_dir("merge", "sample", settings_path=self.settings))
        other = self.folder / "NPA9998 Project"
        other.mkdir()
        with mock.patch.dict(os.environ, {"SURVEY_PLATFORM_PROJECT_ROOT": str(other), "SURVEY_PLATFORM_WORK_DIR": ""}):
            self.assertIsNone(launch_paths.remembered_dir("quota", "sample", settings_path=self.settings))

    def test_the_current_entry_wins_over_remembered_folders(self):
        current = self.folder / "Current"
        current.mkdir()
        with self.env(test_run=False):
            launch_paths.remember_dir("quota", "sample", self.data / "a.csv", settings_path=self.settings)
            self.assertEqual(launch_paths.input_dir("quota", "sample", str(current / "b.csv"), settings_path=self.settings),
                             str(current.resolve()))

    def test_remembering_never_raises(self):
        launch_paths.remember_dir("app", "slot", "", settings_path=self.settings)
        launch_paths.remember_dir("app", "slot", self.folder / "missing" / "x.csv", settings_path=self.settings)
        self.assertFalse(self.settings.exists())


if __name__ == "__main__":
    unittest.main()
