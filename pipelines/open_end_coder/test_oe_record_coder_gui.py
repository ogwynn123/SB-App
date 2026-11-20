import sys
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import oe_record_coder_core as core  # noqa: E402
import oe_record_coder_gui as gui  # noqa: E402


class RecordCoderGuiHelpersTests(unittest.TestCase):
    def test_launch_context_accepts_survey_launcher_arguments(self) -> None:
        context = gui.parse_launch_context(
            [
                "--survey-id",
                "NPA9999",
                "--project-root",
                r"C:\Projects\NPA9999",
                "--work-dir",
                r"C:\Projects\NPA9999\Data\Partial\Open Ends",
                "--source-root",
                r"C:\Projects\NPA9999\Data",
            ]
        )

        self.assertEqual(context.survey_id, "NPA9999")
        self.assertEqual(context.project_root, Path(r"C:\Projects\NPA9999").resolve())
        self.assertEqual(
            gui.default_session_path(context),
            Path(r"C:\Projects\NPA9999\Data\Partial\Open Ends\NPA9999.oe_session.sqlite").resolve(),
        )

    def test_wincross_export_opens_in_the_oes_folder(self) -> None:
        here = Path(__file__).resolve().parent
        oes = Path("C:/Job/Data/Partial/OEs")
        self.assertEqual(gui.wincross_export_folder(oes / "NPA1.oe_session.sqlite", None), oes)
        test_oes = Path("C:/Job/OG Clean/NPA1pt/Data/Partial/OEs - pt")
        self.assertEqual(gui.wincross_export_folder(test_oes / "NPA1.oe_session.sqlite", here), test_oes)
        elsewhere = Path("C:/Users/x/AppData/Local/OpenEndCoder")
        self.assertEqual(gui.wincross_export_folder(elsewhere / "a.oe_session.sqlite", here), here)
        self.assertEqual(gui.wincross_export_folder(elsewhere / "a.oe_session.sqlite", None), elsewhere)

    def test_code_choice_round_trip(self) -> None:
        item = core.CodeInfo(
            question_id=1,
            code="500",
            label="Health care costs",
            supercategory="Health Care",
            direction="-",
            source="user",
            active=True,
        )

        shown = gui.format_code_choice(item)

        self.assertEqual(shown, "500 | Health care costs")
        self.assertEqual(gui.parse_code_choice(shown), "500")

    def test_code_review_also_line_shows_each_other_codes_label(self) -> None:
        labels = {"3": "Cost of living, rent", "7": "Schools", "96": ""}
        self.assertEqual(gui.also_text(["3", "7"], labels), "   also 3 - Cost of living, rent; 7 - Schools")
        self.assertEqual(gui.also_text(["96", "12"], labels), "   also 96; 12")  # no label known: code alone
        self.assertEqual(gui.also_text([], labels), "")

    def test_import_scope_labels_map_to_core_values(self) -> None:
        self.assertEqual(gui.import_scope_key("New or changed"), "new_or_changed")
        self.assertEqual(gui.import_scope_key("New only"), "new")
        self.assertEqual(gui.import_scope_key("Source changed"), "changed")
        self.assertEqual(gui.import_scope_key("All active"), "all")
        self.assertEqual(gui.import_scope_key("unexpected"), "new_or_changed")


if __name__ == "__main__":
    unittest.main()
