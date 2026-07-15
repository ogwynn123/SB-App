#!/usr/bin/env python3
"""Global survey question catalog (SQLite) with fuzzy search and link approval."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from rapidfuzz import fuzz

from wincrossTableCompile import apply_battery_suffixes, mark_common_stems, parse_survey


SURVEY_DIR_RE = re.compile(r"(?i)^NPA(?P<code>\d{4,})$")
TABLE_ID_RE = re.compile(r"(?i)^TQ(?P<qid>\d+[a-z]?)\^\d+$")
HEADER_QID_RE = re.compile(r"(?i)^Q(?P<qid>\d+[a-z]?)\.\s*(?P<title>.+)$")
QID_PARTS_RE = re.compile(r"(?i)^(?P<qnum>\d+)(?P<suffix>[a-z]?)$")
BRACKET_RE = re.compile(r"\[[^\]]+\]")
WS_RE = re.compile(r"\s+")
NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")
SKIP_TABLE_LINE_PREFIXES = ("TQ",)
LINK_STATUSES = {"suggested", "approved", "auto_approved", "rejected"}
STOP_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class SurveyPaths:
    code: str
    folder: Path
    json_path: Path | None
    tables_autogen_path: Path | None
    tables_checked_path: Path | None

    @property
    def preferred_tables_path(self) -> Path | None:
        if self.tables_checked_path and self.tables_checked_path.exists():
            return self.tables_checked_path
        if self.tables_autogen_path and self.tables_autogen_path.exists():
            return self.tables_autogen_path
        return None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_root(base_dir: Path | None = None) -> Path:
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent
    return base_dir / "NPA_Surveys"


def default_db_path(root: Path) -> Path:
    return root / "catalog.sqlite"


def _clean_text(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u2019", "'").replace("\u00a0", " ")
    text = WS_RE.sub(" ", text)
    return text.strip()


def _should_preserve_brackets(question_text: str, item_text: str | None) -> bool:
    blob = f"{_clean_text(question_text)} {_clean_text(item_text)}".casefold()
    return "less likely" in blob and "more likely" in blob


def _normalize_text(value: str | None, preserve_brackets: bool = False) -> str:
    text = _clean_text(value).casefold()
    if not preserve_brackets:
        text = BRACKET_RE.sub(" ", text)
    text = NON_ALNUM_RE.sub(" ", text)
    text = WS_RE.sub(" ", text)
    return text.strip()


def _meaningful_tokens(text: str) -> set[str]:
    return {
        tok
        for tok in text.split()
        if tok and len(tok) >= 3 and tok not in STOP_TOKENS
    }


def _qid_parts(qid: str | None) -> tuple[str | None, str | None]:
    if not qid:
        return None, None
    m = QID_PARTS_RE.match(qid.strip())
    if not m:
        return None, None
    qnum = str(int(m.group("qnum")))
    suffix = (m.group("suffix") or "").lower()
    return qnum, suffix


def _make_key(*parts: str) -> str:
    raw = "|".join(parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return digest


def _unique_question_key(
    base_key: str,
    *,
    signature: tuple[Any, ...],
    seen_signatures: set[tuple[Any, ...]],
    assigned_keys: set[str],
    duplicate_counts: dict[str, int],
) -> str | None:
    if signature in seen_signatures:
        return None
    seen_signatures.add(signature)

    if base_key not in assigned_keys:
        assigned_keys.add(base_key)
        duplicate_counts[base_key] = 1
        return base_key

    next_idx = duplicate_counts.get(base_key, 1) + 1
    candidate = _make_key(base_key, f"dup{next_idx}")
    while candidate in assigned_keys:
        next_idx += 1
        candidate = _make_key(base_key, f"dup{next_idx}")
    duplicate_counts[base_key] = next_idx
    assigned_keys.add(candidate)
    return candidate


def _resolve_json_path(folder: Path, code: str) -> Path | None:
    exact = folder / f"NPA{code}JSON.json"
    if exact.exists():
        return exact
    matches = sorted(folder.glob("*JSON*.json"))
    return matches[0] if matches else None


def _resolve_tables_autogen_path(folder: Path, code: str) -> Path | None:
    autogen = folder / f"NPA{code}TABLES.autogen.txt"
    legacy = folder / f"NPA{code}TABLES.txt"
    if autogen.exists():
        return autogen
    if legacy.exists():
        return legacy
    return None


def _resolve_tables_checked_path(folder: Path, code: str) -> Path | None:
    checked = folder / f"NPA{code}TABLES.checked.txt"
    return checked if checked.exists() else None


def discover_surveys(root: Path) -> list[SurveyPaths]:
    surveys: list[SurveyPaths] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        m = SURVEY_DIR_RE.match(child.name)
        if not m:
            continue
        code = str(int(m.group("code")))
        surveys.append(
            SurveyPaths(
                code=code,
                folder=child,
                json_path=_resolve_json_path(child, code),
                tables_autogen_path=_resolve_tables_autogen_path(child, code),
                tables_checked_path=_resolve_tables_checked_path(child, code),
            )
        )
    return surveys


def _parse_tables_blocks(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in lines:
        line = raw.strip()
        if not line or line == "```" or line.upper() == "[TABLES]":
            continue
        if TABLE_ID_RE.match(line):
            if current is not None:
                blocks.append(current)
            current = {"table_id": line, "banner": "", "header": "", "lines": []}
            continue
        if current is None:
            continue
        if not current["banner"]:
            current["banner"] = line
            continue
        if not current["header"]:
            current["header"] = line
            continue
        if any(line.upper().startswith(prefix) for prefix in SKIP_TABLE_LINE_PREFIXES):
            continue
        current["lines"].append(line)
    if current is not None:
        blocks.append(current)
    return blocks


def _extract_table_qid(table_id: str, header: str) -> tuple[str | None, str]:
    m_header = HEADER_QID_RE.match(header)
    if m_header:
        return m_header.group("qid").lower(), _clean_text(m_header.group("title"))
    m_table = TABLE_ID_RE.match(table_id)
    if m_table:
        return m_table.group("qid").lower(), _clean_text(header)
    return None, _clean_text(header)


def _extract_table_option_line(line: str) -> tuple[str, str]:
    if "^" not in line:
        return _clean_text(line), ""
    label, rest = line.split("^", 1)
    selector = rest.split("^", 1)[0] if "^" in rest else rest
    return _clean_text(label), _clean_text(selector)


def _open_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS surveys (
            survey_code TEXT PRIMARY KEY,
            folder_path TEXT NOT NULL,
            json_path TEXT,
            tables_autogen_path TEXT,
            tables_checked_path TEXT,
            preferred_tables_path TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS questions (
            question_key TEXT PRIMARY KEY,
            survey_code TEXT NOT NULL,
            source TEXT NOT NULL,
            qid TEXT,
            qnum TEXT,
            item_suffix TEXT,
            question_text TEXT NOT NULL,
            item_text TEXT,
            normalized_text TEXT NOT NULL,
            table_id TEXT,
            table_header TEXT,
            payload_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_questions_survey ON questions(survey_code);
        CREATE INDEX IF NOT EXISTS idx_questions_qid ON questions(qid);
        CREATE INDEX IF NOT EXISTS idx_questions_source ON questions(source);

        CREATE TABLE IF NOT EXISTS question_options (
            question_key TEXT NOT NULL,
            ord INTEGER NOT NULL,
            option_value TEXT,
            option_text TEXT,
            normalized_option_text TEXT,
            PRIMARY KEY (question_key, ord)
        );

        CREATE INDEX IF NOT EXISTS idx_qopts_question ON question_options(question_key);
        CREATE INDEX IF NOT EXISTS idx_qopts_norm ON question_options(normalized_option_text);

        CREATE TABLE IF NOT EXISTS question_links (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            left_question_key TEXT NOT NULL,
            right_question_key TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            reviewed_at TEXT,
            note TEXT
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_question_links_pair
            ON question_links(left_question_key, right_question_key);
        """
    )


