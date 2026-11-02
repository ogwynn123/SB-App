from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
import uuid
from datetime import date
from pathlib import Path
from unittest.mock import patch

from docx import Document
from docx.enum.text import WD_BREAK


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

        self.assertEqual(len(result.created_directories), 8)
        self.assertTrue((root / "Job").is_dir())
        self.assertTrue((root / "Data").is_dir())
        self.assertTrue((root / "Data" / "Partial").is_dir())
        for name in ("Banners", "OEs", "Results"):
            self.assertTrue((root / "Data" / "Partial" / name).is_dir(), name)
        self.assertTrue((root / "Job" / "Table Gen").is_dir())
        self.assertTrue((root / "Reports").is_dir())
        self.assertEqual(result.source_docx, latest)
        self.assertEqual(result.docx_action, "copied")
        expected_docs = [
            root / f"NPA9998 Revised {suffix}.docx"
            for suffix in ("Tab", "Trend Marginals", "Trend Tables", "Cover", "Results")
        ]
        self.assertEqual(list(result.created_documents), expected_docs)
        tab, trend_marginals, trend_tables, cover, results = expected_docs
        for path in (tab, trend_tables, cover):
            self.assertEqual("".join(p.text for p in Document(str(path)).paragraphs), "")
        # The fixture questionnaire is not a real DOCX, so the template's XX-NN stays.
        self.assertEqual([p.text for p in Document(str(trend_marginals)).paragraphs[:2]], ["XX-NN", "Trend Marginals"])
        self.assertEqual(results.read_bytes(), b"latest")  # Results starts as the Final questionnaire
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
        for name in ("Banners", "OEs", "Results"):
            (partial / name).mkdir(parents=True)
        (root / "Reports").mkdir()
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
        self.assertEqual(len(result.existing_directories), 9)  # the standard folders, Qst included
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

    def test_startup_document_names_drop_final_and_date(self) -> None:
        cases = {
            "NPA3887 Stelson PA-10 Track Week 2 Final 10.19.26": "NPA3887 Stelson PA-10 Track Week 2",
            "NPA3830 Benchmark FINAL 9.30.26": "NPA3830 Benchmark",
            "NPA3801 Poll_Final_20261019": "NPA3801 Poll",
            "NPA3802 Survey Final": "NPA3802 Survey",
            "Final": "NPA9999",
        }
        for stem, expected in cases.items():
            self.assertEqual(core.questionnaire_base_name(stem, "NPA9999"), expected, stem)

    def _questionnaire(self, path: Path, title_line: str) -> None:
        document = Document()
        document.add_paragraph("Hello, my name is ...")
        document.add_paragraph(title_line)
        document.add_paragraph("Democrat\t1")
        document.save(str(path))

    def test_trend_marginals_uses_template_with_the_questionnaire_area(self) -> None:
        cases = {
            "NPA9979\tOctober 20-22, 2026\tPA-10": "PA-10",
            "NPA9979  July 2026\tIllinois": "Illinois",
            "NPA9979 May 2026\t\tIA-01": "IA-01",
        }
        for title_line, area in cases.items():
            root = self._case_dir() / "NPA9979 Project"
            (root / "Qst").mkdir(parents=True)
            self._questionnaire(root / "Qst" / "NPA9979 Poll Final.docx", title_line)
            context = core.ProjectContext.from_values("NPA9979", root)

            result = core.run_project_startup(context)

            marginals = Document(str(root / "NPA9979 Poll Trend Marginals.docx"))
            self.assertEqual(marginals.paragraphs[0].text, area, title_line)
            self.assertTrue(marginals.paragraphs[0].runs[0].bold)  # template formatting kept
            self.assertEqual(marginals.paragraphs[1].text, "Trend Marginals")
            self.assertIn(f"for {area}", " ".join(result.document_notes))
            shutil.rmtree(root)

    def test_trend_marginals_falls_back_to_blank_without_template(self) -> None:
        root = self._case_dir() / "NPA9978 Project"
        (root / "Qst").mkdir(parents=True)
        self._questionnaire(root / "Qst" / "NPA9978 Poll Final.docx", "NPA9978\tJune 2026\tNV-03")
        context = core.ProjectContext.from_values("NPA9978", root)

        with patch.object(core, "TREND_MARGINALS_TEMPLATE", root / "missing.docx"):
            result = core.run_project_startup(context)

        marginals = root / "NPA9978 Poll Trend Marginals.docx"
        self.assertEqual("".join(p.text for p in Document(str(marginals)).paragraphs), "")
        self.assertIn("template not found", " ".join(result.document_notes))

    def _job(self, folder: Path, cover_name: str | None = None) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        if cover_name:
            (folder / cover_name).write_bytes(f"cover of {folder.name}".encode())
        return folder

    def test_prior_cover_is_the_latest_earlier_job_for_the_client(self) -> None:
        client = self._case_dir() / "Archive" / "Client"
        self._job(client / "2025" / "NPA9950 Benchmark", "NPA9950 Client XX-01 Cover.docx")
        self._job(client / "2026" / "NPA9960 Week 5", "NPA9960 Client XX-01 Week 5 Cover.docx")
        self._job(client / "2026" / "NPA9965 Week 4", "NPA9965 Client XX-01 Week 4 Cover DRAFT.docx")
        self._job(client / "2026" / "NPA9990 Week 1", "NPA9990 Client XX-01 Week 1 Cover.docx")  # later job
        self._job(client.parent / "Other Client" / "2026" / "NPA9969", "NPA9969 Other Cover.docx")
        current = self._job(client / "2026" / "NPA9970 Week 3")

        self.assertEqual(
            core.find_prior_cover(current, "NPA9970"),
            client / "2026" / "NPA9960 Week 5" / "NPA9960 Client XX-01 Week 5 Cover.docx",
        )
        first_of_year = self._job(client / "2026" / "NPA9955 Benchmark")
        self.assertEqual(
            core.find_prior_cover(first_of_year, "NPA9955"),
            client / "2025" / "NPA9950 Benchmark" / "NPA9950 Client XX-01 Cover.docx",
        )

    def test_prior_cover_from_a_test_folder_inside_the_job(self) -> None:
        year = self._case_dir() / "Archive" / "Client" / "2026"
        self._job(year / "NPA9920 Week 3", "NPA9920 Client Week 3 Cover.docx")
        job = self._job(year / "NPA9925 Week 2", "NPA9925 Client Week 2 Cover.docx")  # the real job's own cover
        test_folder = self._job(job / "Job" / "OG Clean" / "NPA9925pt")

        self.assertEqual(
            core.find_prior_cover(test_folder, "NPA9925"),
            year / "NPA9920 Week 3" / "NPA9920 Client Week 3 Cover.docx",
        )

    def _cover(self, path: Path) -> None:
        from docx.enum.section import WD_SECTION

        document = Document()
        for text in ("\tTABULAR REPORT", "\tNPA9900", "\tPREPARED FOR:", "PA-10", "\tOCTOBER 13-15, 2026"):
            document.add_paragraph(text)
        document.add_section(WD_SECTION.NEW_PAGE)
        document.add_paragraph("OVERVIEW")
        first = document.add_paragraph("The following is a survey among 400 likely voters in Iowa’s 1st ")
        first.add_run("Congressional District (the 10th District, not District 5) using landline (1")
        first.add_run("3%) and text (87%).  It was conducted September 29-October 1, 2026.")
        document.add_paragraph("In 95 cases out of 100, results fall within ±4.9 percentage points of the population.")
        document.add_paragraph("As with any survey, the release of selected figures could be damaging.")
        document.add_paragraph(
            "The data have been weighted by sex, age, and 2024 vote to better reflect the composition of the electorate."
        )
        document.add_paragraph("SUBGROUP DEFINITIONS").runs[0].add_break(WD_BREAK.PAGE)
        document.add_paragraph("3+\tVoters who voted in 3 or more of the 2024, 2022, 2020 or 2018 elections.")
        document.save(str(path))

    def test_copied_cover_gets_new_survey_id_and_highlights(self) -> None:
        import cover_prep

        path = self._case_dir() / "cover.docx"
        self._cover(path)

        changes = cover_prep.prepare_copied_cover(path, "NPA9905")

        document = Document(str(path))
        texts = [p.text for p in document.paragraphs]
        highlighted = {
            p.text[:12]: "".join(r.text for r in p.runs if r.font.highlight_color)
            for p in document.paragraphs
            if any(r.font.highlight_color for r in p.runs)
        }
        self.assertIn("\tNPA9905", texts)
        self.assertNotIn("\tNPA9900", texts)
        self.assertEqual(changes.survey_ids_replaced, 1)
        self.assertEqual(highlighted["\tOCTOBER 13-"], "OCTOBER 13-15, 2026")
        # District numbers ("1st Congressional District", "10th District", "District 5") are left alone.
        self.assertEqual(highlighted["The followin"], "40013%87%September 29-October 1, 2026")
        self.assertEqual(highlighted["In 95 cases "], "±4.9")  # 95 and 100 are not touched
        self.assertEqual(highlighted["The data hav"], "weighted by sex, age, and 2024 vote")
        self.assertNotIn("3+\tVoters who", highlighted)  # page 3 is left alone
        self.assertNotIn("As with any ", highlighted)
        self.assertEqual(changes.notes, ())

    def _intake_project(self, survey_id: str) -> core.ProjectContext:
        root = self._case_dir() / "Archive" / "Stelson" / "2026" / f"{survey_id} Track Week 2"
        (root / "Qst").mkdir(parents=True)
        self._questionnaire(root / "Qst" / f"{survey_id} Stelson PA-10 Final.docx", f"{survey_id}\tOctober 2026\tPA-10")
        return core.ProjectContext.from_values(survey_id, root)

    def test_data_intake_names_reports_with_todays_date(self) -> None:
        import data_intake

        context = self._intake_project("NPA9910")
        downloads = self._case_dir()
        report_target, zip_target = data_intake.TARGETS
        first = downloads / "p3794 PA-10 1315Oct2026 1.xlsx"
        first.write_bytes(b"night 1")
        second = downloads / "p3794 PA-10 1315Oct2026 2.xlsx"
        second.write_bytes(b"night 2")

        self.assertIsNotNone(data_intake.check_source(zip_target, first))  # only .zip goes in the zip box
        self.assertEqual(data_intake.report_name_stem(context), "NPA9910 Stelson PA-10")
        first_dest = data_intake.destination_for(context, report_target, first)
        today = date.today().strftime("%m.%d.%y")
        self.assertEqual(first_dest, context.project_root / "Reports" / f"NPA9910 Stelson PA-10 {today}.xlsx")
        self.assertEqual(data_intake.place_file(first, first_dest), "copied")
        self.assertTrue(first.exists())  # copied, not moved

        second_dest = data_intake.destination_for(context, report_target, second)
        self.assertEqual(second_dest.name, f"NPA9910 Stelson PA-10 {today} (2).xlsx")  # second report, same day
        data_intake.place_file(second, second_dest)
        # Dropping the first report again finds its copy instead of making a third.
        again = data_intake.destination_for(context, report_target, first)
        self.assertEqual(again, first_dest)
        self.assertEqual(data_intake.place_file(first, again), "identical")

    def test_data_intake_unzips_and_renames_csv_and_codelist(self) -> None:
        import zipfile

        import data_intake

        context = self._intake_project("NPA9912")
        archive = self._case_dir() / "export.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("export/p3794_data.csv", "a,b\n1,2\n")
            bundle.writestr("export/p3794 codes.xlsx", b"xlsx bytes")
            bundle.writestr("export/readme.txt", "notes")
            bundle.writestr("__MACOSX/export/._p3794_data.csv", "junk")
        data = context.project_root / "Data"
        data.mkdir()
        (data / "NPA9912.csv").write_text("older delivery", encoding="utf-8")

        kept = data_intake.unzip_data(context, archive)  # existing different CSV is not replaced
        self.assertEqual((data / "NPA9912.csv").read_text(encoding="utf-8"), "older delivery")
        self.assertEqual(kept.kept, [data / "NPA9912.csv"])
        self.assertEqual((data / "NPA9912 Working Codelist.xlsx").read_bytes(), b"xlsx bytes")
        self.assertTrue((data / "readme.txt").exists())
        self.assertFalse(any("MACOSX" in p.name or p.name.startswith("._") for p in data.iterdir()))

        replaced = data_intake.unzip_data(context, archive, replace=lambda _path: True)
        self.assertEqual((data / "NPA9912.csv").read_text(encoding="utf-8"), "a,b\n1,2\n")
        self.assertIn(("p3794_data.csv", data / "NPA9912.csv"), replaced.renamed)

        two_csvs = self._case_dir() / "two.zip"
        with zipfile.ZipFile(two_csvs, "w") as bundle:
            bundle.writestr("one.csv", "1")
            bundle.writestr("two.csv", "2")
        result = data_intake.unzip_data(context, two_csvs)
        self.assertTrue((data / "one.csv").exists() and (data / "two.csv").exists())
        self.assertTrue(any("2 .csv files" in note for note in result.notes))

    def test_data_intake_window_adds_dropped_files(self) -> None:
        import tkinter as tk

        import data_intake

        import zipfile

        context = self._intake_project("NPA9911")
        root_dir = context.project_root
        downloads = self._case_dir()
        (downloads / "report.xlsx").write_bytes(b"r")
        with zipfile.ZipFile(downloads / "data.zip", "w") as bundle:
            bundle.writestr("data.csv", "x")
            bundle.writestr("codes.xlsx", "c")
        try:
            tk_root = tk.Tk()
        except tk.TclError:
            self.skipTest("No display for Tk")
        tk_root.withdraw()
        self.addCleanup(tk_root.destroy)
        logged: list[str] = []

        dialog = data_intake.DataIntakeDialog(tk_root, context, log=logged.append)
        report_target, zip_target = data_intake.TARGETS
        dialog._choose(report_target, [downloads / "report.xlsx"])
        dialog._choose(zip_target, [downloads / "data.zip"])
        dialog.add_files()

        today = date.today().strftime("%m.%d.%y")
        self.assertEqual((root_dir / "Reports" / f"NPA9911 Stelson PA-10 {today}.xlsx").read_bytes(), b"r")
        self.assertFalse((root_dir / "Data" / "data.zip").exists())  # removed after unzipping
        self.assertTrue((downloads / "data.zip").exists())  # the original stays
        self.assertEqual((root_dir / "Data" / "NPA9911.csv").read_text(encoding="utf-8"), "x")
        self.assertTrue((root_dir / "Data" / "NPA9911 Working Codelist.xlsx").exists())
        self.assertTrue(any("NPA9911.csv" in line for line in logged))
        self.assertTrue((root_dir / "Data" / "Partial" / "NPA9911 Stelson PA-10 Day 1.docx").exists())
        dialog.destroy()

    def test_partial_day_document_counts_field_days(self) -> None:
        import data_intake

        context = self._intake_project("NPA9914")
        partial = context.project_root / "Data" / "Partial"
        base = "NPA9914 Stelson PA-10"

        day1, created = data_intake.partial_day_document(context, date(2026, 10, 20))
        self.assertEqual((day1, created), (partial / f"{base} Day 1.docx", True))
        again, created = data_intake.partial_day_document(context, date(2026, 10, 20))
        self.assertEqual((again, created), (day1, False))  # same day: no Day 2

        (partial / f"{base} Day 2 SB1.docx").write_bytes(b"made by hand")  # variants count
        day3, created = data_intake.partial_day_document(context, date(2026, 10, 21))
        self.assertEqual((day3, created), (partial / f"{base} Day 3.docx", True))
        self.assertEqual("".join(p.text for p in Document(str(day3)).paragraphs), "")
        self.assertEqual((partial / f"{base} Day 2 SB1.docx").read_bytes(), b"made by hand")

    def _first_merge(self, data: Path) -> None:
        """Run one real merge the way the Table Merger window does, leaving a merge_runs record."""
        import subprocess

        merge = data / "Merge"
        merge.mkdir(parents=True)
        (merge / "NPA9915.csv").write_text("survnum,q1,q2,qold\n1,1,2,x\n2,2,1,y\n", encoding="utf-8")
        (merge / "NPA9900ts.csv").write_text(
            "survnum,TIMESERIES,q1,q2,legacy\n10,1,1,1,a\n11,1,2,2,b\n", encoding="utf-8"
        )
        subprocess.run(
            [
                sys.executable, str(APP_ROOT / "pipelines" / "table_merger" / "unified_merge.py"),
                "--primary", str(merge / "NPA9915.csv"), "--secondary", str(merge / "NPA9900ts.csv"),
                "--primary-join", "survnum", "--secondary-join", "survnum",
                "--output", str(merge / "NPA9915ts.csv"), "--map", "q2=q2", "--block-primary", "qold",
                "--report-dir", str(merge / "compilingReports"), "--archive-dir", str(merge / "surveyInput"),
                "--ignore-config",
            ],
            cwd=str(merge), check=True, capture_output=True,
        )

    def test_this_waves_files_are_staged_in_merge_before_the_first_merge(self) -> None:
        sys.path.insert(0, str(APP_ROOT / "pipelines" / "table_merger"))
        import merge_autorun
        from sheet_merge_core import merge_folder_defaults

        root = self._case_dir() / "NPA9930 Track Week 2"
        merge = root / "Data" / "Merge"
        merge.mkdir(parents=True)
        (merge / "NPA9920tsSB.csv").write_text("earlier wave", encoding="utf-8")
        (merge / "NPA9920 Client Week 1 FinalJSON.json").write_text("{}", encoding="utf-8")
        (root / "Data" / "NPA9930.csv").write_text("day 1", encoding="utf-8")
        table_gen = root / "Job" / "Table Gen"
        table_gen.mkdir(parents=True)
        (table_gen / "NPA9930 Client Week 2 FinalJSON.json").write_text('{"elements": []}', encoding="utf-8")
        context = core.ProjectContext.from_values("NPA9930", root)

        notes = merge_autorun.seed_first_merge(context)

        self.assertEqual(len(notes), 2)
        self.assertEqual((merge / "NPA9930.csv").read_text(encoding="utf-8"), "day 1")
        self.assertTrue((merge / "NPA9930 Client Week 2 FinalJSON.json").exists())
        self.assertEqual(merge_autorun.seed_first_merge(context), [])  # nothing new
        defaults = merge_folder_defaults(merge, "NPA9930")
        self.assertEqual(defaults["primary"].name, "NPA9930.csv")
        self.assertEqual(defaults["secondary"].name, "NPA9920tsSB.csv")
        self.assertEqual(defaults["primary_survey_json"].name, "NPA9930 Client Week 2 FinalJSON.json")
        self.assertEqual(defaults["secondary_survey_json"].name, "NPA9920 Client Week 1 FinalJSON.json")

        day2 = root / "Data" / "NPA9930.csv"
        day2.write_text("day 2", encoding="utf-8")
        [note] = merge_autorun.seed_first_merge(context, day2)
        self.assertIn("older copy", note)
        self.assertEqual((merge / "NPA9930.csv").read_text(encoding="utf-8"), "day 2")
        backups = list((merge / "Backups").glob("*/NPA9930.csv"))
        self.assertEqual([b.read_text(encoding="utf-8") for b in backups], ["day 1"])
        self.assertEqual((merge / "NPA9920tsSB.csv").read_text(encoding="utf-8"), "earlier wave")

        (merge / "merge_runs").mkdir()
        (merge / "merge_runs" / "merge_20261102_100000.json").write_text("{}", encoding="utf-8")
        day2.write_text("day 3", encoding="utf-8")
        self.assertEqual(merge_autorun.seed_first_merge(context, day2), [])  # the rerun takes over

    def test_new_data_reruns_last_merge_with_same_mapping_and_columns(self) -> None:
        import pandas as pd

        import merge_autorun

        context = self._intake_project("NPA9915")
        data = context.project_root / "Data"
        self.assertEqual(merge_autorun.rerun_last_merge(context, data / "NPA9915.csv").status, "no_previous_merge")
        self._first_merge(data)
        first_run = merge_autorun.latest_merge_run(context)
        # The analyst renamed a column in the trend file after the first merge.
        trend = data / "Merge" / "NPA9915ts.csv"
        frame = pd.read_csv(trend, dtype=str, keep_default_na=False)
        renamed_from = frame.columns[-1]
        frame.rename(columns={renamed_from: "LEGACY_RENAMED"}).to_csv(trend, index=False)
        previous_columns = list(pd.read_csv(trend, nrows=0).columns)

        new_day = data / "NPA9915.csv"
        new_day.write_text("survnum,q1,q2,qold\n1,1,2,x\n2,2,1,y\n3,1,1,z\n", encoding="utf-8")
        result = merge_autorun.rerun_last_merge(context, new_day)

        self.assertEqual(result.status, "merged", result.detail)
        self.assertEqual(result.mapping_differences, [])
        self.assertNotEqual(merge_autorun.latest_merge_run(context), first_run)
        merged = pd.read_csv(trend, dtype=str, keep_default_na=False)
        self.assertEqual(list(merged.columns), previous_columns)  # names and order kept
        self.assertEqual(len(merged), 2 + 3)  # earlier wave + all of today's rows
        self.assertTrue((result.backup_dir / "NPA9915ts.csv").exists())
        # The main Data folder gets the realigned trend file, not the pre-alignment one.
        self.assertEqual((data / "NPA9915ts.csv").read_bytes(), trend.read_bytes())
        self.assertTrue(any(line.startswith("Copied to Data: ") for line in result.log_lines))
        self.assertEqual((data / "Merge" / "NPA9915.csv").read_text(encoding="utf-8"), new_day.read_text(encoding="utf-8"))
        self.assertTrue(any("LEGACY_RENAMED" in line for line in result.log_lines))

    def test_from_outlook_fills_boxes_from_attachments(self) -> None:
        import tkinter as tk

        import data_intake

        context = self._intake_project("NPA9913")
        saved = self._case_dir()
        report = saved / "PA-10 1315Oct2026 1.xlsx"
        report.write_bytes(b"r")
        archive = saved / "p3794 export.zip"
        archive.write_bytes(b"z")
        self.assertEqual(data_intake.sort_attachments([report, archive]), {"zip": [archive], "report": [report]})
        try:
            tk_root = tk.Tk()
        except tk.TclError:
            self.skipTest("No display for Tk")
        tk_root.withdraw()
        self.addCleanup(tk_root.destroy)
        dialog = data_intake.DataIntakeDialog(tk_root, context)

        with patch.object(data_intake, "save_outlook_attachments", return_value=("Nightly", [report, archive])):
            dialog.from_outlook()
        self.assertEqual(dialog.chosen, {"report": report, "zip": archive})

        dialog.chosen = {"report": None, "zip": None}
        with patch.object(data_intake, "save_outlook_attachments", side_effect=RuntimeError("Outlook is not open.")), \
                patch.object(data_intake.messagebox, "showwarning") as warning:
            dialog.from_outlook()
        warning.assert_called_once()
        self.assertEqual(dialog.chosen, {"report": None, "zip": None})

        second = saved / "PA-10 1315Oct2026 2.xlsx"
        second.write_bytes(b"r2")
        with patch.object(data_intake, "save_outlook_attachments", return_value=("Nightly", [report, second])), \
                patch.object(dialog, "_pick", return_value=second) as pick:
            dialog.from_outlook()
        pick.assert_called_once()
        self.assertEqual(dialog.chosen["report"], second)
        dialog.destroy()

    def test_startup_creates_merge_folder_when_client_has_earlier_job(self) -> None:
        from project_status import merge_status

        year = self._case_dir() / "Archive" / "Client" / "2026"
        prior = self._job(year / "NPA9890 Week 3")
        (prior / "Job" / "Table Gen").mkdir(parents=True)
        (prior / "Job" / "Table Gen" / "NPA9890 Client Week 3 FinalJSON.json").write_text("{}", encoding="utf-8")
        (prior / "Data").mkdir()
        for name in ("NPA9890.csv", "NPA9890ts.csv", "NPA9890tsSB.csv", "NPA9890tsSBw2018added.csv"):
            (prior / "Data" / name).write_text(name, encoding="utf-8")
        tracking = self._job(year / "NPA9895 Week 2")
        context = core.ProjectContext.from_values("NPA9895", tracking)

        result = core.run_project_startup(context)

        self.assertEqual(result.prior_job, prior)
        merge = tracking / "Data" / "Merge"
        self.assertIn(merge, result.created_directories)
        self.assertEqual(
            sorted(p.name for p in merge.iterdir()), ["NPA9890 Client Week 3 FinalJSON.json", "NPA9890tsSB.csv"]
        )
        self.assertTrue((prior / "Data" / "NPA9890tsSB.csv").exists())  # copied, not moved
        self.assertTrue(any("Copied NPA9890tsSB.csv" in note for note in result.document_notes))
        status = merge_status(context)
        self.assertEqual(status.state, "todo")
        self.assertIn("earlier job: NPA9890 Week 3", status.summary)
        self.assertEqual(core.run_project_startup(context).created_directories, ())  # second run: nothing new

        first = self._job(self._case_dir() / "Archive" / "New Client" / "2026" / "NPA9896")
        first_context = core.ProjectContext.from_values("NPA9896", first)
        self.assertIsNone(core.run_project_startup(first_context).prior_job)
        self.assertFalse((first / "Data" / "Merge").exists())
        self.assertEqual(merge_status(first_context).state, "info")

    def test_prior_merge_inputs_pick_the_sample_balanced_file(self) -> None:
        job = self._job(self._case_dir() / "NPA9880 Week 4")
        (job / "Data").mkdir()
        for name in ("NPA9880tsRR.csv", "NPA9880tsRR - backup sb.csv", "NPA9880tsRRsb.csv"):
            (job / "Data" / name).write_text("x", encoding="utf-8")
        files, notes = core.prior_merge_inputs(job)
        self.assertEqual([p.name for p in files], ["NPA9880tsRRsb.csv"])
        self.assertIn("no questionnaire JSON", notes[0])

        (job / "Data" / "NPA9880tsSB1sb.csv").write_text("x", encoding="utf-8")
        files, notes = core.prior_merge_inputs(job)
        self.assertEqual(files, [])
        self.assertTrue(any("several sample-balanced files" in note for note in notes))

    def test_prior_cover_searches_sibling_year_subfolders(self) -> None:
        year = self._case_dir() / "Archive" / "Client" / "2026"
        self._job(year / "Primary" / "NPA9940", "NPA9940 Client Primary Cover.docx")
        current = self._job(year / "General" / "NPA9945")

        self.assertEqual(core.find_prior_cover(current, "NPA9945"), year / "Primary" / "NPA9940" / "NPA9940 Client Primary Cover.docx")

    def test_project_startup_copies_prior_cover_or_makes_blank(self) -> None:
        year = self._case_dir() / "Archive" / "Client" / "2026"
        self._job(year / "NPA9930 Week 4", "NPA9930 Client Week 4 Cover.docx")
        root = self._job(year / "NPA9935 Week 3")
        (root / "Qst").mkdir()
        (root / "Qst" / "NPA9935 Client Week 3 Final.docx").write_bytes(b"qst")
        context = core.ProjectContext.from_values("NPA9935", root)

        result = core.run_project_startup(context)

        self.assertEqual((root / "NPA9935 Client Week 3 Cover.docx").read_bytes(), b"cover of NPA9930 Week 4")
        self.assertIn("Cover copied from the prior job", " ".join(result.document_notes))

        lonely = self._job(self._case_dir() / "Archive" / "New Client" / "2026" / "NPA9936")
        (lonely / "Qst").mkdir()
        (lonely / "Qst" / "NPA9936 New Final.docx").write_bytes(b"qst")
        blank = core.run_project_startup(core.ProjectContext.from_values("NPA9936", lonely))
        self.assertEqual("".join(p.text for p in Document(str(lonely / "NPA9936 New Cover.docx")).paragraphs), "")
        self.assertIn("created a blank Cover", " ".join(blank.document_notes))

    def test_project_startup_keeps_existing_documents_and_skips_without_final(self) -> None:
        root = self._case_dir() / "NPA9984 Project"
        (root / "Qst").mkdir(parents=True)
        context = core.ProjectContext.from_values("NPA9984", root)

        without_final = core.run_project_startup(context)
        self.assertEqual(without_final.created_documents, ())
        self.assertEqual(list(root.glob("*.docx")), [])

        (root / "Qst" / "NPA9984 Poll Final 10.1.26.docx").write_bytes(b"qst")
        tab = root / "NPA9984 Poll Tab.docx"
        tab.write_bytes(b"analyst edits")
        result = core.run_project_startup(context)

        self.assertEqual(result.existing_documents, (tab,))
        self.assertEqual(len(result.created_documents), 4)
        self.assertEqual(tab.read_bytes(), b"analyst edits")
        self.assertEqual(core.run_project_startup(context).created_documents, ())

    def test_project_startup_empties_only_a_new_results_copy_with_word(self) -> None:
        root = self._case_dir() / "NPA9983 Project"
        (root / "Qst").mkdir(parents=True)
        (root / "Qst" / "NPA9983 Poll Final.docx").write_bytes(b"qst")
        context = core.ProjectContext.from_values("NPA9983", root)

        with patch.object(core, "run_word_macro", return_value=(True, "Ran it.")) as word, patch.object(
            core, "export_pdf_with_word", return_value=(False, "no Word in tests")
        ):
            first = core.run_project_startup(context, use_word=True)
            second = core.run_project_startup(context, use_word=True)

        word.assert_called_once_with(root / "NPA9983 Poll Results.docx", core.RESULTS_EMPTY_MACRO)
        self.assertEqual(first.results_macro_status, "emptied")
        self.assertEqual(second.results_macro_status, "not_run")
        self.assertIn("already existed", second.results_macro_detail)

    def test_project_startup_reports_word_failure_and_keeps_results_copy(self) -> None:
        root = self._case_dir() / "NPA9982 Project"
        (root / "Qst").mkdir(parents=True)
        (root / "Qst" / "NPA9982 Poll Final.docx").write_bytes(b"qst")
        context = core.ProjectContext.from_values("NPA9982", root)

        with patch.object(core, "run_word_macro", return_value=(False, "Word could not run it.")), patch.object(
            core, "export_pdf_with_word", return_value=(False, "no Word in tests")
        ):
            result = core.run_project_startup(context, use_word=True)

        self.assertEqual(result.results_macro_status, "failed")
        self.assertEqual((root / "NPA9982 Poll Results.docx").read_bytes(), b"qst")

    def test_project_startup_saves_questionnaire_pdf_in_qst_and_table_gen(self) -> None:
        root = self._case_dir() / "NPA9981 Project"
        (root / "Qst").mkdir(parents=True)
        source = root / "Qst" / "NPA9981 Poll Final 10.1.26.docx"
        source.write_bytes(b"qst")
        context = core.ProjectContext.from_values("NPA9981", root)

        def fake_export(document, pdf):
            pdf.write_bytes(b"%PDF from " + document.name.encode())
            return True, f"Saved {pdf.name}."

        with patch.object(core, "export_pdf_with_word", side_effect=fake_export) as export, patch.object(
            core, "run_word_macro", return_value=(True, "Ran it.")
        ):
            first = core.run_project_startup(context, use_word=True)
            second = core.run_project_startup(context, use_word=True)

        qst_pdf = source.with_suffix(".pdf")
        table_gen_pdf = root / "Job" / "Table Gen" / qst_pdf.name
        export.assert_called_once_with(source, qst_pdf)
        self.assertEqual(first.pdf_status, "created")
        self.assertEqual(first.pdf_paths, (qst_pdf, table_gen_pdf))
        self.assertEqual(table_gen_pdf.read_bytes(), qst_pdf.read_bytes())
        self.assertEqual(second.pdf_status, "exists")
        self.assertEqual(second.pdf_paths, ())

    def test_project_startup_never_replaces_an_older_pdf(self) -> None:
        root = self._case_dir() / "NPA9980 Project"
        (root / "Qst").mkdir(parents=True)
        source = root / "Qst" / "NPA9980 Poll Final.docx"
        source.write_bytes(b"qst")
        pdf = source.with_suffix(".pdf")
        pdf.write_bytes(b"old pdf")
        os.utime(pdf, (100, 100))
        context = core.ProjectContext.from_values("NPA9980", root)

        with patch.object(core, "export_pdf_with_word") as export, patch.object(
            core, "run_word_macro", return_value=(True, "Ran it.")
        ):
            result = core.run_project_startup(context, use_word=True)

        export.assert_not_called()
        self.assertEqual(result.pdf_status, "stale")
        self.assertEqual(pdf.read_bytes(), b"old pdf")
        self.assertFalse((root / "Job" / "Table Gen" / pdf.name).exists())

    def test_project_startup_reuses_open_ends_instead_of_adding_oes(self) -> None:
        root = self._case_dir() / "NPA9985 Project"
        open_ends = root / "Data" / "Partial" / "Open Ends"
        open_ends.mkdir(parents=True)
        context = core.ProjectContext.from_values("NPA9985", root)

        result = core.run_project_startup(context)

        self.assertFalse((root / "Data" / "Partial" / "OEs").exists())
        self.assertIn(open_ends, result.existing_directories)
        self.assertTrue((root / "Data" / "Partial" / "Banners").is_dir())
        self.assertTrue((root / "Data" / "Partial" / "Results").is_dir())
        self.assertEqual(core.inspect_project_startup(context).missing_directories, ())

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

    def test_startup_creates_a_missing_qst_folder(self) -> None:
        project_root = self._case_dir() / "NPA9987 Project"
        (project_root / "Data").mkdir(parents=True)
        context = core.ProjectContext.from_values("9987", project_root)
        self.assertIn(project_root / "Qst", core.inspect_project_startup(context).missing_directories)

        result = core.run_project_startup(context)

        self.assertTrue((project_root / "Qst").is_dir())
        self.assertIn(project_root / "Qst", result.created_directories)
        self.assertEqual(result.docx_action, "no_final_docx")
        self.assertEqual(result.check.docx_status, "no_final_docx")
        self.assertEqual(core.run_project_startup(context).created_directories, ())

    def test_test_run_sends_outputs_to_the_og_clean_test_folder(self) -> None:
        case = self._case_dir()
        project_root = case / "NPA9989 Project"
        project_root.mkdir()
        fake_app = case / "app"
        for parts in (("table_merger", "sheetMerging_GUI.py"), ("wincross_table_generator", "survey_pipeline_gui.py")):
            entry = fake_app / "pipelines" / parts[0] / parts[1]
            entry.parent.mkdir(parents=True)
            entry.write_text("", encoding="utf-8")
        context = core.ProjectContext.from_values("9989", project_root)
        core.run_project_startup(context)
        expected = project_root / "Job" / "OG Clean" / "NPA9989pt"
        self.assertEqual(core.test_output_dir(context, create=False), expected)
        self.assertFalse(expected.exists())

        with patch.object(core.subprocess, "Popen") as popen:
            _process, work_dir, _command = core.launch_tool(
                context, core.TOOL_BY_KEY["table_merger"], app_root=fake_app, test_run=True)
        env = popen.call_args.kwargs["env"]
        self.assertEqual(work_dir, project_root / "Data")  # inputs still come from Data
        self.assertEqual(env["SURVEY_PLATFORM_OUTPUT_DIR"], str(expected))
        self.assertEqual(env["SURVEY_PLATFORM_TEST_RUN"], "1")
        self.assertTrue(expected.is_dir())

        with patch.object(core.subprocess, "Popen") as popen:
            _process, work_dir, command = core.launch_tool(
                context, core.TOOL_BY_KEY["wincross"], app_root=fake_app, test_run=True)
        self.assertEqual(work_dir, expected)  # Table Gen writes into its work folder
        self.assertEqual(command[command.index("--work-dir") + 1], str(expected))

        with patch.object(core.subprocess, "Popen") as popen:
            core.launch_tool(context, core.TOOL_BY_KEY["table_merger"], app_root=fake_app)
        env = popen.call_args.kwargs["env"]
        self.assertEqual(env["SURVEY_PLATFORM_OUTPUT_DIR"], str(project_root / "Data"))
        self.assertEqual(env["SURVEY_PLATFORM_TEST_RUN"], "")

    def test_open_end_draft_plan_finds_data_open_ends_and_lead_ins(self) -> None:
        case = self._case_dir()
        project_root = case / "NPA9988 Project"
        project_root.mkdir()
        context = core.ProjectContext.from_values("9988", project_root)
        core.run_project_startup(context)
        data = project_root / "Data"
        (data / "NPA9988.csv").write_text(
            "survnum,q5,q6,c6_1,c6_2,c6_3,3854_q9,3854_c9_1,3854_c9_2,3854_c9_3\n"
            "1,1,Good on taxes,,,,old,,,\n2,2,Too old,,,,old,,,\n",
            encoding="utf-8",
        )
        (data / "NPA9988 Quotas.csv").write_text("x\n", encoding="utf-8")
        table_gen = project_root / "Job" / "Table Gen"
        table_gen.mkdir(parents=True, exist_ok=True)
        (table_gen / "NPA9988 FinalJSON.json").write_text(json.dumps({"elements": [
            {"type": "question", "qnum": "5", "text": "Has your opinion of Smith gotten more or less favorable?",
             "question_type": "opinion_trend", "instructions": [],
             "response_options": [{"value": "1", "text": "More favorable"}, {"value": "2", "text": "Less favorable"}]},
            {"type": "question", "qnum": "6", "text": "What are you hearing about Smith?", "instructions": []},
        ]}), encoding="utf-8")

        spec = core.plan_oe_draft(context, test_run=True)

        self.assertEqual(Path(spec["data"]).name, "NPA9988.csv")
        self.assertEqual([q["column"] for q in spec["questions"]], ["q6"])  # carried 3854_q9 skipped
        self.assertEqual(spec["questions"][0]["text"], "What are you hearing about Smith?")
        self.assertEqual(spec["questions"][0]["lead"]["column"], "q5")
        self.assertEqual(spec["questions"][0]["lead"]["options"], ["More favorable", "Less favorable"])
        self.assertEqual(Path(spec["out"]).parent, project_root / "Job" / "OG Clean" / "NPA9988pt")
        self.assertEqual(spec["notes"], [])

    def test_survey_id_path_mismatch_is_reported(self) -> None:
        root = self._case_dir() / "NPA9992 Project"
        root.mkdir()
        context = core.ProjectContext.from_values("NPA9991", root)

        self.assertIn("NPA9992", context.warnings()[0])
        self.assertIn("NPA9991", context.warnings()[0])

    def test_project_startup_accepts_final_followed_by_a_date(self) -> None:
        root = self._case_dir() / "NPA9994 Track Week 2"
        qst = root / "Qst"
        qst.mkdir(parents=True)
        files = {
            "NPA9994 Track Week 2 Draft 1.docx": 100,
            "NPA9994 Track Week 2 Final 10.19.26.docx": 200,
            "NPA9994 Track Week 2 Final - Phone.docx": 300,
            "NPA9994 Track Week 2 Final - SMS.docx": 400,
            "NPA9994 SPANISH FINAL 10.19.26.docx": 500,
        }
        for name, stamp in files.items():
            (qst / name).write_bytes(name.encode())
            os.utime(qst / name, (stamp, stamp))
        context = core.ProjectContext.from_values("NPA9994", root)

        self.assertEqual(core.find_latest_final_docx(context), qst / "NPA9994 Track Week 2 Final 10.19.26.docx")

        for stem in ("X FINAL 9.30.26", "X Final 10-19-2026", "X Final_20261019", "X Final", "X FINALFINAL"):
            self.assertTrue(core.is_final_questionnaire_name(stem), stem)
        for stem in ("X Final - Phone", "X Spanish Final", "X Semifinal", "X Final 2", "X Finalized"):
            self.assertFalse(core.is_final_questionnaire_name(stem), stem)

    def test_tomas_is_off_by_default_and_can_be_turned_on(self) -> None:
        import platform_features

        case = self._case_dir()
        config = case / "survey_tool_config.json"
        with patch.dict(os.environ, {"SURVEYPLATFORM_TOMAS": ""}):
            self.assertFalse(platform_features.tomas_enabled(config))
            config.write_text(json.dumps({"features": {"tomas": "yes"}}), encoding="utf-8")
            self.assertFalse(platform_features.tomas_enabled(config))
            config.write_text(json.dumps({"features": {"tomas": True}}), encoding="utf-8")
            self.assertTrue(platform_features.tomas_enabled(config))
        with patch.dict(os.environ, {"SURVEYPLATFORM_TOMAS": "0"}):
            self.assertFalse(platform_features.tomas_enabled(config))

        with patch.dict(os.environ, {"SURVEYPLATFORM_TOMAS": "0"}):
            self.assertNotIn("tomas", [tool.key for tool in core.active_tools()])
        with patch.dict(os.environ, {"SURVEYPLATFORM_TOMAS": "1"}):
            self.assertIn("tomas", [tool.key for tool in core.active_tools()])
        self.assertIn("tomas", core.TOOL_BY_KEY)

    def _write_csv(self, path: Path, rows: list[list[str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(",".join(row) for row in rows) + "\n", encoding="utf-8")

    def test_launcher_lists_every_daily_tool(self) -> None:
        keys = [tool.key for tool in core.TOOLS]
        for key in (
            "project_startup", "wincross", "table_merger", "sample_append", "open_end_coder", "quota_checker",
            "trend_table_updater", "auto_results", "prelim_qc", "dashboard", "browser_workbench",
        ):
            self.assertIn(key, keys)
        self.assertEqual(core.resolve_tool_entry(core.TOOL_BY_KEY["dashboard"]).name, "survey_platform_gui.py")
        self.assertEqual(core.resolve_tool_entry(core.TOOL_BY_KEY["browser_workbench"]).name, "run_survey_browser.bat")

    def test_sample_append_picks_newest_timeseries_and_remembers_columns(self) -> None:
        root = self._case_dir() / "NPA9997 Track"
        data_dir = root / "Data"
        self._write_csv(data_dir / "NPA9997.csv", [["voterbaseid", "score"], ["A", ""]])
        self._write_csv(data_dir / "NPA9997ts.csv", [["voterbaseid", "timeseries", "score"], ["A", "2", ""]])
        self._write_csv(data_dir / "NPA9997tsSB.csv", [["voterbaseid", "timeseries", "score"], ["A", "2", ""]])
        self._write_csv(data_dir / "NPA9997tsSB_append.csv", [["x"], ["1"]])
        os.utime(data_dir / "NPA9997ts.csv", (100, 100))
        os.utime(data_dir / "NPA9997tsSB.csv", (200, 200))
        os.utime(data_dir / "NPA9997tsSB_append.csv", (300, 300))
        sample = root / "Sample" / "sample.csv"
        self._write_csv(sample, [["voterbase_id", "csm"], ["A", "0.7"]])
        context = core.ProjectContext.from_values("NPA9997", root)

        data = core.default_append_data_file(context)
        self.assertEqual(data, data_dir / "NPA9997tsSB.csv")

        result = core.run_sample_append(context, data, sample, "score=csm")

        self.assertEqual(result.changed["score"], 1)
        self.assertEqual(core.remembered_append_columns(context), "score=csm")
        self.assertEqual(
            (data_dir / "NPA9997tsSB.csv").read_text(encoding="utf-8").splitlines()[1], "A,2,"
        )

    def test_prelim_qc_writes_report_under_job_qc(self) -> None:
        root = self._case_dir() / "NPA9996 Track"
        (root / "Job").mkdir(parents=True)
        (root / "Job" / "NPA9996.job").write_text(
            "[TABLES]\nTQ1^1\n OV,OI\n Q1. Test\n Yes^Q1(1)^NS\n Ghost^MISSING(1)^NS\n", encoding="utf-8"
        )
        self._write_csv(root / "Data" / "NPA9996.csv", [["q1"], ["1"]])
        context = core.ProjectContext.from_values("NPA9996", root)

        report_path, counts, inputs = core.run_prelim_qc(context)

        self.assertEqual(report_path.parent.parent, root / "Job" / "QC")
        self.assertEqual(counts.get("Critical"), 1)
        self.assertEqual(inputs.data_path.name, "NPA9996.csv")
        self.assertIn("prelim_qc", json.loads(context.manifest_path.read_text(encoding="utf-8"))["tools"])


if __name__ == "__main__":
    unittest.main()
