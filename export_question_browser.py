#!/usr/bin/env python3
"""Export a standalone Question Browser package with a SQLite snapshot."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "repository" / "questions.sqlite"
DEFAULT_OUT = ROOT / "dist" / "question_browser"
BROWSER_SOURCE = ROOT / "pipelines" / "catalogger" / "repository_dashboard_gui.py"


STANDALONE_APP = r'''#!/usr/bin/env python3
"""Standalone read-only Question Browser launcher."""

from __future__ import annotations

import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from pipelines.catalogger.repository_dashboard_gui import (  # noqa: E402
    RepositoryDashboardGUI,
    _configure_tcl_env,
    messagebox,
    tk,
    ttk,
)


class QuestionBrowserOnlyGUI(RepositoryDashboardGUI):
    """Use the platform Question Browser UI against a packaged SQLite DB."""

    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        self.root.title("Survey Question Browser")
        self.root.geometry("1500x900")
        self.repo_root_var.set(str(APP_DIR / "repository"))

        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)

        header = ttk.LabelFrame(outer, text="Question Database")
        header.pack(fill=tk.X, pady=(0, 6))

        self.browser_db_var = tk.StringVar(
            value=str(APP_DIR / "repository" / "questions.sqlite")
        )
        ttk.Label(header, text="Database").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        ttk.Entry(header, textvariable=self.browser_db_var, state="readonly", width=110).grid(
            row=0,
            column=1,
            sticky="we",
            padx=6,
            pady=6,
        )
        ttk.Button(header, text="Refresh Summary", command=self.refresh_question_summary).grid(
            row=0,
            column=2,
            sticky="w",
            padx=6,
            pady=6,
        )
        header.grid_columnconfigure(1, weight=1)

        questions_tab = ttk.Frame(outer, padding=4)
        questions_tab.pack(fill=tk.BOTH, expand=True)
        self._build_questions_tab(questions_tab)
        self.refresh_question_summary()

    def load_index(self) -> None:
        self.refresh_question_summary()

    def rebuild_question_index(self) -> None:
        messagebox.showinfo(
            "Question Browser",
            "This is a read-only exported database snapshot. "
            "Re-export from SurveyPlatform to refresh the question index.",
        )


def main() -> None:
    _configure_tcl_env()
    root = tk.Tk()
    QuestionBrowserOnlyGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
'''


LAUNCH_BAT = r'''@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 question_browser_standalone.py
) else (
    python question_browser_standalone.py
)
if errorlevel 1 pause
'''


def _sqlite_count(db_path: Path, sql: str) -> int:
    with sqlite3.connect(str(db_path)) as conn:
        return int(conn.execute(sql).fetchone()[0])


def _snapshot_sqlite(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    source_uri = f"file:{source.as_posix()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True) as src_conn:
        with sqlite3.connect(str(target)) as dst_conn:
            src_conn.backup(dst_conn)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_readme(path: Path, *, db_name: str, survey_count: int, question_count: int) -> None:
    _write_text(
        path,
        f"""# Survey Question Browser Export

This folder is a read-only snapshot of the SurveyPlatform Question Browser.

## Open

Double-click `Launch Question Browser.bat`, or run:

```bat
py -3 question_browser_standalone.py
```

## Included

- `repository/{db_name}`: SQLite question database snapshot
- `question_browser_standalone.py`: small launcher
- `pipelines/catalogger/repository_dashboard_gui.py`: Question Browser UI/query code

## Snapshot

- Surveys indexed: {survey_count}
- Questions indexed: {question_count}

To refresh this export, rerun `export_question_browser.py` from SurveyPlatform.
""",
    )


def export_question_browser(source_db: Path, out_dir: Path, *, overwrite: bool) -> Path:
    source_db = source_db.resolve()
    out_dir = out_dir.resolve()

    if not source_db.exists():
        raise FileNotFoundError(f"Question DB not found: {source_db}")
    if not BROWSER_SOURCE.exists():
        raise FileNotFoundError(f"Browser source not found: {BROWSER_SOURCE}")
    if out_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Output already exists; pass --overwrite: {out_dir}")
        shutil.rmtree(out_dir)

    repo_dir = out_dir / "repository"
    db_target = repo_dir / "questions.sqlite"
    _snapshot_sqlite(source_db, db_target)

    browser_target = out_dir / "pipelines" / "catalogger" / "repository_dashboard_gui.py"
    browser_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BROWSER_SOURCE, browser_target)
    _write_text(out_dir / "pipelines" / "__init__.py", "")
    _write_text(out_dir / "pipelines" / "catalogger" / "__init__.py", "")

    _write_text(out_dir / "question_browser_standalone.py", STANDALONE_APP)
    _write_text(out_dir / "Launch Question Browser.bat", LAUNCH_BAT)

    survey_count = _sqlite_count(db_target, "SELECT COUNT(*) FROM repo_questions_surveys")
    question_count = _sqlite_count(db_target, "SELECT COUNT(*) FROM repo_questions")
    _write_readme(
        out_dir / "README.md",
        db_name=db_target.name,
        survey_count=survey_count,
        question_count=question_count,
    )

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_db": str(source_db),
        "output_dir": str(out_dir),
        "survey_count": survey_count,
        "question_count": question_count,
        "files": [
            "Launch Question Browser.bat",
            "question_browser_standalone.py",
            "repository/questions.sqlite",
            "pipelines/catalogger/repository_dashboard_gui.py",
            "README.md",
        ],
    }
    _write_text(
        out_dir / "question_browser_export_manifest.json",
        json.dumps(manifest, indent=2),
    )
    return out_dir


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a standalone read-only Question Browser package."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Source questions.sqlite path.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output folder.")
    parser.add_argument("--overwrite", action="store_true", help="Replace output folder if it exists.")
    args = parser.parse_args()

    out_dir = export_question_browser(
        Path(args.db),
        Path(args.out),
        overwrite=bool(args.overwrite),
    )
    print(f"Question Browser export written to: {out_dir}")
    print(f"Launch: {out_dir / 'Launch Question Browser.bat'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
