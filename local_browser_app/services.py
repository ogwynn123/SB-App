"""Thin service adapters around the existing SurveyPlatform processing cores.

The browser application deliberately keeps business rules in the existing pipeline
modules.  This module only normalizes browser payloads, serializes results, and
provides a small, stable API for the HTTP layer and tests.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any, Callable, Iterable


APP_DIR = Path(__file__).resolve().parent
PLATFORM_ROOT = APP_DIR.parent
PIPELINES_ROOT = PLATFORM_ROOT / "pipelines"
QUESTION_DB = PLATFORM_ROOT / "repository" / "questions.sqlite"

for _module_dir in (
    PIPELINES_ROOT / "wincross_table_generator",
    PIPELINES_ROOT / "table_merger",
    PIPELINES_ROOT / "open_end_coder",
    PIPELINES_ROOT / "auto_results",
    PIPELINES_ROOT / "sample_quota_checker",
):
    value = str(_module_dir)
    if value not in sys.path:
        sys.path.insert(0, value)


LogCallback = Callable[[str], None]


def jsonable(value: Any) -> Any:
    """Convert pipeline dataclasses and path objects to JSON-safe values."""
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    return value


def _text(payload: dict[str, Any], key: str, default: str = "") -> str:
    return str(payload.get(key, default) or "").strip()


def _required_path(payload: dict[str, Any], key: str, *, must_exist: bool = True) -> Path:
    raw = _text(payload, key)
    if not raw:
        raise ValueError(f"{key.replace('_', ' ').title()} is required.")
    path = Path(raw).expanduser().resolve(strict=False)
    if must_exist and not path.exists():
        raise FileNotFoundError(path)
    return path


def _optional_path(payload: dict[str, Any], key: str) -> Path | None:
    raw = _text(payload, key)
    return Path(raw).expanduser().resolve(strict=False) if raw else None


def _as_bool(payload: dict[str, Any], key: str, default: bool = False) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Sample quota checker


def quota_review(payload: dict[str, Any]) -> dict[str, Any]:
    from quota_browser_review import build_quota_review

    quota_path = _required_path(payload, "quota_path")
    sample_path = _required_path(payload, "sample_path")
    return build_quota_review(
        quota_path,
        sample_path,
        mappings=payload.get("mappings") if isinstance(payload.get("mappings"), dict) else None,
        matches=payload.get("matches") if isinstance(payload.get("matches"), dict) else None,
        section_filters=(
            payload.get("section_filters") if isinstance(payload.get("section_filters"), dict) else None
        ),
    )


# ---------------------------------------------------------------------------
# Table generator


def table_discover(payload: dict[str, Any]) -> dict[str, Any]:
    import survey_pipeline_gui as gui

    root = _required_path(payload, "root")
    if not root.is_dir():
        raise ValueError(f"Table Gen root is not a folder: {root}")
    output_root = _optional_path(payload, "output_root")
    jobs = gui.discover_pairs_recursive(root, output_root)
    rows: list[dict[str, Any]] = []
    for job in jobs:
        validation = gui.compute_validation(job)
        rows.append(
            {
                "job_id": job.job_id,
                "stem": job.stem,
                "folder": str(job.folder),
                "docx": str(job.docx),
                "pdf": str(job.pdf),
                "raw_out": str(job.raw_out),
                "json_out": str(job.json_out),
                "tables_out": str(job.tables_out),
                "banners_out": str(job.banners_out),
                "cover_out": str(job.cover_out),
                "validation": validation,
            }
        )
    return {"root": str(root), "count": len(rows), "jobs": rows}


def table_run(payload: dict[str, Any], log: LogCallback) -> dict[str, Any]:
    import survey_pipeline as pipeline

    raw_jobs = payload.get("jobs")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        raise ValueError("Select at least one discovered Table Gen job.")

    include_banners = _as_bool(payload, "include_banners", True)
    include_cover = _as_bool(payload, "include_cover", True)
    completed: list[dict[str, Any]] = []
    for index, raw_job in enumerate(raw_jobs, start=1):
        if not isinstance(raw_job, dict):
            raise ValueError("Invalid Table Gen job payload.")
        docx = _required_path(raw_job, "docx")
        pdf = _required_path(raw_job, "pdf")
        raw_out = _required_path(raw_job, "raw_out", must_exist=False)
        json_out = _required_path(raw_job, "json_out", must_exist=False)
        tables_out = _required_path(raw_job, "tables_out", must_exist=False)
        banners_out = _required_path(raw_job, "banners_out", must_exist=False)
        cover_out = _required_path(raw_job, "cover_out", must_exist=False)
        log(f"[browser] Table Gen {index}/{len(raw_jobs)}: {docx.stem}")
        pipeline.run_one(
            docx=docx,
            pdf=pdf,
            raw_out=raw_out,
            json_out=json_out,
            tables_out=tables_out,
            banners_out=banners_out,
            cover_out=cover_out,
            py_exe=sys.executable,
            on_message=log,
            skip_banners=not include_banners,
            skip_cover=not include_cover,
        )
        completed.append(
            {
                "stem": docx.stem,
                "raw": str(raw_out),
                "json": str(json_out),
                "tables": str(tables_out),
                "banners": str(banners_out) if include_banners else None,
                "cover": str(cover_out) if include_cover else None,
            }
        )
    return {"completed": len(completed), "outputs": completed}


# ---------------------------------------------------------------------------
# Sheet merge


def sheet_file_info(payload: dict[str, Any]) -> dict[str, Any]:
    import sheet_merge_core as core

    path = _required_path(payload, "path")
    sheets = core.list_sheets(path) if path.suffix.casefold() == ".xlsx" else []
    requested_sheet = _text(payload, "sheet") or (sheets[0] if sheets else None)
    frame = core.read_table(path, requested_sheet)
    return {
        "path": str(path),
        "sheets": sheets,
        "selected_sheet": requested_sheet,
        "rows": len(frame),
        "columns": [str(column) for column in frame.columns],
    }


def _merge_options(payload: dict[str, Any]):
    import sheet_merge_core as core

    primary = _required_path(payload, "primary_path")
    secondary = _required_path(payload, "secondary_path")
    mapping, blocked = core.parse_mapping_text_with_blocks(_text(payload, "mapping_text"))
    output = _optional_path(payload, "output_path")
    output_parent = (output.parent if output else primary.parent).resolve(strict=False)
    return core.MergeOptions(
        primary_path=primary,
        secondary_path=secondary,
        primary_sheet=_text(payload, "primary_sheet") or None,
        secondary_sheet=_text(payload, "secondary_sheet") or None,
        primary_join=_text(payload, "primary_join") or None,
        secondary_join=_text(payload, "secondary_join") or None,
        mapping_mode="manual_only" if _text(payload, "mapping_mode") == "manual_only" else "auto",
        threshold=int(payload.get("threshold", 85) or 85),
        top_n=5,
        duplicate_policy_primary="continue",
        duplicate_policy_secondary="continue",
        conflict_policy="append",
        output_mode="new_file",
        row_order="primary_first" if _text(payload, "row_order") == "primary_first" else "secondary_first",
        output_path=output,
        xlsx_write_mode="preserve_sheets",
        report_enabled=_as_bool(payload, "report_enabled", True),
        archive_secondary=_as_bool(payload, "archive_secondary", False),
        report_dir=output_parent / "compilingReports",
        archive_dir=output_parent / "surveyInput",
        manual_mapping=mapping,
        blocked_primary_columns=blocked,
    )


def sheet_preview(payload: dict[str, Any]) -> dict[str, Any]:
    import sheet_merge_core as core

    options = _merge_options(payload)
    analysis = core.analyze_merge(options)

    primary_df = core.read_table(options.primary_path, options.primary_sheet)
    secondary_df = core.read_table(options.secondary_path, options.secondary_sheet)
    context = core.build_timeseries_context(options, list(secondary_df.columns))
    if context.enabled:
        core.apply_timeseries_primary_layer(primary_df, secondary_df, context)
    primary_cols = list(primary_df.columns)
    secondary_cols = list(secondary_df.columns)
    primary_join, secondary_join = core._resolve_joins(
        options, primary_cols, secondary_cols
    )
    mapping, methods, scores = core._build_effective_mapping(
        options,
        primary_cols,
        secondary_cols,
        primary_join,
        secondary_join,
        context,
    )
    mapping_rows = [
        {
            "primary": primary_col,
            "secondary": secondary_col,
            "method": methods.get(primary_col, ""),
            "score": scores.get(primary_col),
        }
        for primary_col, secondary_col in mapping.items()
    ]
    reviewed_text = "\n".join(
        f"{row['primary']}={row['secondary']}"
        for row in mapping_rows
        if row["method"] not in {"secondary_extra", "timeseries_extra"}
    )
    return {
        "analysis": jsonable(analysis),
        "mapping": mapping_rows,
        "reviewed_mapping_text": reviewed_text,
        "blocked_primary_columns": sorted(options.blocked_primary_columns),
        "timeseries": jsonable(context),
    }


def sheet_run(payload: dict[str, Any], log: LogCallback) -> dict[str, Any]:
    import sheet_merge_core as core

    options = _merge_options(payload)
    log(f"[browser] Merging {options.secondary_path.name} into {options.primary_path.name}")
    result = core.run_merge(options)
    log(f"[browser] Merge complete: {result.output_path}")
    return jsonable(result)


# ---------------------------------------------------------------------------
# Open-end record coder


def _oe_session_path(payload: dict[str, Any], *, allow_default: bool = False) -> Path:
    raw = _text(payload, "session_path")
    if raw:
        return Path(raw).expanduser().resolve(strict=False)
    if allow_default:
        data_path = _required_path(payload, "data_path")
        return data_path.with_name(f"{data_path.stem}.oe_session.sqlite")
    raise ValueError("Session path is required.")


def _oe_dashboard(session: Any) -> dict[str, Any]:
    dataset = session.active_dataset()
    return {
        "session_path": str(session.path),
        "dataset": dict(dataset) if dataset is not None else None,
        "questions": jsonable(session.questions()),
        "review": jsonable(session.review_summary()),
        "max_timeseries": session.max_timeseries(),
    }


def oe_import(payload: dict[str, Any]) -> dict[str, Any]:
    import oe_record_coder_core as core

    data_path = _required_path(payload, "data_path")
    session_path = _oe_session_path(payload, allow_default=True)
    session = core.CodingSession(
        session_path,
        survey_id=_text(payload, "survey_id"),
        project_root=data_path.parent,
    )
    try:
        summary = session.import_data(data_path, key_column=_text(payload, "key_column") or None)
        codelist = _optional_path(payload, "codelist_path")
        codelist_summary = None
        if codelist is not None:
            codelist_summary = session.load_codelist(
                codelist,
                overwrite_existing=_as_bool(payload, "overwrite_codelist", False),
            )
        return {
            "import": jsonable(summary),
            "codelist": jsonable(codelist_summary),
            "dashboard": _oe_dashboard(session),
        }
    finally:
        session.close()


def oe_dashboard(payload: dict[str, Any]) -> dict[str, Any]:
    import oe_record_coder_core as core

    session = core.CodingSession(_oe_session_path(payload))
    try:
        return _oe_dashboard(session)
    finally:
        session.close()


def oe_responses(payload: dict[str, Any]) -> dict[str, Any]:
    import oe_record_coder_core as core

    question_id = int(payload.get("question_id", 0) or 0)
    if question_id <= 0:
        raise ValueError("Select an open-end question.")
    raw_timeseries = payload.get("timeseries")
    timeseries = int(raw_timeseries) if str(raw_timeseries or "").strip() else None
    limit = min(max(int(payload.get("limit", 250) or 250), 1), 1000)
    session = core.CodingSession(_oe_session_path(payload))
    try:
        rows = session.list_responses(
            question_id,
            status=_text(payload, "status", "all"),
            search=_text(payload, "search"),
            code_filter=_text(payload, "code_filter"),
            code_scope=_text(payload, "code_scope", "either"),
            timeseries=timeseries,
            import_scope=_text(payload, "import_scope", "all"),
        )
        codes = session.list_codes(question_id, include_inactive=True)
        return {
            "total": len(rows),
            "limited": len(rows) > limit,
            "responses": jsonable(rows[:limit]),
            "codes": jsonable(codes),
            "question": jsonable(session.question(question_id)),
        }
    finally:
        session.close()


def _parse_codes(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item for item in re.split(r"[\s,;]+", str(value or "").strip()) if item]


def oe_assign(payload: dict[str, Any]) -> dict[str, Any]:
    import oe_record_coder_core as core

    response_id = int(payload.get("response_id", 0) or 0)
    if response_id <= 0:
        raise ValueError("Select a response to code.")
    session = core.CodingSession(_oe_session_path(payload))
    try:
        codes = _parse_codes(payload.get("codes"))
        response = session.set_assignment(
            response_id,
            codes,
            flagged=_as_bool(payload, "flagged", False),
            note=_text(payload, "note"),
        )
        applied = 1
        if _as_bool(payload, "apply_matching", False):
            applied = session.apply_to_matching_text(
                response_id,
                codes,
                timeseries=response.timeseries if _as_bool(payload, "matching_timeseries_only", True) else None,
            )
            response = session.response(response_id)
        return {"response": jsonable(response), "applied": applied}
    finally:
        session.close()


def oe_reset(payload: dict[str, Any]) -> dict[str, Any]:
    import oe_record_coder_core as core

    response_id = int(payload.get("response_id", 0) or 0)
    if response_id <= 0:
        raise ValueError("Select a response to reset.")
    session = core.CodingSession(_oe_session_path(payload))
    try:
        return {"response": jsonable(session.reset_assignment(response_id))}
    finally:
        session.close()


def oe_upsert_code(payload: dict[str, Any]) -> dict[str, Any]:
    import oe_record_coder_core as core

    session = core.CodingSession(_oe_session_path(payload))
    try:
        result = session.upsert_code(
            int(payload.get("question_id", 0) or 0),
            _text(payload, "code"),
            label=_text(payload, "label"),
            supercategory=_text(payload, "supercategory"),
            direction=_text(payload, "direction", "o"),
            active=_as_bool(payload, "active", True),
        )
        return {"code": jsonable(result)}
    finally:
        session.close()


def oe_export(payload: dict[str, Any], log: LogCallback) -> dict[str, Any]:
    import oe_record_coder_core as core

    kind = _text(payload, "kind", "coded_csv")
    output_path = _required_path(payload, "output_path", must_exist=False)
    session = core.CodingSession(_oe_session_path(payload))
    try:
        log(f"[browser] Exporting OE {kind}: {output_path}")
        if kind == "coded_csv":
            result = session.export_coded_csv(output_path)
        elif kind == "codebook":
            result = {"output_path": session.export_codebook_xlsx(output_path)}
        elif kind == "wincross":
            result = session.export_wincross_tables(output_path)
        elif kind == "audit":
            result = {"output_path": session.export_audit_csv(output_path)}
        else:
            raise ValueError(f"Unsupported OE export kind: {kind}")
        return jsonable(result)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Question browser


def _question_connection(db_path: Path = QUESTION_DB) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"Question index not found: {db_path}")
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def question_filters(_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    connection = _question_connection()
    try:
        def values(column: str, limit: int = 500) -> list[str]:
            rows = connection.execute(
                f"SELECT DISTINCT {column} AS value FROM repo_questions "
                f"WHERE TRIM({column})<>'' ORDER BY {column} LIMIT ?",
                (limit,),
            ).fetchall()
            return [str(row["value"]) for row in rows]

        count = int(connection.execute("SELECT COUNT(*) FROM repo_questions").fetchone()[0])
        return {
            "count": count,
            "states": values("state_code"),
            "regions": values("region"),
            "clients": values("client"),
            "types": values("question_type"),
            "families": values("question_family"),
        }
    finally:
        connection.close()


def _search_tokens(query: str) -> list[str]:
    return [token.casefold() for token in re.findall(r"[A-Za-z0-9']+", query) if token]


def question_search(payload: dict[str, Any]) -> dict[str, Any]:
    query = _text(payload, "query")
    mode = _text(payload, "mode", "all_words")
    if mode not in {"all_words", "exact", "any_word"}:
        mode = "all_words"
    page = max(int(payload.get("page", 1) or 1), 1)
    page_size = min(max(int(payload.get("page_size", 40) or 40), 10), 100)

    clauses = ["1=1"]
    params: list[Any] = []
    filter_columns = {
        "state": "q.state_code",
        "region": "q.region",
        "client": "q.client",
        "question_type": "q.question_type",
        "question_family": "q.question_family",
        "survey_code": "q.survey_code",
    }
    for key, column in filter_columns.items():
        value = _text(payload, key)
        if value:
            clauses.append(f"{column}=? COLLATE NOCASE")
            params.append(value)

    columns = [
        "q.question_text",
        "q.item_text",
        "q.option_texts_json",
        "q.question_family",
        "q.question_group",
        "q.classification_groups_json",
        "q.question_topics_json",
        "q.structure_tags_json",
        "q.scale_tags_json",
        "q.question_target",
    ]
    combined = " OR ".join(f"LOWER({column}) LIKE ?" for column in columns)
    if query:
        terms = [query.casefold()] if mode == "exact" else _search_tokens(query)
        if not terms:
            clauses.append("0=1")
        else:
            pieces: list[str] = []
            for term in terms:
                pieces.append(f"({combined})")
                params.extend([f"%{term}%"] * len(columns))
            clauses.append((" OR " if mode == "any_word" else " AND ").join(pieces))

    where = " AND ".join(f"({clause})" for clause in clauses)
    connection = _question_connection()
    try:
        total = int(
            connection.execute(f"SELECT COUNT(*) FROM repo_questions q WHERE {where}", params).fetchone()[0]
        )
        pages = (total + page_size - 1) // page_size
        if pages:
            page = min(page, pages)
        offset = (page - 1) * page_size
        rows = connection.execute(
            f"""
            SELECT q.question_id, q.survey_id, q.survey_code, q.qid, q.qnum,
                   q.question_text, q.item_text, q.option_texts_json,
                   q.question_type, q.question_family, q.question_group,
                   q.question_target, q.state_code, q.region, q.client,
                   q.canonical_key, q.source_json_path
            FROM repo_questions q
            WHERE {where}
            ORDER BY q.survey_code DESC, q.question_ord, q.item_suffix
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["options"] = json.loads(str(item.pop("option_texts_json") or "[]"))
            except json.JSONDecodeError:
                item["options"] = []
            output.append(item)
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "results": output,
        }
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Auto Results


