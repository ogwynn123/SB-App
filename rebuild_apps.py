#!/usr/bin/env python3
"""Rebuild packaged specialist EXEs whose source is newer than the EXE.

Desktop shortcuts and the EXE-first launchers open the EXEs, so a source fix
does nothing for them until the EXE is rebuilt. For each app rebuilt this:

1. refuses to run while that app is open (Windows locks the EXE),
2. copies the current EXEs to .tmp_archive/exe_backups/<timestamp>/<app>/,
3. runs the app's own build script, logging to .tmp_tests/rebuild_logs/,
4. starts the new EXE, checks it stays up, and closes it again.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from packaged_apps import APPS, APPS_BY_KEY, BASE_DIR, PackagedApp, freshness

BACKUP_ROOT = BASE_DIR / ".tmp_archive" / "exe_backups"
LOG_ROOT = BASE_DIR / ".tmp_tests" / "rebuild_logs"


def running_exes(app: PackagedApp) -> list[str]:
    result = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True)
    names = {name.casefold() for name in app.exes}
    return sorted({line.split('","')[0].strip('"') for line in result.stdout.splitlines() if line.split('","')[0].strip('"').casefold() in names})


def backup(app: PackagedApp, stamp: str) -> Path:
    dest = BACKUP_ROOT / stamp / app.key
    dest.mkdir(parents=True, exist_ok=True)
    for exe in app.exe_paths:
        if exe.exists():
            shutil.copy2(exe, dest / exe.name)
    return dest


def build(app: PackagedApp, stamp: str) -> tuple[bool, Path]:
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = LOG_ROOT / f"{stamp}_{app.key}.log"
    started = time.time()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        proc = subprocess.run(
            ["cmd", "/c", str(app.build_path)],
            cwd=app.folder,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    rebuilt = all(exe.exists() and exe.stat().st_mtime >= started - 1 for exe in app.exe_paths)
    return proc.returncode == 0 and rebuilt, log_path


def launch_check(app: PackagedApp, wait_seconds: float) -> str:
    from acceptance_smoke import _stop_process_tree

    gui_exe = app.exe_paths[-1]
    process = subprocess.Popen([str(gui_exe)], cwd=gui_exe.parent)
    try:
        time.sleep(wait_seconds)
        if process.poll() is not None:
            return f"exited during startup with code {process.returncode}"
    finally:
        remaining = _stop_process_tree(process)
    if remaining:
        return f"left running after close (PID {', '.join(map(str, remaining))})"
    return ""


def print_status() -> list[PackagedApp]:
    stale: list[PackagedApp] = []
    for app in APPS:
        state = freshness(app)
        detail = ""
        if state.status == "stale" and state.newest_source is not None:
            detail = f"  (newer source: {state.newest_source.relative_to(BASE_DIR)})"
        manual = "" if app.auto_rebuild else "  [rebuilt only when named]"
        print(f"{app.key:<13} {app.label:<22} {state.status}{detail}{manual}")
        if state.status != "fresh" and app.auto_rebuild:
            stale.append(app)
    return stale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("apps", nargs="*", help=f"Apps to rebuild even if fresh. Choices: {', '.join(APPS_BY_KEY)}")
    parser.add_argument("--list", action="store_true", help="Only show which EXEs are stale.")
    parser.add_argument("--wait", type=float, default=4.0, help="Seconds each new EXE must stay running.")
    args = parser.parse_args()

    unknown = [key for key in args.apps if key not in APPS_BY_KEY]
    if unknown:
        parser.error(f"unknown app(s): {', '.join(unknown)}")

    stale = print_status()
    targets = [APPS_BY_KEY[key] for key in args.apps] if args.apps else stale
    if args.list:
        return 0
    if not targets:
        print("\nAll packaged EXEs are up to date.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    failures: list[str] = []
    for app in targets:
        print(f"\n== {app.label}")
        open_exes = running_exes(app)
        if open_exes:
            failures.append(f"{app.label}: close {', '.join(open_exes)} and run again")
            print(f"   skipped: {open_exes[0]} is open")
            continue
        print(f"   backup: {backup(app, stamp).relative_to(BASE_DIR)}")
        ok, log_path = build(app, stamp)
        if not ok:
            failures.append(f"{app.label}: build failed, see {log_path.relative_to(BASE_DIR)}")
            print("   build: FAILED")
            continue
        print(f"   build: ok ({log_path.relative_to(BASE_DIR)})")
        problem = launch_check(app, args.wait)
        if problem:
            failures.append(f"{app.label}: new EXE {problem}")
            print(f"   launch: FAILED ({problem})")
        else:
            print("   launch: ok (started and closed)")

    if failures:
        print("\nProblems:")
        for failure in failures:
            print(f" - {failure}")
        print(f"Previous EXEs are kept under {BACKUP_ROOT.relative_to(BASE_DIR)}\\{stamp}.")
        return 1
    print(f"\nRebuilt {len(targets)} app(s). Previous EXEs: {BACKUP_ROOT.relative_to(BASE_DIR)}\\{stamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
