#!/usr/bin/env python3
"""Close matches for sample (voter-file) columns whose names differ between exports.

Sample vendors rename columns between waves and export formats:
"StartDateTime" / "Starttime", "partisanscore" / "tsmartpartisanscore",
"ct_w_overall_v2" / "calltimewindoveralv2", "zip" / "vfregcasszip". Exact and
fuzzy name matching miss these, so the merge's auto-fill adds a close-match
step for non-question columns:

1. Names are compared after removing vendor prefixes (tsmart, ts, vf, vfreg,
   vfregcass, voterbase, reg, ...) and evening out abbreviations
   (datetime -> time, call-time window / ct_w, phone usage / pu_u, scr/score,
   dist/district, lvl/level, weekday spellings).
2. Names listed together in merge_column_aliases.txt (editable) are the same
   column, for abbreviations no rule can work out ("pgentntscore" /
   "presidglturnoutscore").
3. With the data at hand, a candidate must hold the same kind of values
   (real ages are not the 1-4 codes of "hage"; "Male/Female" is not "1/2").
4. Of several candidates (the vendor's names changed between earlier waves),
   the one with values in the trend file's most recent wave wins.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

def _alias_file() -> Path:
    """The editable list in pipelines/table_merger; inside the packaged EXE
    (dist/sheet_merge_gui.exe) that same source copy if present, else the bundled one."""
    bundled = Path(__file__).resolve().with_name("merge_column_aliases.txt")
    if getattr(sys, "frozen", False):
        source = Path(sys.executable).resolve().parent.parent / "merge_column_aliases.txt"
        if source.exists():
            return source
    return bundled


ALIAS_FILE = _alias_file()

# Removed from the start of earlier waves' (secondary) names, longest first, repeatedly.
SECONDARY_PREFIXES = ("vfregcass", "vfreg", "voterbase", "tsmart", "voter", "vf", "ts", "reg", "base", "vb")
# This wave's short names only carry "ts_" (ts_roloff_score, ts_colgradscr).
PRIMARY_PREFIXES = ("ts",)
WEEKDAYS = {
    "sunday": "sun", "sun": "sun", "monday": "mon", "mon": "mon", "tuesday": "tue", "tues": "tue", "tue": "tue",
    "wednesday": "wed", "wed": "wed", "wen": "wed", "thursday": "thu", "thurs": "thu", "thur": "thu", "thu": "thu",
    "friday": "fri", "fri": "fri", "saturday": "sat", "sat": "sat",
}
_WEEKDAY_RE = re.compile(r"^ctw(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")")
FUZZY_CLOSE = 92  # similarity of the evened-out names when no rule or alias makes them equal
_DATE_RE = re.compile(r"^\d{1,4}[-/.](\d{1,2}|[a-z]{3})[-/.]\d{1,4}|^\d{1,2}:\d{2}(:\d{2})?$", re.IGNORECASE)


def canonical(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).casefold())


def close_name(name: str, *, secondary: bool) -> str:
    """The name with vendor prefixes and abbreviations evened out."""
    text = canonical(name)
    prefixes = SECONDARY_PREFIXES if secondary else PRIMARY_PREFIXES
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if text.startswith(prefix) and len(text) - len(prefix) >= 2:
                text = text[len(prefix):]
                changed = True
                break
    text = text.replace("datetime", "time")
    text = re.sub(r"^(calltimewindow|calltimewind|ctw|window)", "ctw", text)
    text = _WEEKDAY_RE.sub(lambda m: "ctw" + WEEKDAYS[m.group(1)], text)
    text = re.sub(r"^ctwoveral(?!l)", "ctwoverall", text)
    text = re.sub(r"^(phoneusage|puu)", "pu", text)
    text = re.sub(r"(score|scr)(?=v?\d*$)", "score", text)
    text = re.sub(r"(district|dist)", "dist", text)
    text = re.sub(r"(level|lvl)", "lvl", text)
    return text


def _alias_lines(path: Path | str | None):
    file = Path(path) if path else ALIAS_FILE
    if not file.exists():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            yield line


def _names(text: str) -> set[str]:
    return {canonical(part) for part in text.split("|") if canonical(part)}


def load_aliases(path: Path | str | None = None) -> list[set[str]]:
    """Groups of names (canonical) that are the same column; one group per line, | between names."""
    groups = []
    for line in _alias_lines(path):
        if "=" in line:
            continue
        group = _names(line)
        if len(group) > 1:
            groups.append(group)
    return groups


def load_directed_aliases(path: Path | str | None = None) -> list[tuple[set[str], set[str]]]:
    """Lines "this wave's names = earlier waves' names" ("gendergrp = sgroup"): the
    earlier column goes to this wave's column even when this wave also has a
    column of the earlier name that means something else."""
    rules = []
    for line in _alias_lines(path):
        if "=" not in line:
            continue
        left, right = line.split("=", 1)
        if _names(left) and _names(right):
            rules.append((_names(left), _names(right)))
    return rules


# --- Values ---------------------------------------------------------------------

@dataclass
class Profile:
    kind: str  # empty | number | date | text
    values: frozenset[str] = frozenset()
    low: float = 0.0
    high: float = 0.0


def profile(series) -> Profile:
    """What kind of values a column holds (from up to 2,000 non-blank values)."""
    import pandas as pd

    values = series.dropna().astype(str).str.strip()
    values = values[values != ""].head(2000)
    if values.empty:
        return Profile("empty")
    numbers = pd.to_numeric(values, errors="coerce")
    if numbers.notna().mean() >= 0.95:
        return Profile("number", frozenset(values.unique()[:200]), float(numbers.min()), float(numbers.max()))
    if values.map(lambda v: bool(_DATE_RE.match(v))).mean() >= 0.9:
        return Profile("date")
    return Profile("text", frozenset(v.casefold() for v in values.unique()[:200]))


def compatible(a: Profile, b: Profile) -> bool:
    """Could these be the same column? Only clearly different kinds of values say no:
    real ages against 1-4 codes, "Male/Female" against 1/2, "W/B/H" against codes.
    Different categories of the same kind are fine (another district's counties).
    Unknown (empty) counts as yes."""
    if a.kind == "empty" or b.kind == "empty":
        return True
    kinds = {a.kind, b.kind}
    if kinds in ({"date"}, {"date", "text"}):
        # "20-OCT-2026 15:38:49" may read as text; a time on one side and a timestamp on the other is fine.
        return True
    if kinds == {"number"}:
        return min(a.high, b.high) >= max(a.low, b.low)  # the value ranges meet
    if kinds == {"number", "text"}:
        return bool({v.casefold() for v in a.values} & {v.casefold() for v in b.values})
    if kinds == {"text"}:
        return True
    return False  # a date against numbers


@dataclass
class ValueCheck:
    """Lazily profiles columns of this wave's (primary) and the trend file's (secondary) data."""
    primary_df: object = None
    secondary_df: object = None
    secondary_timeseries: str | None = None
    _cache: dict = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.primary_df is not None and self.secondary_df is not None

    def _profile(self, side: str, column: str) -> Profile:
        key = (side, column)
        if key not in self._cache:
            df = self.primary_df if side == "p" else self.secondary_df
            self._cache[key] = profile(df[column]) if df is not None and column in df.columns else Profile("empty")
        return self._cache[key]

    def compatible(self, primary_col: str, secondary_col: str) -> bool:
        if not self.available:
            return True
        return compatible(self._profile("p", primary_col), self._profile("s", secondary_col))

    def latest_wave(self, secondary_col: str) -> float:
        """The most recent timeseries with a value in this trend-file column (-1 if none known)."""
        key = ("wave", secondary_col)
        if key not in self._cache:
            latest = -1.0
            df = self.secondary_df
            if df is not None and self.secondary_timeseries and secondary_col in df.columns:
                import pandas as pd

                filled = df[secondary_col].astype(str).str.strip().ne("") & df[secondary_col].notna()
                waves = pd.to_numeric(df.loc[filled, self.secondary_timeseries], errors="coerce").dropna()
                latest = float(waves.max()) if not waves.empty else -1.0
            self._cache[key] = latest
        return self._cache[key]


# --- The close-match step ---------------------------------------------------------

def close_candidates(
    primary_col: str, secondary_cols: list[str], aliases: list[set[str]],
) -> list[str]:
    """Earlier-wave columns that are the same column by the name rules or the alias list."""
    from rapidfuzz import fuzz

    wanted = close_name(primary_col, secondary=False)
    group = next((g for g in aliases if canonical(primary_col) in g), set())
    equal = [
        col for col in secondary_cols
        if close_name(col, secondary=True) == wanted or canonical(col) in group
    ]
    if equal or len(wanted) < 6:
        return equal
    scored = [(fuzz.ratio(wanted, close_name(col, secondary=True)), col) for col in secondary_cols]
    best = max((score for score, _col in scored), default=0)
    return [col for score, col in scored if score >= FUZZY_CLOSE and score == best]


def pick(primary_col: str, candidates: list[str], values: ValueCheck) -> str | None:
    """The candidate holding the same kind of values that the most recent wave used."""
    from rapidfuzz import fuzz

    fitting = [col for col in candidates if values.compatible(primary_col, col)]
    if not fitting:
        return None
    if len(fitting) > 1 and not values.available:
        return None  # several equally named candidates and no data to choose: leave it to the analyst
    return max(fitting, key=lambda col: (values.latest_wave(col), fuzz.QRatio(primary_col.casefold(), col.casefold())))
