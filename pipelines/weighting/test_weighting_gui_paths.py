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


class SearchableComboboxTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk

        try:
            self.root = tk.Tk()
        except tk.TclError as exc:  # no display
            self.skipTest(f"Tk unavailable: {exc}")
        self.root.withdraw()
        self.picked = []

    def tearDown(self):
        self.root.destroy()

    def _combo(self, **kw):
        import tkinter as tk

        var = tk.StringVar(value="")
        combo = gui.SearchableCombobox(self.root, textvariable=var, **kw)
        combo.set_values(["sex", "region", "age_group", "AGE", "3880_WEIGHT", "2026GeneralWeight"])
        combo.bind("<<ComboboxSelected>>", lambda _e: self.picked.append(var.get()), add="+")
        return combo, var

    def _type(self, combo, text):
        combo.set(text)
        combo._narrow(type("E", (), {"keysym": "a"})())

    def test_typing_narrows_the_list_with_prefix_matches_first(self):
        combo, _var = self._combo()
        self._type(combo, "age")
        self.assertEqual(list(combo["values"]), ["age_group", "AGE"])
        self._type(combo, "weight")
        self.assertEqual(list(combo["values"]), ["3880_WEIGHT", "2026GeneralWeight"])

    def test_return_picks_the_first_match_and_fires_selected(self):
        combo, var = self._combo()
        self._type(combo, "reg")
        combo._commit(first_match=True)
        self.assertEqual(var.get(), "region")
        self.assertEqual(self.picked, ["region"])
        self.assertEqual(len(combo["values"]), 6)  # full list back

    def test_leaving_keeps_a_full_name_in_its_own_case_or_restores_the_last_choice(self):
        combo, var = self._combo()
        self._type(combo, "age")  # exact name, other case
        combo._commit(first_match=False)
        self.assertEqual(var.get(), "AGE")
        self._type(combo, "zzz")
        combo._commit(first_match=False)
        self.assertEqual(var.get(), "AGE")

    def test_weight_box_keeps_a_new_name(self):
        combo, var = self._combo(allow_new=True, allow_blank=False)
        self._type(combo, "3887_WEIGHT")
        combo._commit(first_match=True)
        self.assertEqual(var.get(), "3887_WEIGHT")


class RemainingTests(unittest.TestCase):
    def test_remaining_says_what_is_left_or_over(self):
        self.assertEqual(gui._remaining(100.0)[0], "100% allocated")
        self.assertEqual(gui._remaining(99.996)[0], "100% allocated")
        self.assertEqual(gui._remaining(95.5), ("Remaining: 4.50% to reach 100%", gui.REMAINING_SHORT))
        self.assertEqual(gui._remaining(102.25), ("Over by 2.25% (above 100%)", gui.REMAINING_OVER))


if __name__ == "__main__":
    unittest.main()