def auto_results_run(payload: dict[str, Any], log: LogCallback) -> dict[str, Any]:
    import autoResults_gui as core

    source_mode = _text(payload, "source_mode", "docx")
    marginals = _optional_path(payload, "marginals_path")
    xlsx = _optional_path(payload, "xlsx_path")
    template = _required_path(payload, "template_path")
    output = _required_path(payload, "output_path", must_exist=False)
    placeholder = str(payload.get("placeholder", "!!") or "!!")
    log(f"[browser] Auto Results source={source_mode}; template={template.name}")
    try:
        result = core.run_autoresults(
            marginals_path=marginals,
            template_path=template,
            output_path=output,
            placeholder=placeholder,
            mode="no_fix" if _text(payload, "mode") == "no_fix" else "fix",
            write_report=_as_bool(payload, "write_report", True),
            xlsx_path=xlsx,
            source_mode="xlsx" if source_mode == "xlsx" else "docx",
        )
    except Exception as exc:
        title, message, include_traceback = core.friendly_run_error(
            exc,
            marginals_path=marginals,
            template_path=template,
            output_path=output,
            xlsx_path=xlsx,
        )
        error = RuntimeError(f"{title}: {message}")
        if not include_traceback:
            raise error from None
        raise error from exc
    log(f"[browser] Auto Results complete: {output}")
    return jsonable(result)

