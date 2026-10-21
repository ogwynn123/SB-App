#!/usr/bin/env python3
"""Run every SurveyPlatform regression suite and print one summary."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / ".tmp_tests"
COVERAGE_RC = BASE_DIR / ".coveragerc"


@dataclass(frozen=True)
class Suite:
    name: str
    cwd: str
    args: tuple[str, ...]


SUITES: tuple[Suite, ...] = (
    Suite("wincross", "pipelines/wincross_table_generator", (
        "-m", "unittest",
        "test_wincrossTableCompile.py", "test_question_attributes.py", "test_surveyConvertJSON.py",
        "test_wincrossBannerCompile.py", "test_wincrossCoverCompile.py", "test_survey_unformatter.py",
        "test_survey_pipeline_gui.py", "test_golden_compare.py",
    )),
    Suite("trend", "pipelines/trend_table_updater", ("-m", "unittest", "test_trend_table_updater_core.py")),
    Suite("merge", "pipelines/table_merger", ("-m", "unittest", "test_sheet_merge_core.py", "test_sheetMerging_gui.py")),
    Suite("auto_results", "pipelines/auto_results", ("-m", "unittest", "test_autoResults_alignment.py")),
    Suite("quota", "pipelines/sample_quota_checker", (
        "-m", "unittest", "test_sample_quota_checker.py", "test_quota_workbook_scraper.py",
    )),
    Suite("oe", "pipelines/open_end_coder", (
        "-m", "unittest", "test_oe_codebook_gui.py", "test_oe_record_coder_core.py", "test_oe_record_coder_gui.py",
    )),
    Suite("tomas", "pipelines/thomas_in_a_box", (
        "-m", "unittest", "test_tomas_docx_rebuilder.py", "test_tomas_pipeline.py", "test_tomas_translate.py",
    )),
    Suite("catalog", "pipelines/catalogger", (
        "-m", "unittest", "test_repository_dashboard_data_intake.py", "test_survey_catalog.py",
    )),
    Suite("channel", "pipelines/questionnaire_channel_builder", ("-m", "unittest", "test_channel_builder.py")),
    Suite("writer", "pipelines/survey_writer", ("-m", "unittest", "test_survey_writer_app.py")),
    Suite("browser", ".", ("-m", "unittest", "local_browser_app.test_local_browser_app")),
    Suite("launcher", ".", ("-m", "unittest", "test_survey_ops_lite.py", "test_acceptance_smoke.py", "test_packaged_apps.py")),
)
ACCEPTANCE = Suite("acceptance", ".", ("acceptance_smoke.py",))

RAN_RE = re.compile(r"^Ran (\d+) tests? in", re.MULTILINE)


def run_suite(
    suite: Suite, env: dict[str, str], verbose: bool, coverage: bool = False
) -> tuple[bool, int | None, float, str]:
    started = time.perf_counter()
    prefix = []
    if coverage:
        prefix = ["-m", "coverage", "run", "--parallel-mode", f"--rcfile={COVERAGE_RC}", f"--source={BASE_DIR}"]
    proc = subprocess.run(
        [sys.executable, *prefix, *suite.args],
        cwd=BASE_DIR / suite.cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.perf_counter() - started
    output = proc.stdout + proc.stderr
    match = RAN_RE.search(output)
    count = int(match.group(1)) if match else None
    if verbose:
        print(output)
    return proc.returncode == 0, count, elapsed, output


def main() -> int:
    names = [suite.name for suite in SUITES]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suites", nargs="*", help=f"Suites to run (default: all). Choices: {', '.join(names)}")
    parser.add_argument("--acceptance", action="store_true", help="Also run the synthetic end-to-end acceptance smoke test.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print each suite's full output.")
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Measure line coverage (needs `py -3 -m pip install coverage`) and write an HTML report.",
    )
    args = parser.parse_args()

    unknown = [name for name in args.suites if name not in names]
    if unknown:
        parser.error(f"unknown suite(s): {', '.join(unknown)}")
    selected = [suite for suite in SUITES if not args.suites or suite.name in args.suites]
    if args.acceptance:
        selected.append(ACCEPTANCE)

    # A repo-local temp folder avoids Windows sandbox PermissionErrors under
    # freshly created system temp directories.
    TEMP_DIR.mkdir(exist_ok=True)
    env = dict(os.environ, TEMP=str(TEMP_DIR), TMP=str(TEMP_DIR), PYTHONIOENCODING="utf-8")

    if args.coverage:
        env["COVERAGE_FILE"] = str(TEMP_DIR / ".coverage")
        for stale in TEMP_DIR.glob(".coverage*"):
            stale.unlink()

    failures: list[tuple[Suite, str]] = []
    total = 0
    for suite in selected:
        print(f"{suite.name:<13}", end="", flush=True)
        ok, count, elapsed, output = run_suite(suite, env, args.verbose, args.coverage)
        total += count or 0
        label = f"{count} tests" if count is not None else "done"
        print(f"{'PASS' if ok else 'FAIL'}  {label:<10} {elapsed:5.1f}s")
        if not ok:
            failures.append((suite, output))

    for suite, output in failures:
        print(f"\n===== {suite.name} output ({suite.cwd}) =====")
        print(output.rstrip())

    print(f"\n{len(selected) - len(failures)}/{len(selected)} suites passed, {total} tests run.")
    if args.coverage:
        sys.stdout.flush()
        report_dir = TEMP_DIR / "coverage_html"
        for command in (["combine", "-q"], ["report", "--sort=cover"], ["html", "-q", "-d", str(report_dir)]):
            subprocess.run(
                [sys.executable, "-m", "coverage", *command, f"--rcfile={COVERAGE_RC}"],
                cwd=BASE_DIR,
                env=env,
            )
        print(f"\nHTML coverage report: {report_dir / 'index.html'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
