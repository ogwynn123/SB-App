#!/usr/bin/env python3
"""Compare generated WinCross TABLES with the final hand-edited .job files.

Each corpus job folder (default: SurveyPlatform/corpus/wincross/NPA####) holds:

- the Final questionnaire DOCX and its same-stem PDF
- final.job: the job file the analyst finished in WinCross
- historical/*TABLES.autogen.txt: the Table Gen output used at the time (optional)
- source.json: where the files were copied from

The script runs the current pipeline into <job>/generated/, parses the [TABLES]
records from every source, aligns tables by ID, and writes a mismatch report.
It never writes to the archive.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLATFORM_ROOT = HERE.parent.parent
DEFAULT_CORPUS = PLATFORM_ROOT / "corpus" / "wincross"

TABLE_START_RE = re.compile(r"^(T[^\s^]+)\^")
SECTION_RE = re.compile(r"^\[([A-Z]+)\]\s*$")


@dataclass
class Row:
    label: str
    selector: str
    flags: str

    def key(self) -> tuple[str, str, str]:
        return (norm_text(self.label), norm_selector(self.selector), norm_flags(self.flags))


@dataclass
class Table:
    table_id: str
    banner: str = ""
    title_lines: list[str] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)

    @property
    def title(self) -> str:
        return " ".join(line.strip() for line in self.title_lines).strip()


def norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("’", "'").replace("‘", "'")).strip().casefold()


def norm_selector(text: str) -> str:
    return re.sub(r"\s+", "", text).upper()


def norm_flags(text: str) -> str:
    return ",".join(sorted(part.strip().upper() for part in text.split(",") if part.strip()))


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_tables(text: str) -> dict[str, Table]:
    """Parse [TABLES] records from a .job file or a TABLES text file."""
    tables: dict[str, Table] = {}
    has_sections = any(SECTION_RE.match(line) for line in text.splitlines())
    in_tables = not has_sections
    current: Table | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r\n")
        section = SECTION_RE.match(line)
        if section:
            in_tables = section.group(1) == "TABLES"
            current = None
            continue
        if not in_tables or line.startswith("```"):
            continue
        start = TABLE_START_RE.match(line)
        if start:
            table_id = start.group(1).upper()
            current = Table(table_id)
            suffix = 2
            while table_id in tables:
                table_id = f"{start.group(1).upper()}#{suffix}"
                suffix += 1
            tables[table_id] = current
            continue
        if current is None or not line.strip():
            continue
        body = line[1:] if line.startswith(" ") else line
        if not current.banner and not current.title_lines and not current.rows and "^" not in body:
            current.banner = body.strip()
        elif "^" in body:
            parts = body.split("^")
            current.rows.append(Row(parts[0], parts[1] if len(parts) > 1 else "", "^".join(parts[2:])))
        elif not current.rows:
            current.title_lines.append(body)
        else:
            current.rows.append(Row(body, "", ""))
    return tables


@dataclass
class TableDiff:
    table_id: str
    status: str
    banner_changed: bool = False
    title_changed: bool = False
    rows_same: int = 0
    rows_label_only: int = 0
    rows_selector: int = 0
    rows_flags: int = 0
    rows_added_in_final: int = 0
    rows_removed_from_generated: int = 0
    generated_title: str = ""
    final_title: str = ""
    generated_banner: str = ""
    final_banner: str = ""
    detail: list[str] = field(default_factory=list)

    @property
    def structural(self) -> bool:
        return self.status == "compared" and bool(
            self.banner_changed
            or self.rows_selector
            or self.rows_flags
            or self.rows_added_in_final
            or self.rows_removed_from_generated
        )


def compare_rows(generated: list[Row], final: list[Row], diff: TableDiff) -> None:
    gen_keys = [row.key() for row in generated]
    fin_keys = [row.key() for row in final]
    matcher = difflib.SequenceMatcher(a=gen_keys, b=fin_keys, autojunk=False)
    for op, a1, a2, b1, b2 in matcher.get_opcodes():
        if op == "equal":
            diff.rows_same += a2 - a1
            continue
        paired = min(a2 - a1, b2 - b1) if op == "replace" else 0
        for offset in range(paired):
            g, f = generated[a1 + offset], final[b1 + offset]
            gk, fk = g.key(), f.key()
            if gk[1] != fk[1]:
                diff.rows_selector += 1
            elif gk[2] != fk[2]:
                diff.rows_flags += 1
            else:
                diff.rows_label_only += 1
            diff.detail.append(f"~ {g.label}^{g.selector}^{g.flags}  ->  {f.label}^{f.selector}^{f.flags}")
        for row in generated[a1 + paired : a2]:
            diff.rows_removed_from_generated += 1
            diff.detail.append(f"- {row.label}^{row.selector}^{row.flags}")
        for row in final[b1 + paired : b2]:
            diff.rows_added_in_final += 1
            diff.detail.append(f"+ {row.label}^{row.selector}^{row.flags}")


def is_open_end(gen: Table, fin: Table) -> bool:
    # Open-end categories come from the OE coder's codelist, not from Table Gen.
    if norm_text(fin.title).startswith(("open end", "open-end")):
        return True
    return any(norm_selector(row.selector).startswith("NET") for row in fin.rows) and len(fin.rows) > len(gen.rows) + 3


def match_by_title(generated: dict[str, Table], final: dict[str, Table]) -> dict[str, str]:
    """Pair tables whose IDs differ (common for demographics) by normalized title."""
    unmatched_final: dict[str, list[str]] = {}
    for table_id, fin in final.items():
        if table_id not in generated:
            unmatched_final.setdefault(norm_text(title_shape(fin.title)), []).append(table_id)
    pairs: dict[str, str] = {}
    for table_id, gen in generated.items():
        if table_id in final:
            continue
        candidates = unmatched_final.get(norm_text(title_shape(gen.title)))
        if candidates:
            pairs[table_id] = candidates.pop(0)
    return pairs


def compare_tables(generated: dict[str, Table], final: dict[str, Table]) -> list[TableDiff]:
    diffs: list[TableDiff] = []
    title_pairs = match_by_title(generated, final)
    for table_id, gen in generated.items():
        fin = final.get(table_id) or final.get(title_pairs.get(table_id, ""))
        if fin is None:
            diffs.append(TableDiff(table_id, "generated_only", generated_title=gen.title, generated_banner=gen.banner))
            continue
        diff = TableDiff(
            table_id,
            "open_end" if is_open_end(gen, fin) else "compared",
            banner_changed=norm_selector(gen.banner) != norm_selector(fin.banner),
            title_changed=norm_text(gen.title) != norm_text(fin.title),
            generated_title=gen.title,
            final_title=fin.title,
            generated_banner=gen.banner,
            final_banner=fin.banner,
        )
        compare_rows(gen.rows, fin.rows, diff)
        diffs.append(diff)
    paired_final = set(title_pairs.values())
    for table_id, fin in final.items():
        if table_id not in generated and table_id not in paired_final:
            diffs.append(TableDiff(table_id, "final_only", final_title=fin.title, final_banner=fin.banner))
    return diffs


def table_family(table_id: str) -> str:
    match = re.match(r"T([A-Z]+)", table_id)
    prefix = match.group(1) if match else table_id
    if prefix.startswith("Q"):
        return "TQ"
    if "TREND" in prefix or prefix in {"T", "TT", "TTT"}:
        return "trend"
    return f"T{prefix}"


def find_questionnaire(job_dir: Path) -> tuple[Path, Path]:
    meta_path = job_dir / "source.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        docx = job_dir / meta["questionnaire"]
        return docx, docx.with_suffix(".pdf")
    docx = next(p for p in sorted(job_dir.glob("*.docx")) if not p.name.startswith("~$"))
    return docx, docx.with_suffix(".pdf")


def generate(job_dir: Path, *, regenerate: bool) -> Path:
    sys.path.insert(0, str(HERE))
    import survey_pipeline  # noqa: E402

    docx, pdf = find_questionnaire(job_dir)
    out_dir = job_dir / "generated"
    stem = job_dir.name
    tables_out = out_dir / f"{stem}TABLES.autogen.txt"
    if tables_out.exists() and not regenerate:
        return tables_out
    out_dir.mkdir(exist_ok=True)
    log: list[str] = []
    survey_pipeline.run_one(
        docx=docx,
        pdf=pdf if pdf.exists() else None,
        raw_out=out_dir / f"{stem}RAW.txt",
        json_out=out_dir / f"{stem}JSON.json",
        tables_out=tables_out,
        banners_out=out_dir / f"{stem}BANNERS.autogen.txt",
        py_exe=sys.executable,
        skip_cover=True,
        on_message=log.append,
    )
    (out_dir / "pipeline.log").write_text("\n".join(log), encoding="utf-8")
    return tables_out


def summarize(diffs: list[TableDiff]) -> dict[str, int]:
    compared = [d for d in diffs if d.status == "compared"]
    return {
        "compared": len(compared),
        "exact": sum(1 for d in compared if not d.structural and not d.title_changed and not d.rows_label_only),
        "title_or_label_only": sum(
            1 for d in compared if not d.structural and (d.title_changed or d.rows_label_only)
        ),
        "structural": sum(1 for d in compared if d.structural),
        "banner_changed": sum(1 for d in compared if d.banner_changed),
        "open_end": sum(1 for d in diffs if d.status == "open_end"),
        "generated_only": sum(1 for d in diffs if d.status == "generated_only"),
        "final_only": sum(1 for d in diffs if d.status == "final_only"),
        "rows_same": sum(d.rows_same for d in compared),
        "rows_label_only": sum(d.rows_label_only for d in compared),
        "rows_selector": sum(d.rows_selector for d in compared),
        "rows_flags": sum(d.rows_flags for d in compared),
        "rows_added_in_final": sum(d.rows_added_in_final for d in compared),
        "rows_removed_from_generated": sum(d.rows_removed_from_generated for d in compared),
    }


class Patterns:
    """Recurring edits across jobs, used to spot missing generator rules."""

    def __init__(self) -> None:
        self.banner: Counter[str] = Counter()
        self.flags: Counter[str] = Counter()
        self.added: Counter[str] = Counter()
        self.removed: Counter[str] = Counter()
        self.labels: Counter[str] = Counter()
        self.titles: Counter[str] = Counter()
        self.final_only: Counter[str] = Counter()
        self.generated_only: Counter[str] = Counter()
        self.jobs: dict[str, set[str]] = {}

    def _add(self, counter: Counter[str], key: str, job: str) -> None:
        counter[key] += 1
        self.jobs.setdefault(f"{id(counter)}:{key}", set()).add(job)

    def job_count(self, counter: Counter[str], key: str) -> int:
        return len(self.jobs.get(f"{id(counter)}:{key}", set()))

    def update(self, job: str, diffs: list[TableDiff]) -> None:
        for diff in diffs:
            if diff.status == "final_only":
                self._add(self.final_only, title_shape(diff.final_title) or diff.table_id, job)
            elif diff.status == "generated_only":
                self._add(self.generated_only, title_shape(diff.generated_title) or diff.table_id, job)
            if diff.status != "compared":
                continue
            if diff.banner_changed:
                self._add(self.banner, f"{diff.generated_banner}  ->  {diff.final_banner}", job)
            if diff.title_changed:
                self._add(self.titles, title_change_kind(diff.generated_title, diff.final_title), job)
            for line in diff.detail:
                kind, _, rest = line.partition(" ")
                if kind == "+":
                    self._add(self.added, row_shape(rest), job)
                elif kind == "-":
                    self._add(self.removed, row_shape(rest), job)
                elif kind == "~":
                    before, _, after = rest.partition("  ->  ")
                    b, a = before.split("^"), after.split("^")
                    if norm_selector(b[1]) == norm_selector(a[1]) and norm_flags(b[2]) != norm_flags(a[2]):
                        self._add(self.flags, f"{norm_flags(b[2])} -> {norm_flags(a[2])}", job)
                    elif norm_selector(b[1]) == norm_selector(a[1]):
                        self._add(self.labels, f"{b[0].strip()} -> {a[0].strip()}", job)


def row_shape(row: str) -> str:
    label, _, rest = row.partition("^")
    flags = rest.partition("^")[2]
    label = re.sub(r"\d+", "#", label.strip()) or "(blank)"
    return f"{label} [{norm_flags(flags)}]"


def title_shape(title: str) -> str:
    title = re.sub(r"^Q\d+[a-z]?\.\s*", "", title.strip())
    return re.sub(r"\s+", " ", title)[:70]


def title_change_kind(generated: str, final: str) -> str:
    g, f = generated.strip(), final.strip()
    if re.sub(r"\s*\[[A-Z][A-Z'\- ]+\]", "", g) == f:
        return "pronunciation guide left in generated title"
    if f.lower().startswith(re.match(r"q\d+[a-z]?\.\s*", g.lower()).group(0) + "open end") if re.match(r"q\d+[a-z]?\.", g.lower()) else False:
        return "final adds 'Open End -' prefix"
    if len(f) < len(g) * 0.6:
        return "final shortens long question text to a label"
    if norm_text(g) == norm_text(f):
        return "case/spacing only"
    return "other wording change"


def top(counter: Counter[str], patterns: Patterns, limit: int = 15) -> list[str]:
    return [
        f"| {count} | {patterns.job_count(counter, key)} | `{key.replace('|', '/')}` |"
        for key, count in counter.most_common(limit)
    ]


def pct(part: int, whole: int) -> str:
    return f"{(100 * part / whole):.0f}%" if whole else "-"


def write_job_report(path: Path, job: str, label: str, diffs: list[TableDiff]) -> None:
    lines = [f"# {job}: {label}", ""]
    for diff in diffs:
        if diff.status == "generated_only":
            lines.append(f"## {diff.table_id}: only in generated\n\n{diff.generated_title}\n")
        elif diff.status == "final_only":
            lines.append(f"## {diff.table_id}: only in final ({table_family(diff.table_id)})\n\n{diff.final_title}\n")
        elif diff.status == "open_end":
            lines.append(f"## {diff.table_id}: open end (codes from OE coder)\n\n{diff.final_title}\n")
        elif diff.structural or diff.title_changed or diff.rows_label_only:
            lines.append(f"## {diff.table_id}")
            if diff.title_changed:
                lines.append(f"- title: `{diff.generated_title}` -> `{diff.final_title}`")
            if diff.banner_changed:
                lines.append(f"- banner: `{diff.generated_banner}` -> `{diff.final_banner}`")
            if diff.detail:
                lines.append("")
                lines.append("```text")
                lines.extend(diff.detail)
                lines.append("```")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--job", action="append", help="Limit to these job folders, e.g. NPA3873.")
    parser.add_argument("--regenerate", action="store_true", help="Rerun Table Gen even if generated output exists.")
    parser.add_argument("--out", type=Path, help="Report folder (default: <corpus>/../reports/<timestamp>).")
    args = parser.parse_args()

    job_dirs = sorted(p for p in args.corpus.iterdir() if p.is_dir() and (p / "final.job").exists())
    if args.job:
        wanted = {name.upper() for name in args.job}
        job_dirs = [p for p in job_dirs if p.name.upper() in wanted]
    out_dir = args.out or args.corpus.parent / "reports" / datetime.now().strftime("%Y%m%d_%H%M%S")
    (out_dir / "jobs").mkdir(parents=True, exist_ok=True)

    csv_rows: list[dict[str, object]] = []
    summary_rows: list[tuple[str, str, dict[str, int]]] = []
    final_only_families: Counter[str] = Counter()
    patterns = Patterns()
    failures: list[str] = []
    for job_dir in job_dirs:
        job = job_dir.name
        final = parse_tables(read_text(job_dir / "final.job"))
        sources: list[tuple[str, Path]] = []
        try:
            sources.append(("current", generate(job_dir, regenerate=args.regenerate)))
        except BaseException as exc:  # pipeline steps raise SystemExit on failure
            failures.append(f"{job}: {exc}")
        sources.extend(("historical", p) for p in sorted((job_dir / "historical").glob("*TABLES.autogen.txt")))
        for label, tables_path in sources:
            diffs = compare_tables(parse_tables(read_text(tables_path)), final)
            summary_rows.append((job, label, summarize(diffs)))
            if label == "current":
                patterns.update(job, diffs)
            write_job_report(out_dir / "jobs" / f"{job}_{label}.md", job, label, diffs)
            for diff in diffs:
                if label == "current" and diff.status == "final_only":
                    final_only_families[table_family(diff.table_id)] += 1
                csv_rows.append(
                    {
                        "job": job,
                        "source": label,
                        "table_id": diff.table_id,
                        "status": diff.status,
                        "structural": diff.structural,
                        "title_changed": diff.title_changed,
                        "banner_changed": diff.banner_changed,
                        "rows_same": diff.rows_same,
                        "rows_label_only": diff.rows_label_only,
                        "rows_selector": diff.rows_selector,
                        "rows_flags": diff.rows_flags,
                        "rows_added_in_final": diff.rows_added_in_final,
                        "rows_removed_from_generated": diff.rows_removed_from_generated,
                        "generated_title": diff.generated_title,
                        "final_title": diff.final_title,
                        "generated_banner": diff.generated_banner,
                        "final_banner": diff.final_banner,
                    }
                )

    with (out_dir / "tables.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(csv_rows[0].keys()) if csv_rows else ["job"])
        writer.writeheader()
        writer.writerows(csv_rows)

    lines = [
        "# Table Gen vs final .job",
        "",
        "Tables are aligned by table ID. A table is *structural* when its banner,",
        "a selector, flags, or the set of rows changed. Title and row-label edits are",
        "counted separately because analysts routinely shorten them.",
        "",
        "Open-end tables are listed separately: their coded categories come from the",
        "OE coder, not Table Gen.",
        "",
        "| Job | Source | Compared | Exact | Title/label only | Structural | Banner changed | Open end | Only generated | Only final | Rows same | Selector | Flags | Rows added in final | Rows removed |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    totals: dict[str, Counter[str]] = {"current": Counter(), "historical": Counter()}
    for job, label, s in summary_rows:
        totals[label].update(s)
        lines.append(
            f"| {job} | {label} | {s['compared']} | {s['exact']} | {s['title_or_label_only']} | {s['structural']} | "
            f"{s['banner_changed']} | {s['open_end']} | {s['generated_only']} | {s['final_only']} | {s['rows_same']} | "
            f"{s['rows_selector']} | {s['rows_flags']} | {s['rows_added_in_final']} | {s['rows_removed_from_generated']} |"
        )
    lines.append("")
    for label, t in totals.items():
        if not t:
            continue
        lines.append(
            f"**{label} total:** {t['compared']} tables compared; exact {t['exact']} ({pct(t['exact'], t['compared'])}), "
            f"title/label only {t['title_or_label_only']}, structural {t['structural']} ({pct(t['structural'], t['compared'])}); "
            f"{t['final_only']} tables only in final, {t['generated_only']} only in generated."
        )
        lines.append("")
    if final_only_families:
        lines.append("Tables only in final (current run), by ID family: " + ", ".join(
            f"{family} {count}" for family, count in final_only_families.most_common()
        ))
        lines.append("")
    lines.append("## Recurring patterns (current run)")
    lines.append("")
    lines.append("Each table lists occurrences, then the number of jobs they appear in.")
    for heading, counter in (
        ("Banner changes", patterns.banner),
        ("Title changes by kind", patterns.titles),
        ("Flag changes on otherwise identical rows", patterns.flags),
        ("Row label edits", patterns.labels),
        ("Rows added in final", patterns.added),
        ("Rows removed from generated", patterns.removed),
        ("Tables only in final", patterns.final_only),
        ("Tables only in generated", patterns.generated_only),
    ):
        if not counter:
            continue
        lines.extend(["", f"### {heading}", "", "| Count | Jobs | Pattern |", "|---:|---:|---|"])
        lines.extend(top(counter, patterns))
    lines.append("")
    if failures:
        lines.append("## Pipeline failures")
        lines.extend(f"- {failure}" for failure in failures)
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report: {out_dir / 'summary.md'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