def _insert_survey(conn: sqlite3.Connection, survey: SurveyPaths) -> None:
    conn.execute(
        """
        INSERT INTO surveys(
            survey_code, folder_path, json_path, tables_autogen_path,
            tables_checked_path, preferred_tables_path, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            survey.code,
            str(survey.folder),
            str(survey.json_path) if survey.json_path else "",
            str(survey.tables_autogen_path) if survey.tables_autogen_path else "",
            str(survey.tables_checked_path) if survey.tables_checked_path else "",
            str(survey.preferred_tables_path) if survey.preferred_tables_path else "",
            utc_now_iso(),
        ),
    )


def _insert_question(
    conn: sqlite3.Connection,
    *,
    question_key: str,
    survey_code: str,
    source: str,
    qid: str | None,
    question_text: str,
    item_text: str | None,
    normalized_text: str,
    table_id: str | None = None,
    table_header: str | None = None,
    payload_json: str | None = None,
) -> None:
    qnum, suffix = _qid_parts(qid)
    conn.execute(
        """
        INSERT INTO questions(
            question_key, survey_code, source, qid, qnum, item_suffix,
            question_text, item_text, normalized_text, table_id, table_header, payload_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            question_key,
            survey_code,
            source,
            qid or "",
            qnum or "",
            suffix or "",
            question_text,
            item_text or "",
            normalized_text,
            table_id or "",
            table_header or "",
            payload_json or "",
        ),
    )


