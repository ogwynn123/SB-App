from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import survey_launcher_core as core
from survey_ops_lite import normalize_survey_id_from_path


class SurveyLauncherTests(unittest.TestCase):
    def _case_dir(self) -> Path:
        root = APP_ROOT / ".tmp_tests" / "survey_launcher"
        root.mkdir(parents=True, exist_ok=True)
        case = root / f"case_{uuid.uuid4().hex}"
        case.mkdir()
        self.addCleanup(lambda path=case: shutil.rmtree(path, ignore_errors=True))
        return case

    def test_normalize_survey_id(self) -> None:
        self.assertEqual(core.normalize_survey_id("1234"), "NPA1234")
        self.assertEqual(core.normalize_survey_id(" npa 3820! "), "NPA3820")
        self.assertEqual(normalize_survey_id_from_path(Path("Client/NPA3818 Track/Job")), "NPA3818")

    def test_context_does_not_create_folders_until_requested(self) -> None:
        root = self._case_dir() / "NPA9999 Project"
        root.mkdir()

        context = core.ProjectContext.from_values("9999", root)

        self.assertEqual(context.survey_id, "NPA9999")
        self.assertFalse((root / "Job").exists())
        self.assertFalse(context.manifest_path.exists())

    def test_project_startup_creates_layout_and_copies_latest_final_docx(self) -> None:
        root = self._case_dir() / "NPA9998 Project"
        qst = root / "Qst"
        later_folder = qst / "Revised"
        later_folder.mkdir(parents=True)
        older = qst / "NPA9998 Draft Final.docx"
        latest = later_folder / "NPA9998 Revised Final.docx"
        ignored = later_folder / "NPA9998 Final - Phone.docx"
        older.write_bytes(b"older")
        latest.write_bytes(b"latest")
        ignored.write_bytes(b"ignored")
        os.utime(older, (100, 100))
        os.utime(latest, (200, 200))
        os.utime(ignored, (300, 300))
        context = core.ProjectContext.from_values("NPA9998", root)

        result = core.run_project_startup(context)

        self.assertEqual(len(result.created_directories), 4)
        self.assertTrue((root / "Job").is_dir())
        self.assertTrue((root / "Data").is_dir())
        self.assertTrue((root / "Data" / "Partial").is_dir())
        self.assertTrue((root / "Job" / "Table Gen").is_dir())
        self.assertEqual(result.source_docx, latest)
        self.assertEqual(result.docx_action, "copied")
        self.assertEqual((root / "Job" / "Table Gen" / latest.name).read_bytes(), b"latest")
        self.assertEqual(result.check.status_label, "Ready")

        startup_tool = core.TOOL_BY_KEY["project_startup"]
        manifest_path = core.record_tool_launch(context, startup_tool, context.project_root)
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["project_root"], ".")
        self.assertEqual(payload["tools"]["project_startup"]["work_dir"], ".")

    def test_project_startup_reuses_folders_and_preserves_newer_conflict(self) -> None:
        root = self._case_dir() / "NPA9988 Project"
        qst = root / "Qst"
        table_gen = root / "Job" / "Table Gen"
        partial = root / "Data" / "Partial"
        qst.mkdir(parents=True)
        table_gen.mkdir(parents=True)
        partial.mkdir(parents=True)
        marker = partial / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        source = qst / "NPA9988 Final.docx"
        destination = table_gen / source.name
        source.write_bytes(b"source")
        destination.write_bytes(b"local edit")
        os.utime(source, (100, 100))
        os.utime(destination, (200, 200))
        context = core.ProjectContext.from_values("NPA9988", root)

        result = core.run_project_startup(context)

        self.assertEqual(result.created_directories, ())
        self.assertEqual(len(result.existing_directories), 4)
        self.assertEqual(result.docx_action, "destination_conflict")
        self.assertEqual(destination.read_bytes(), b"local edit")
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        self.assertEqual(result.check.status_label, "Review DOCX conflict")

    def test_project_startup_updates_older_final_copy(self) -> None:
        root = self._case_dir() / "NPA9987 Project"
        qst = root / "Qst"
        table_gen = root / "Job" / "Table Gen"
        qst.mkdir(parents=True)
        table_gen.mkdir(parents=True)
        (root / "Data" / "Partial").mkdir(parents=True)
        source = qst / "NPA9987 Final.docx"
        destination = table_gen / source.name
        source.write_bytes(b"new source")
        destination.write_bytes(b"old copy")
        os.utime(destination, (100, 100))
        os.utime(source, (200, 200))
        context = core.ProjectContext.from_values("NPA9987", root)

        result = core.run_project_startup(context)

        self.assertEqual(result.docx_action, "updated")
        self.assertEqual(destination.read_bytes(), b"new source")
        self.assertEqual(result.check.status_label, "Ready")

    def test_dependent_tools_require_project_startup(self) -> None:
        root = self._case_dir() / "NPA9986 Project"
        root.mkdir()
        context = core.ProjectContext.from_values("NPA9986", root)

        with self.assertRaisesRegex(FileNotFoundError, "Run Project Startup"):
            context.ensure_work_dir(core.TOOL_BY_KEY["wincross"])
        with self.assertRaisesRegex(FileNotFoundError, "Run Project Startup"):
            context.ensure_work_dir(core.TOOL_BY_KEY["table_merger"])

    def test_existing_folder_casing_is_reused(self) -> None:
        root = self._case_dir() / "NPA9997 Project"
        existing = root / "Job" / "table gen"
        existing.mkdir(parents=True)
        context = core.ProjectContext.from_values("NPA9997", root)

        work_dir = context.ensure_work_dir(core.TOOL_BY_KEY["wincross"])

        self.assertEqual(work_dir, existing)
        self.assertFalse((root / "Job" / "Table Gen").exists() and work_dir != root / "Job" / "Table Gen")

    def test_existing_open_end_convention_is_preferred(self) -> None:
        root = self._case_dir() / "NPA9996 Project"
        existing = root / "Data" / "Partial" / "OEs"
        existing.mkdir(parents=True)
        context = core.ProjectContext.from_values("NPA9996", root)

        work_dir = context.ensure_work_dir(core.TOOL_BY_KEY["open_end_coder"])

        self.assertEqual(work_dir, existing)

    def test_trend_updater_uses_table_gen_without_creating_it(self) -> None:
        root = self._case_dir() / "NPA9991 Project"
        root.mkdir()
        context = core.ProjectContext.from_values("NPA9991", root)
        tool = core.TOOL_BY_KEY["trend_table_updater"]

        with self.assertRaisesRegex(FileNotFoundError, "Run Project Startup"):
            context.ensure_work_dir(tool)

        core.run_project_startup(context)
        self.assertEqual(context.ensure_work_dir(tool), root / "Job" / "Table Gen")

    def test_open_end_coder_command_passes_project_context(self) -> None:
        case = self._case_dir()
        project_root = case / "NPA9996 Project"
        work_dir = project_root / "Data" / "Partial" / "Open Ends"
        work_dir.mkdir(parents=True)
        fake_app = case / "app"
        entry = fake_app / "pipelines" / "open_end_coder" / "oe_record_coder_gui.py"
        entry.parent.mkdir(parents=True)
        entry.write_text("", encoding="utf-8")
        context = core.ProjectContext.from_values("9996", project_root)
        tool = core.TOOL_BY_KEY["open_end_coder"]

        command = core.build_tool_command(
            context,
            tool,
            work_dir,
            app_root=fake_app,
            python_executable="python-test",
        )

        self.assertEqual(command[:2], ["python-test", str(entry)])
        self.assertEqual(command[command.index("--survey-id") + 1], "NPA9996")
        self.assertEqual(command[command.index("--project-root") + 1], str(project_root))
        self.assertEqual(command[command.index("--work-dir") + 1], str(work_dir))

    def test_wincross_command_passes_shared_context(self) -> None:
        case = self._case_dir()
        project_root = case / "NPA9995 Project"
        qst = project_root / "Qst"
        qst.mkdir(parents=True)
        fake_app = case / "app"
        entry = fake_app / "pipelines" / "wincross_table_generator" / "survey_pipeline_gui.py"
        entry.parent.mkdir(parents=True)
        entry.write_text("", encoding="utf-8")
        context = core.ProjectContext.from_values("9995", project_root)
        tool = core.TOOL_BY_KEY["wincross"]
        core.run_project_startup(context)
        work_dir = context.ensure_work_dir(tool)

        command = core.build_tool_command(
            context,
            tool,
            work_dir,
            app_root=fake_app,
            python_executable="python-test",
        )

        self.assertEqual(command[:2], ["python-test", str(entry)])
        self.assertEqual(command[command.index("--survey-id") + 1], "NPA9995")
        self.assertEqual(command[command.index("--work-dir") + 1], str(work_dir))
        self.assertEqual(command[command.index("--source-root") + 1], str(qst))

    def test_recent_project_pairing_is_reused_and_deduplicated(self) -> None:
        case = self._case_dir()
        settings_path = case / "launcher_settings.json"
        first_root = case / "NPA9994"
        second_root = case / "NPA9993"
        first_root.mkdir()
        second_root.mkdir()
        first = core.ProjectContext.from_values("9994", first_root)
        second = core.ProjectContext.from_values("9993", second_root)

        core.remember_project(first, settings_path=settings_path)
        core.remember_project(second, settings_path=settings_path)
        settings = core.remember_project(first, settings_path=settings_path)

        self.assertEqual(settings["last_survey_id"], "NPA9994")
        self.assertEqual(len(settings["recent_projects"]), 2)
        self.assertEqual(settings["recent_projects"][0]["project_root"], str(first_root.resolve()))

    def test_launch_is_process_isolated_and_records_context(self) -> None:
        case = self._case_dir()
        project_root = case / "NPA9990 Project"
        project_root.mkdir()
        fake_app = case / "app"
        entry = fake_app / "pipelines" / "table_merger" / "sheetMerging_GUI.py"
        entry.parent.mkdir(parents=True)
        entry.write_text("", encoding="utf-8")
        context = core.ProjectContext.from_values("9990", project_root)
        tool = core.TOOL_BY_KEY["table_merger"]
        core.run_project_startup(context)

        with patch.object(core.subprocess, "Popen") as popen:
            process, work_dir, command = core.launch_tool(context, tool, app_root=fake_app)

        self.assertIs(process, popen.return_value)
        self.assertEqual(work_dir, project_root / "Data")
        self.assertEqual(command[1], str(entry))
        call = popen.call_args
        self.assertEqual(call.kwargs["cwd"], str(work_dir))
        self.assertEqual(call.kwargs["env"]["SURVEY_PLATFORM_SURVEY_ID"], "NPA9990")
        self.assertEqual(call.kwargs["env"]["SURVEY_PLATFORM_PROJECT_ROOT"], str(project_root))
        self.assertEqual(call.kwargs["env"]["SURVEY_PLATFORM_WORK_DIR"], str(work_dir))
        self.assertEqual(call.kwargs["env"]["SURVEY_PLATFORM_SOURCE_ROOT"], str(project_root))
        self.assertTrue(context.manifest_path.exists())

    def test_survey_id_path_mismatch_is_reported(self) -> None:
        root = self._case_dir() / "NPA9992 Project"
        root.mkdir()
        context = core.ProjectContext.from_values("NPA9991", root)

        self.assertIn("NPA9992", context.warnings()[0])
        self.assertIn("NPA9991", context.warnings()[0])


if __name__ == "__main__":
    unittest.main()
