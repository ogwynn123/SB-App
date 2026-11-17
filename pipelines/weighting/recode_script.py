"""Run WinCross-style recode lines to build derived weighting variables.

Covers the subset used in .job weighting set-ups, so blocks can be pasted in:

    DECLARE VOTEHIST:1=0
    IF NOT VF_G2024 ( ) COMPUTE VOTEHIST = VOTEHIST + 1
    IF Q101 (1-4) ASSIGN SEXAGE = (1)
    IF Q100 (2) COMPUTE SEXAGE = SEXAGE + 5
    IF REGIONCODE (2-5) COMPUTE RACEREGION = RACEREGION + {5 *{REGIONCODE - 1}}
    ASSIGN SEXREGION = REGIONCODE

Conditions use COLUMN (codes) with AND / OR / NOT and { } for grouping;
( ) means blank and alpha codes match regardless of case. Lines starting with
* are comments. A TIMESERIES test is treated as true when the data has no
TIMESERIES column, since single-wave files do not carry one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TIMESERIES = "TIMESERIES"


class RecodeError(ValueError):
    def __init__(self, line_no: int, line: str, message: str):
        super().__init__(f"Line {line_no}: {message}\n    {line.strip()}")
        self.line_no = line_no


@dataclass
class RecodeResult:
    data: pd.DataFrame
    created: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def apply_recode_script(df: pd.DataFrame, script: str) -> RecodeResult:
    """Return a copy of df with every variable the script assigns added as a text column."""
    result = RecodeResult(data=df.copy())
    if not script or not script.strip():
        return result
    runner = _Runner(result)
    for line_no, raw in enumerate(script.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        try:
            runner.run_line(line)
        except RecodeError:
            raise
        except _ParseError as exc:
            raise RecodeError(line_no, raw, str(exc)) from None
    return result


# --------------------------------------------------------------------------- internals


class _ParseError(Exception):
    pass


def _format_number(value: float) -> str:
    if pd.isna(value):
        return ""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.10g}"


def _normalize(value) -> str:
    text = "" if value is None else str(value).strip()
    if re.fullmatch(r"-?\d+\.0+", text):
        text = text.split(".")[0]
    return text.upper()


@dataclass
class ConditionResult:
    mask: np.ndarray  # True for the rows the condition keeps
    resolved: list[str] = field(default_factory=list)  # e.g. "TIMESERIES (MAX) = 12"


def evaluate_condition(df: pd.DataFrame, text: str) -> ConditionResult:
    """Evaluate a filter such as 'TIMESERIES (MAX) AND QSTYPE (1)' on every row of df.

    Same tests as IF lines: COLUMN (codes) with AND / OR / NOT and { }; ( ) = blank,
    1-4,7 = ranges and lists, A-Z = letters. (MAX) / (MIN) mean the highest / lowest
    whole-number code in that column. Unlike recode lines, every column must exist.
    """
    runner = _Runner(RecodeResult(data=df), strict=True)
    cursor = _Cursor(text.strip())
    try:
        mask = runner._condition(cursor)
        if not cursor.at_end():
            raise _ParseError(f"unexpected text: {cursor.rest()}")
    except _ParseError as exc:
        raise RecodeError(1, text, str(exc)) from None
    return ConditionResult(mask=mask.to_numpy(dtype=bool), resolved=runner.resolved)


class _Runner:
    def __init__(self, result: RecodeResult, strict: bool = False):
        self.result = result
        self.df = result.data
        self.columns = {c.upper(): c for c in self.df.columns}
        self.timeseries_noted = False
        self.strict = strict  # filters: a missing TIMESERIES column is an error, not "true"
        self.resolved: list[str] = []

    # -- statements

    def run_line(self, line: str) -> None:
        cursor = _Cursor(line)
        keyword = cursor.word().upper()
        if keyword == "DECLARE":
            self._declare(cursor.rest())
            return
        mask = pd.Series(True, index=self.df.index)
        if keyword == "IF":
            mask = self._condition(cursor)
            keyword = cursor.word().upper()
        if keyword not in ("ASSIGN", "COMPUTE"):
            raise _ParseError("expected ASSIGN or COMPUTE")
        target = cursor.word()
        if not target:
            raise _ParseError(f"{keyword} needs a variable name")
        cursor.expect("=")
        if target.upper() not in self.columns:
            # WinCross needs a DECLARE first; here a counter built with COMPUTE starts at 0
            # (like DECLARE VOTEHIST:1=0) and a code built with ASSIGN starts blank.
            start = "0" if keyword == "COMPUTE" else ""
            self._store(target, pd.Series(start, index=self.df.index, dtype=object), None)
        if keyword == "ASSIGN" and cursor.peek() == "(":
            values = pd.Series(cursor.parenthesised().strip(), index=self.df.index, dtype=object)
        else:
            numeric = self._expression(cursor)
            if keyword == "ASSIGN" and cursor.single_name is not None:
                values = self._column(cursor.single_name).astype(str).str.strip()
            else:
                values = numeric.map(_format_number)
        if not cursor.at_end():
            raise _ParseError(f"unexpected text: {cursor.rest()}")
        self._store(target, values, mask)

    def _declare(self, text: str) -> None:
        for item in text.split(","):
            match = re.fullmatch(r"\s*([A-Za-z0-9_]+)\s*(?::\s*\d+)?\s*(?:=\s*(\S+))?\s*", item)
            if not match:
                raise _ParseError(f"cannot read DECLARE item '{item.strip()}'")
            name, initial = match.groups()
            if initial is not None or name.upper() not in self.columns:
                self._store(name, pd.Series(initial or "", index=self.df.index, dtype=object), None)

    def _store(self, name: str, values: pd.Series, mask: pd.Series | None) -> None:
        key = name.upper()
        column = self.columns.get(key)
        if column is None:
            column = name
            self.columns[key] = column
            self.df[column] = ""
            self.result.created.append(column)
        if mask is None:
            self.df[column] = values.astype(str)
        else:
            self.df.loc[mask, column] = values[mask].astype(str)

    # -- conditions

    def _condition(self, cursor: "_Cursor") -> pd.Series:
        result = self._and(cursor)
        while cursor.peek_word().upper() == "OR":
            cursor.word()
            result = result | self._and(cursor)
        return result

    def _and(self, cursor: "_Cursor") -> pd.Series:
        result = self._unary(cursor)
        while cursor.peek_word().upper() == "AND":
            cursor.word()
            result = result & self._unary(cursor)
        return result

    def _unary(self, cursor: "_Cursor") -> pd.Series:
        if cursor.peek_word().upper() == "NOT":
            cursor.word()
            return ~self._unary(cursor)
        if cursor.peek() == "{":
            cursor.expect("{")
            inner = self._condition(cursor)
            cursor.expect("}")
            return inner
        name = cursor.word()
        if not name:
            raise _ParseError("expected a test like Q100 (1)")
        codes = cursor.parenthesised()
        if name.upper() == TIMESERIES and TIMESERIES not in self.columns and not self.strict:
            if not self.timeseries_noted:
                self.result.notes.append("No TIMESERIES column in the data; TIMESERIES tests were treated as true.")
                self.timeseries_noted = True
            return pd.Series(True, index=self.df.index)
        values = self._column(name).map(_normalize)
        keyword = codes.strip().upper()
        if keyword in ("MAX", "MIN"):
            numbers = [int(v) for v in values.unique() if re.fullmatch(r"-?\d+", v)]
            if not numbers:
                raise _ParseError(f"{name} ({keyword}) needs whole-number codes in {name}")
            pick = max(numbers) if keyword == "MAX" else min(numbers)
            self.resolved.append(f"{self.columns[name.upper()]} ({keyword}) = {pick}")
            return values == str(pick)
        return values.isin(_expand_codes(codes))

    # -- arithmetic

    def _expression(self, cursor: "_Cursor") -> pd.Series:
        cursor.single_name = None
        start = cursor.pos
        value = self._sum(cursor)
        text = cursor.text[start:cursor.pos].strip()
        cursor.single_name = text if re.fullmatch(r"[A-Za-z0-9_]+", text) and not _is_number(text) else None
        return value

    def _sum(self, cursor: "_Cursor") -> pd.Series:
        value = self._product(cursor)
        while cursor.peek() in ("+", "-"):
            op = cursor.take()
            other = self._product(cursor)
            value = value + other if op == "+" else value - other
        return value

    def _product(self, cursor: "_Cursor") -> pd.Series:
        value = self._atom(cursor)
        while cursor.peek() in ("*", "/"):
            op = cursor.take()
            other = self._atom(cursor)
            if op == "*":
                value = value * other
            else:
                value = value / other.replace(0, np.nan)
        return value

    def _atom(self, cursor: "_Cursor") -> pd.Series:
        if cursor.peek() in ("{", "("):
            closer = "}" if cursor.take() == "{" else ")"
            value = self._sum(cursor)
            cursor.expect(closer)
            return value
        if cursor.peek() == "-":
            cursor.take()
            return -self._atom(cursor)
        word = cursor.word()
        if not word:
            raise _ParseError("expected a number or variable")
        if _is_number(word):
            return pd.Series(float(word), index=self.df.index)
        return pd.to_numeric(self._column(word).astype(str).str.strip(), errors="coerce").fillna(0.0)

    def _column(self, name: str) -> pd.Series:
        column = self.columns.get(name.upper())
        if column is None:
            where = "in the data" if self.strict else "in the data or a variable defined above"
            raise _ParseError(f"'{name}' is not a column {where}")
        return self.df[column]


def _is_number(text: str) -> bool:
    return re.fullmatch(r"\d+(\.\d*)?|\.\d+", text) is not None


def _expand_codes(text: str) -> set[str]:
    """'1-4,7' -> {1,2,3,4,7}; 'U,N,O, ' -> {U,N,O,''}; ' ' -> {''}; 'A-C' -> {A,B,C}."""
    codes: set[str] = set()
    for token in text.split(","):
        token = token.strip()
        range_match = re.fullmatch(r"(-?\d+)\s*-\s*(-?\d+)", token)
        alpha_match = re.fullmatch(r"([A-Za-z])\s*-\s*([A-Za-z])", token)
        if range_match:
            lo, hi = sorted(int(x) for x in range_match.groups())
            codes.update(str(v) for v in range(lo, hi + 1))
        elif alpha_match:
            lo, hi = sorted(ch.upper() for ch in alpha_match.groups())
            codes.update(chr(c) for c in range(ord(lo), ord(hi) + 1))
        else:
            codes.add(_normalize(token))
    return codes


class _Cursor:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.single_name: str | None = None

    def _skip(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def peek(self) -> str:
        self._skip()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def take(self) -> str:
        ch = self.peek()
        self.pos += 1
        return ch

    def expect(self, ch: str) -> None:
        if self.peek() != ch:
            found = self.peek() or "end of line"
            raise _ParseError(f"expected '{ch}' but found '{found}'")
        self.pos += 1

    def word(self) -> str:
        self._skip()
        match = re.match(r"[A-Za-z0-9_.]+", self.text[self.pos:])
        if not match:
            return ""
        self.pos += match.end()
        return match.group(0)

    def peek_word(self) -> str:
        saved = self.pos
        word = self.word()
        self.pos = saved
        return word

    def parenthesised(self) -> str:
        self.expect("(")
        end = self.text.find(")", self.pos)
        if end < 0:
            raise _ParseError("missing ')'")
        inner = self.text[self.pos:end]
        self.pos = end + 1
        return inner

    def rest(self) -> str:
        self._skip()
        return self.text[self.pos:]

    def at_end(self) -> bool:
        return self.peek() == ""