def _insert_options(
    conn: sqlite3.Connection,
    question_key: str,
    options: Iterable[tuple[int, str, str]],
) -> None:
    conn.executemany(
        """
        INSERT INTO question_options(
            question_key, ord, option_value, option_text, normalized_option_text
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                question_key,
                order,
                value,
                text,
                _normalize_text(text),
            )
            for order, value, text in options
        ],
    )


def _catalog_json_questions(conn: sqlite3.Connection, survey: SurveyPaths) -> int:
    if not survey.json_path or not survey.json_path.exists():
        return 0
    obj = json.loads(survey.json_path.read_text(encoding="utf-8"))
    questions = parse_survey(obj)
    apply_battery_suffixes(questions)
    mark_common_stems(questions)

    created = 0
    seen_signatures: set[tuple[Any, ...]] = set()
    assigned_keys: set[str] = set()
    duplicate_counts: dict[str, int] = {}
    for q in questions:
        preserve_brackets = _should_preserve_brackets(q.title, q.item_text)
        q_text = _clean_text(q.title)
        i_text = _clean_text(q.item_text)
        option_pairs = [(_clean_text(o.value), _clean_text(o.text)) for o in q.options]
        opt_texts = [text for _value, text in option_pairs]
        normalized = _normalize_text(
            " ".join([q_text, i_text, *opt_texts]),
            preserve_brackets=preserve_brackets,
        )
        base_key = _make_key(
            survey.code,
            "json",
            q.qid.casefold(),
            _normalize_text(q_text, preserve_brackets=preserve_brackets),
            _normalize_text(i_text, preserve_brackets=preserve_brackets),
        )
        signature = (
            survey.code,
            "json",
            q.qid.casefold(),
            q_text,
            i_text,
            tuple(option_pairs),
        )
        question_key = _unique_question_key(
            base_key,
            signature=signature,
            seen_signatures=seen_signatures,
            assigned_keys=assigned_keys,
            duplicate_counts=duplicate_counts,
        )
        if question_key is None:
            continue
        _insert_question(
            conn,
            question_key=question_key,
            survey_code=survey.code,
            source="json",
            qid=q.qid,
            question_text=q_text,
            item_text=i_text,
            normalized_text=normalized,
            payload_json=json.dumps(
                {
                    "qid": q.qid,
                    "qnum": q.qnum,
                    "title": q.title,
                    "item_text": q.item_text,
                },
                ensure_ascii=False,
            ),
        )
        _insert_options(
            conn,
            question_key,
            ((idx, opt.value, _clean_text(opt.text)) for idx, opt in enumerate(q.options, start=1)),
        )
        created += 1
    return created


def _catalog_table_blocks(conn: sqlite3.Connection, survey: SurveyPaths, source: str, path: Path) -> int:
    if not path.exists():
        return 0
    blocks = _parse_tables_blocks(path)
    created = 0
    seen_signatures: set[tuple[Any, ...]] = set()
    assigned_keys: set[str] = set()
    duplicate_counts: dict[str, int] = {}
    for block in blocks:
        table_id = _clean_text(block.get("table_id"))
        header = _clean_text(block.get("header"))
        qid, title = _extract_table_qid(table_id, header)
        preserve_brackets = _should_preserve_brackets(title, "")
        option_pairs: list[tuple[int, str, str]] = []
        for idx, raw_line in enumerate(block.get("lines", []), start=1):
            label, selector = _extract_table_option_line(raw_line)
            if not label:
                continue
            option_pairs.append((idx, selector, label))
        normalized = _normalize_text(
            " ".join([title, *[label for _idx, _sel, label in option_pairs]]),
            preserve_brackets=preserve_brackets,
        )
        base_key = _make_key(
            survey.code,
            source,
            (qid or "").casefold(),
            table_id.casefold(),
            _normalize_text(title, preserve_brackets=preserve_brackets),
        )
        signature = (
            survey.code,
            source,
            (qid or "").casefold(),
            table_id,
            title,
            tuple(option_pairs),
        )
        question_key = _unique_question_key(
            base_key,
            signature=signature,
            seen_signatures=seen_signatures,
            assigned_keys=assigned_keys,
            duplicate_counts=duplicate_counts,
        )
        if question_key is None:
            continue
        _insert_question(
            conn,
            question_key=question_key,
            survey_code=survey.code,
            source=source,
            qid=qid,
            question_text=title or header,
            item_text="",
            normalized_text=normalized,
            table_id=table_id,
            table_header=header,
            payload_json=json.dumps(block, ensure_ascii=False),
        )
        _insert_options(conn, question_key, option_pairs)
        created += 1
    return created


def rebuild_catalog(root: Path, db_path: Path) -> dict[str, int]:
    surveys = discover_surveys(root)
    conn = _open_db(db_path)
    _ensure_schema(conn)
    counts = {
        "surveys": 0,
        "json_questions": 0,
        "tables_checked_questions": 0,
        "tables_autogen_questions": 0,
    }
    with conn:
        conn.execute("DELETE FROM surveys")
        conn.execute("DELETE FROM question_options")
        conn.execute("DELETE FROM questions")
        for survey in surveys:
            _insert_survey(conn, survey)
            counts["surveys"] += 1
            counts["json_questions"] += _catalog_json_questions(conn, survey)
            if survey.tables_checked_path:
                counts["tables_checked_questions"] += _catalog_table_blocks(
                    conn,
                    survey,
                    "tables_checked",
                    survey.tables_checked_path,
                )
            if survey.tables_autogen_path:
                counts["tables_autogen_questions"] += _catalog_table_blocks(
                    conn,
                    survey,
                    "tables_autogen",
                    survey.tables_autogen_path,
                )
    conn.close()
    return counts


def _load_option_map(conn: sqlite3.Connection) -> dict[str, list[str]]:
    option_map: dict[str, list[str]] = {}
    rows = conn.execute(
        "SELECT question_key, normalized_option_text FROM question_options"
    ).fetchall()
    for row in rows:
        question_key = row["question_key"]
        normalized = row["normalized_option_text"] or ""
        if not normalized:
            continue
        option_map.setdefault(question_key, []).append(normalized)
    return option_map


def search_catalog(
    db_path: Path,
    query: str,
    *,
    limit: int = 25,
    source: str | None = None,
) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    conn = _open_db(db_path)
    option_map = _load_option_map(conn)
    params: list[Any] = []
    sql = """
        SELECT question_key, survey_code, source, qid, qnum, item_suffix,
               question_text, item_text, normalized_text, table_id, table_header
        FROM questions
    """
    if source:
        sql += " WHERE source = ?"
        params.append(source)
    rows = conn.execute(sql, params).fetchall()
    normalized_query = _normalize_text(query, preserve_brackets=True)
    query_tokens = _meaningful_tokens(normalized_query)
    scored: list[dict[str, Any]] = []
    for row in rows:
        qkey = row["question_key"]
        normalized_row = row["normalized_text"] or ""
        row_tokens = _meaningful_tokens(normalized_row)
        overlap_count = len(query_tokens.intersection(row_tokens)) if query_tokens else 0
        if query_tokens:
            min_overlap = len(query_tokens) if len(query_tokens) <= 3 else 2
            if overlap_count < min_overlap:
                continue
        base_score = int(fuzz.token_set_ratio(normalized_query, normalized_row))
        option_score = 0
        for normalized_opt in option_map.get(qkey, []):
            option_score = max(option_score, int(fuzz.token_set_ratio(normalized_query, normalized_opt)))
        overlap_score = int(round(100 * (overlap_count / max(len(query_tokens), 1)))) if query_tokens else 0
        score = int(round(0.55 * base_score + 0.2 * option_score + 0.25 * overlap_score))
        if normalized_query and normalized_query in normalized_row:
            score = min(100, score + 10)
        if score < 40:
            continue
        scored.append(
            {
                "question_key": qkey,
                "survey_code": row["survey_code"],
                "source": row["source"],
                "qid": row["qid"],
                "question_text": row["question_text"],
                "item_text": row["item_text"],
                "table_header": row["table_header"],
                "score": score,
            }
        )
    conn.close()
    scored.sort(key=lambda item: (-item["score"], item["survey_code"], item["qid"] or ""))
    return scored[:limit]


def _question_similarity(
    left: sqlite3.Row,
    right: sqlite3.Row,
    option_map: dict[str, list[str]],
) -> int:
    text_score = int(fuzz.WRatio(left["normalized_text"] or "", right["normalized_text"] or ""))
    left_item = _normalize_text(left["item_text"] or "")
    right_item = _normalize_text(right["item_text"] or "")
    item_score = int(fuzz.WRatio(left_item, right_item)) if (left_item or right_item) else 0
    left_opts = set(option_map.get(left["question_key"], []))
    right_opts = set(option_map.get(right["question_key"], []))
    if left_opts and right_opts:
        inter = len(left_opts.intersection(right_opts))
        union = len(left_opts.union(right_opts))
        option_score = int(round(100 * (inter / max(union, 1))))
    else:
        option_score = 0
    if left_item or right_item:
        return int(round(0.45 * text_score + 0.35 * item_score + 0.2 * option_score))
    return int(round(0.75 * text_score + 0.25 * option_score))


def _canonical_pair(left_key: str, right_key: str) -> tuple[str, str]:
    if left_key <= right_key:
        return left_key, right_key
    return right_key, left_key


def suggest_links(
    db_path: Path,
    query: str,
    *,
    limit: int = 40,
    min_confidence: int = 70,
    auto_approve_threshold: int = 97,
) -> list[dict[str, Any]]:
    conn = _open_db(db_path)
    _ensure_schema(conn)
    normalized_query = _normalize_text(query, preserve_brackets=True)
    option_map = _load_option_map(conn)
    rows = conn.execute(
        """
        SELECT question_key, survey_code, source, qid, question_text, item_text, normalized_text
        FROM questions
        """
    ).fetchall()
    query_tokens = _meaningful_tokens(normalized_query)
    ranked = []
    for row in rows:
        normalized_row = row["normalized_text"] or ""
        row_tokens = _meaningful_tokens(normalized_row)
        overlap_count = len(query_tokens.intersection(row_tokens)) if query_tokens else 0
        if query_tokens:
            min_overlap = len(query_tokens) if len(query_tokens) <= 3 else 2
            if overlap_count < min_overlap:
                continue
        score = int(fuzz.token_set_ratio(normalized_query, normalized_row))
        if score < 40:
            continue
        ranked.append((score, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    source_priority = {"tables_checked": 3, "tables_autogen": 2, "json": 1}
    dedup: dict[tuple[str, str], tuple[int, sqlite3.Row]] = {}
    for score, row in ranked:
        dedup_key = (
            row["survey_code"],
            (row["qid"] or row["question_text"] or "").casefold(),
        )
        prior = dedup.get(dedup_key)
        if prior is None:
            dedup[dedup_key] = (score, row)
            continue
        prior_score, prior_row = prior
        prior_rank = source_priority.get(prior_row["source"], 0)
        new_rank = source_priority.get(row["source"], 0)
        if new_rank > prior_rank or (new_rank == prior_rank and score > prior_score):
            dedup[dedup_key] = (score, row)
    dedup_ranked = sorted(dedup.values(), key=lambda item: item[0], reverse=True)
    candidate_rows = [row for _score, row in dedup_ranked[: max(limit * 3, 60)]]

    suggested: list[dict[str, Any]] = []
    reached_limit = False
    with conn:
        for i in range(len(candidate_rows)):
            left = candidate_rows[i]
            for j in range(i + 1, len(candidate_rows)):
                right = candidate_rows[j]
                if left["survey_code"] == right["survey_code"]:
                    continue
                confidence = _question_similarity(left, right, option_map)
                if confidence < min_confidence:
                    continue
                status = "auto_approved" if confidence >= auto_approve_threshold else "suggested"
                left_key, right_key = _canonical_pair(left["question_key"], right["question_key"])
                existing = conn.execute(
                    """
                    SELECT link_id, status
                    FROM question_links
                    WHERE left_question_key = ? AND right_question_key = ?
                    """,
                    (left_key, right_key),
                ).fetchone()
                if existing and existing["status"] in ("approved", "rejected"):
                    continue
                if existing:
                    conn.execute(
                        """
                        UPDATE question_links
                        SET confidence = ?, status = ?, created_at = ?
                        WHERE link_id = ?
                        """,
                        (confidence, status, utc_now_iso(), existing["link_id"]),
                    )
                    link_id = int(existing["link_id"])
                else:
                    cur = conn.execute(
                        """
                        INSERT INTO question_links(
                            left_question_key, right_question_key, confidence, status, created_at, reviewed_at, note
                        )
                        VALUES (?, ?, ?, ?, ?, '', '')
                        """,
                        (left_key, right_key, confidence, status, utc_now_iso()),
                    )
                    link_id = int(cur.lastrowid)
                suggested.append(
                    {
                        "link_id": link_id,
                        "left_question_key": left_key,
                        "right_question_key": right_key,
                        "confidence": confidence,
                        "status": status,
                        "left_survey": left["survey_code"],
                        "left_source": left["source"],
                        "left_qid": left["qid"],
                        "right_survey": right["survey_code"],
                        "right_source": right["source"],
                        "right_qid": right["qid"],
                    }
                )
                if len(suggested) >= limit:
                    reached_limit = True
                    break
            if reached_limit:
                break
    conn.close()
    suggested.sort(key=lambda item: (-item["confidence"], item["link_id"]))
    return suggested


def list_links(
    db_path: Path,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    conn = _open_db(db_path)
    _ensure_schema(conn)
    params: list[Any] = []
    sql = """
        SELECT
            l.link_id, l.confidence, l.status, l.created_at, l.reviewed_at,
            l.left_question_key, l.right_question_key,
            ql.survey_code AS left_survey, ql.source AS left_source, ql.qid AS left_qid, ql.question_text AS left_text,
            qr.survey_code AS right_survey, qr.source AS right_source, qr.qid AS right_qid, qr.question_text AS right_text
        FROM question_links l
        LEFT JOIN questions ql ON ql.question_key = l.left_question_key
        LEFT JOIN questions qr ON qr.question_key = l.right_question_key
    """
    if status:
        sql += " WHERE l.status = ?"
        params.append(status)
    sql += " ORDER BY l.confidence DESC, l.link_id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_link_status(db_path: Path, link_id: int, status: str) -> bool:
    if status not in LINK_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    conn = _open_db(db_path)
    _ensure_schema(conn)
    with conn:
        cur = conn.execute(
            """
            UPDATE question_links
            SET status = ?, reviewed_at = ?
            WHERE link_id = ?
            """,
            (status, utc_now_iso(), link_id),
        )
        changed = cur.rowcount > 0
    conn.close()
    return changed
