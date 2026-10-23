#!/usr/bin/env python3
"""Build a local evaluation set of analyst-coded open-end questions.

For each job in the git-ignored Table Gen corpus (corpus/wincross/NPA####), read
the project's newest data file from the archive (read-only) and, for every open-end
question answered in the latest wave, save:

- each verbatim with the analyst's final codes (cN_1..3),
- the code labels from the final .job (rows such as "Running for office^c14_1 S3(8)"),
- the question title from the .job table.

Output: corpus/oe/<NPA>_<question>.json. Client data stays in the ignored corpus.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLATFORM = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PLATFORM / "pipelines" / "table_merger"))

import oe_record_coder_core as oe  # noqa: E402
from carryover_tables import read_job_text  # noqa: E402

ARCHIVE = Path(r"C:\Users\normi\OneDrive - Normington Petts\NPA Archive - Documents")
CORPUS = PLATFORM / "corpus"
TABLE_START_RE = re.compile(r"^(T[^\s^]+)\^")
SECTION_RE = re.compile(r"^\[([A-Z]+)\]\s*$")
BANNER_RE = re.compile(r"[A-Z0-9%]+(?:,[A-Z0-9%]+)+")


def question_text(job_dir: Path, question: str) -> str:
    """Full question wording from Table Gen's questionnaire JSON (qid such as 14 or 14a)."""
    qid = re.sub(r"(?i)^q|oe$", "", question).lower()
    for path in sorted((job_dir / "generated").glob("*JSON.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for element in data.get("elements", []):
            if str(element.get("qid", "")).lower() == qid or str(element.get("qnum", "")).lower() == qid:
                return str(element.get("text") or "")
    return ""


def newest_data_file(project: Path, code: str) -> Path | None:
    data_dir = project / "Data"
    name_re = re.compile(rf"^{code}[A-Za-z0-9_]*$", re.IGNORECASE)
    hits = [p for p in data_dir.glob(f"{code}*.csv") if name_re.match(p.stem)] if data_dir.is_dir() else []
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


def job_code_labels(job_text: str, companion: str) -> tuple[str, dict[str, str]]:
    """Title and code labels for the table that selects on `companion` (e.g. c14_1)."""
    title = ""
    labels: dict[str, str] = {}
    section = ""
    table_title = ""
    table_lines: list[str] = []
    tables: list[tuple[str, list[str]]] = []
    for line in job_text.splitlines():
        header = SECTION_RE.match(line)
        if header:
            section = header.group(1)
            continue
        if section != "TABLES":
            continue
        if TABLE_START_RE.match(line):
            if table_lines:
                tables.append((table_title, table_lines))
            table_title, table_lines = "", []
            continue
        if "^" not in line:
            stripped = line.strip()
            if BANNER_RE.fullmatch(stripped):
                continue
            if stripped and not table_title and not table_lines:
                table_title = stripped
            continue
        table_lines.append(line)
    if table_lines:
        tables.append((table_title, table_lines))
    var_re = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(companion)}\s*(?:[Ss]\d+)?\s*\(", re.IGNORECASE)
    for table_title, lines in tables:
        if not any(var_re.search(line) for line in lines):
            continue
        title = table_title
        active = False
        for line in lines:
            parts = line.split("^")
            if len(parts) < 2:
                continue
            label, selector = parts[0].strip(), parts[1].strip()
            if var_re.search(selector):
                active = True
            elif re.match(r"^[A-Za-z_]", selector) and not selector.upper().startswith(("NET", "CALC")):
                active = False
            if not active or selector.upper().startswith(("NET", "CALC")) or "RH" in parts[-1].upper().split(","):
                continue
            match = re.search(r"\(([^()]*)\)", selector)
            if not match:
                continue
            codes = [c.strip() for c in match.group(1).split(",") if c.strip()]
            if len(codes) == 1 and re.fullmatch(r"\d+", codes[0]) and label:
                labels.setdefault(codes[0], label)
        break
    return title, labels


def build() -> list[Path]:
    out_dir = CORPUS / "oe"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for job_dir in sorted((CORPUS / "wincross").iterdir()):
        source = json.loads((job_dir / "source.json").read_text(encoding="utf-8"))
        project = ARCHIVE / source["project"]
        data_path = newest_data_file(project, job_dir.name)
        if data_path is None:
            print(f"{job_dir.name}: no data file")
            continue
        with data_path.open(encoding="utf-8-sig", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames or []
            rows = list(reader)
        ts_col = next((h for h in headers if h.casefold() == "timeseries"), None)
        waves = [r.get(ts_col, "").strip() for r in rows] if ts_col else []
        numeric = [int(float(w)) for w in waves if re.fullmatch(r"\d+(?:\.0+)?", w)]
        latest = max(numeric) if numeric else None
        job_text = read_job_text(job_dir / "final.job")
        for spec in oe.detect_open_end_questions(headers):
            if re.match(r"^\d{4}_", spec.name):  # earlier waves' questions carried in the ts file
                continue
            items = []
            for row in rows:
                if latest is not None and ts_col and row.get(ts_col, "").strip() not in {str(latest), f"{latest}.0"}:
                    continue
                text = oe.clean_verbatim(row.get(spec.text_column))
                codes = [oe.normalize_code(row.get(c)) for c in spec.companion_columns]
                codes = [c for c in codes if c]
                if text and codes:
                    items.append({"text": text, "codes": codes})
            if len(items) < 50:
                continue
            title, labels = job_code_labels(job_text, spec.companion_columns[0])
            counts = Counter(c for item in items for c in item["codes"])
            record = {
                "job": job_dir.name,
                "question": spec.name,
                "title": title,
                "question_text": question_text(job_dir, spec.name),
                "data_file": data_path.name,
                "wave": latest,
                "labels": labels,
                "code_counts": dict(counts.most_common()),
                "items": items,
            }
            path = out_dir / f"{job_dir.name}_{spec.name}.json"
            path.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
            written.append(path)
            print(f"{job_dir.name} {spec.name}: {len(items)} responses, {len(counts)} codes, "
                  f"{len(labels)} labels | {title[:60]}")
    return written


if __name__ == "__main__":
    build()
