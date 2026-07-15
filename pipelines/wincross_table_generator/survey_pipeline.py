#!/usr/bin/env python3
"""Run survey unformat -> JSON conversion -> optional table compile in one command."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional

MessageCallback = Optional[Callable[[str], None]]


def emit(msg: str, on_message: MessageCallback = None) -> None:
    if on_message:
        on_message(msg)
    else:
        print(msg)


def run_step(cmd: List[str], on_message: MessageCallback = None) -> None:
    emit(f"[pipeline] Running: {' '.join(cmd)}", on_message)
    if on_message is None:
        subprocess.run(cmd, check=True)
        return

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            on_message(line)
    code = proc.wait()
    if code != 0:
        raise subprocess.CalledProcessError(code, cmd)


def run_script(
    script_path: Path,
    script_args: List[str],
    py_exe: str,
    on_message: MessageCallback = None,
) -> None:
    if getattr(sys, "frozen", False):
        display = " ".join([str(script_path), *script_args])
        emit(f"[pipeline] Running: {display}", on_message)
        old_argv = sys.argv[:]
        cap = io.StringIO() if on_message else None
        out_ctx = contextlib.redirect_stdout(cap) if cap is not None else contextlib.nullcontext()
        err_ctx = contextlib.redirect_stderr(cap) if cap is not None else contextlib.nullcontext()
        pending_error: BaseException | None = None
        try:
            with out_ctx, err_ctx:
                try:
                    sys.argv = [str(script_path), *script_args]
                    runpy.run_path(str(script_path), run_name="__main__")
                except SystemExit as exc:
                    code = 0 if exc.code is None else exc.code
                    if not isinstance(code, int):
                        code = 1
                    if code != 0:
                        pending_error = subprocess.CalledProcessError(code, [str(script_path), *script_args])
                except BaseException as exc:  # pragma: no cover - defensive passthrough
                    pending_error = exc
        finally:
            sys.argv = old_argv
        if cap is not None and on_message is not None:
            for line in cap.getvalue().splitlines():
                if line.strip():
                    on_message(line)
        if pending_error is not None:
            raise pending_error
        return
    run_step([py_exe, str(script_path), *script_args], on_message=on_message)


def count_question_elements(json_path: Path) -> int:
    try:
        obj = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if isinstance(obj, dict):
        elements = obj.get("elements")
        if isinstance(elements, list):
            return sum(
                1
                for el in elements
                if isinstance(el, dict) and (el.get("type") == "question" or el.get("element_type") == "question")
            )
    if isinstance(obj, list):
        return sum(
            1 for el in obj if isinstance(el, dict) and (el.get("type") == "question" or el.get("element_type") == "question")
        )
    return 0


def write_raw_from_pdf(pdf_path: Path, raw_out: Path) -> int:
    try:
        import pdfplumber  # type: ignore
    except Exception as exc:
        raise SystemExit(f"PDF fallback unavailable (pdfplumber import failed): {exc}") from exc

    lines: List[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for ln in text.splitlines():
                ln = ln.replace("\xa0", " ").strip()
                ln = re.sub(r"\s+", " ", ln)
                if ln:
                    lines.append(ln)

    raw_out.write_text("\n".join(lines), encoding="utf-8")
    return len(lines)


def default_output_paths(docx_path: Path) -> tuple[Path, Path, Path]:
    stem = docx_path.stem
    parent = docx_path.parent if docx_path.parent != Path("") else Path(".")
    return (
        parent / f"{stem}RAW.txt",
        parent / f"{stem}JSON.json",
        parent / f"{stem}TABLES.autogen.txt",
    )


def default_banners_output_path(source_path: Path) -> Path:
    stem = source_path.stem
    parent = source_path.parent if source_path.parent != Path("") else Path(".")
    return parent / f"{stem}BANNERS.autogen.txt"


def banners_output_path_for_tables(tables_path: Path) -> Path:
    name = tables_path.name
    if "TABLES.autogen" in name:
        return tables_path.with_name(name.replace("TABLES.autogen", "BANNERS.autogen", 1))
    if "TABLES" in name:
        return tables_path.with_name(name.replace("TABLES", "BANNERS", 1))
    return tables_path.with_name(f"{tables_path.stem}BANNERS.autogen.txt")


def cover_output_path_for_tables(tables_path: Path) -> Path:
    name = tables_path.name
    if "TABLES.autogen" in name:
        return tables_path.with_name(name.replace("TABLES.autogen", "COVER.autogen", 1)).with_suffix(".docx")
    if "TABLES" in name:
        return tables_path.with_name(name.replace("TABLES", "COVER", 1)).with_suffix(".docx")
    return tables_path.with_name(f"{tables_path.stem}COVER.autogen.docx")


def default_translation_output_paths(source_path: Path) -> tuple[Path, Path, Path, Path]:
    stem = source_path.stem
    parent = source_path.parent if source_path.parent != Path("") else Path(".")
    return (
        parent / f"{stem}RAW.en.txt",
        parent / f"{stem}RAW.es.txt",
        parent / f"{stem}JSON.es.json",
        parent / f"{stem}TABLES.autogen.txt",
    )


def ensure_parent(path: Path) -> None:
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


def _run_tomas_translate(
    *,
    tomas_script: Path,
    raw_in: Path,
    raw_out: Path,
    py_exe: str,
    on_message: MessageCallback,
    tomas_mode: str,
    tomas_locale: str,
    tomas_register: str,
    tomas_model: str,
    tomas_reasoning_effort: str,
    tomas_temperature: float,
    tomas_max_output_tokens: Optional[int],
    tomas_glossary: Optional[Path],
    tomas_scale_map: Optional[Path],
    tomas_strict: bool,
) -> None:
    args: List[str] = [
        str(raw_in),
        "-o",
        str(raw_out),
        "--mode",
        tomas_mode,
        "--locale",
        tomas_locale,
        "--register",
        tomas_register,
        "--model",
        tomas_model,
        "--reasoning-effort",
        tomas_reasoning_effort,
        "--temperature",
        str(tomas_temperature),
    ]
    if tomas_max_output_tokens is not None:
        args.extend(["--max-output-tokens", str(int(tomas_max_output_tokens))])
    if tomas_glossary is not None:
        args.extend(["--glossary", str(tomas_glossary)])
    if tomas_scale_map is not None:
        args.extend(["--scale-map", str(tomas_scale_map)])
    if not tomas_strict:
        args.append("--no-strict")
    run_script(tomas_script, args, py_exe, on_message=on_message)


def run_one(
    docx: Optional[Path],
    pdf: Optional[Path],
    raw_out: Path,
    json_out: Path,
    tables_out: Path,
    py_exe: str,
    banners_out: Optional[Path] = None,
    cover_out: Optional[Path] = None,
    raw_input: Optional[Path] = None,
    on_message: MessageCallback = None,
    translate_spanish: bool = False,
    translated_raw_out: Optional[Path] = None,
    skip_tables: bool = False,
    skip_banners: bool = False,
    skip_cover: bool = False,
    tomas_mode: str = "cati",
    tomas_locale: str = "es-US",
    tomas_register: str = "usted",
    tomas_model: str = "gpt-5.4",
    tomas_reasoning_effort: str = "high",
    tomas_temperature: float = 0.0,
    tomas_max_output_tokens: Optional[int] = None,
    tomas_glossary: Optional[Path] = None,
    tomas_scale_map: Optional[Path] = None,
    tomas_strict: bool = True,
) -> None:
    if translate_spanish and translated_raw_out is None:
        translated_raw_out = raw_out.with_name(f"{raw_out.stem}.es{raw_out.suffix}")
    if banners_out is None:
        banners_out = banners_output_path_for_tables(tables_out)
    if cover_out is None:
        cover_out = cover_output_path_for_tables(tables_out)

    paths_to_prepare = [raw_out, json_out]
    if not skip_tables:
        paths_to_prepare.append(tables_out)
    if not skip_banners:
        paths_to_prepare.append(banners_out)
    if not skip_cover:
        paths_to_prepare.append(cover_out)
    if translated_raw_out is not None:
        paths_to_prepare.append(translated_raw_out)

    for path in paths_to_prepare:
        ensure_parent(path)

    base_dir = Path(__file__).resolve().parent
    unformatter = base_dir / "survey_unformatter.py"
    converter = base_dir / "surveyConvertJSON.py"
    table_compiler = base_dir / "wincrossTableCompile.py"
    banner_compiler = base_dir / "wincrossBannerCompile.py"
    cover_compiler = base_dir / "wincrossCoverCompile.py"
    tomas_candidates = [
        base_dir.parent / "thomas_in_a_box" / "tomas_translate.py",
        base_dir.parent / "tomasInaBox" / "tomas_translate.py",
    ]
    tomas_script = next((p for p in tomas_candidates if p.exists()), tomas_candidates[0])

    required_scripts = [unformatter, converter]
    if not skip_tables:
        required_scripts.append(table_compiler)
    if not skip_banners:
        required_scripts.append(banner_compiler)
    if not skip_cover:
        required_scripts.append(cover_compiler)
    if translate_spanish:
        required_scripts.append(tomas_script)

    for script in required_scripts:
        if not script.exists():
            raise SystemExit(f"Required script not found: {script}")

    if tomas_glossary and not tomas_glossary.exists():
        raise SystemExit(f"TOMAS glossary file not found: {tomas_glossary}")
    if tomas_scale_map and not tomas_scale_map.exists():
        raise SystemExit(f"TOMAS scale-map file not found: {tomas_scale_map}")

    if raw_input:
        emit(f"[pipeline] Using provided raw input: {raw_input}", on_message)
        raw_out.write_text(raw_input.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    else:
        if docx is None:
            raise SystemExit("Internal error: docx path is required when --raw-input is not provided.")
        step1_args = ["--docx", str(docx), "--output", str(raw_out)]
        if pdf:
            step1_args.extend(["--pdf", str(pdf)])
        run_script(unformatter, step1_args, py_exe, on_message=on_message)

    converter_input = raw_out
    if translate_spanish:
        assert translated_raw_out is not None
        emit(f"[pipeline] Translating RAW to Spanish: {translated_raw_out}", on_message)
        _run_tomas_translate(
            tomas_script=tomas_script,
            raw_in=raw_out,
            raw_out=translated_raw_out,
            py_exe=py_exe,
            on_message=on_message,
            tomas_mode=tomas_mode,
            tomas_locale=tomas_locale,
            tomas_register=tomas_register,
            tomas_model=tomas_model,
            tomas_reasoning_effort=tomas_reasoning_effort,
            tomas_temperature=tomas_temperature,
            tomas_max_output_tokens=tomas_max_output_tokens,
            tomas_glossary=tomas_glossary,
            tomas_scale_map=tomas_scale_map,
            tomas_strict=tomas_strict,
        )
        converter_input = translated_raw_out

    step2_args = ["--input", str(converter_input), "--out", str(json_out)]
    run_script(converter, step2_args, py_exe, on_message=on_message)
    q_count = count_question_elements(json_out)

    if q_count == 0 and pdf and not raw_input:
        emit("[pipeline] Parsed 0 questions from DOCX-derived RAW; retrying with PDF-derived RAW...", on_message)
        line_count = write_raw_from_pdf(pdf, raw_out)
        emit(f"[pipeline] PDF RAW rebuilt with {line_count} line(s): {raw_out}", on_message)

        if translate_spanish:
            assert translated_raw_out is not None
            emit(f"[pipeline] Re-translating PDF-derived RAW to Spanish: {translated_raw_out}", on_message)
            _run_tomas_translate(
                tomas_script=tomas_script,
                raw_in=raw_out,
                raw_out=translated_raw_out,
                py_exe=py_exe,
                on_message=on_message,
                tomas_mode=tomas_mode,
                tomas_locale=tomas_locale,
                tomas_register=tomas_register,
                tomas_model=tomas_model,
                tomas_temperature=tomas_temperature,
                tomas_max_output_tokens=tomas_max_output_tokens,
                tomas_glossary=tomas_glossary,
                tomas_scale_map=tomas_scale_map,
                tomas_strict=tomas_strict,
            )

        run_script(converter, step2_args, py_exe, on_message=on_message)
        q_count = count_question_elements(json_out)

    if q_count == 0:
        raise SystemExit(
            "Parsed 0 questions from RAW input. RAW format is incompatible with surveyConvertJSON.py "
            "(expects numbered lines like '1. Question'). Use --raw-input with a pre-numbered .txt file."
        )
    emit(f"[pipeline] Parsed questions: {q_count}", on_message)

    if not skip_tables:
        step3_args = [str(json_out), str(tables_out)]
        run_script(table_compiler, step3_args, py_exe, on_message=on_message)
    if not skip_banners:
        banner_args = [str(json_out), str(banners_out)]
        run_script(banner_compiler, banner_args, py_exe, on_message=on_message)
    if not skip_cover:
        if skip_banners and not banners_out.exists():
            raise SystemExit(f"Cover generation requires a banner file: {banners_out}")
        cover_args = [str(json_out), str(banners_out), str(cover_out)]
        run_script(cover_compiler, cover_args, py_exe, on_message=on_message)

    emit("[pipeline] Complete.", on_message)
    emit(f"[pipeline] RAW: {raw_out}", on_message)
    if translate_spanish and translated_raw_out is not None:
        emit(f"[pipeline] RAW (Spanish): {translated_raw_out}", on_message)
    emit(f"[pipeline] JSON: {json_out}", on_message)
    if not skip_tables:
        emit(f"[pipeline] TABLES: {tables_out}", on_message)
    else:
        emit("[pipeline] TABLES: skipped", on_message)
    if not skip_banners:
        emit(f"[pipeline] BANNERS: {banners_out}", on_message)
    else:
        emit("[pipeline] BANNERS: skipped", on_message)
    if not skip_cover:
        emit(f"[pipeline] COVER: {cover_out}", on_message)
    else:
        emit("[pipeline] COVER: skipped", on_message)


def find_docx_pdf_pairs(root: Path) -> List[tuple[Path, Path]]:
    docx_by_stem = {p.stem.lower(): p for p in root.glob("*.docx")}
    pdf_by_stem = {p.stem.lower(): p for p in root.glob("*.pdf")}
    shared = sorted(set(docx_by_stem).intersection(pdf_by_stem))
    return [(docx_by_stem[s], pdf_by_stem[s]) for s in shared]


def find_docx_pdf_pairs_recursive(root: Path) -> List[tuple[Path, Path]]:
    docx_by_key = {(p.parent.resolve(), p.stem.lower()): p for p in root.rglob("*.docx")}
    pdf_by_key = {(p.parent.resolve(), p.stem.lower()): p for p in root.rglob("*.pdf")}
    shared = sorted(set(docx_by_key).intersection(pdf_by_key))
    return [(docx_by_key[k], pdf_by_key[k]) for k in shared]


def default_scan_root() -> Path:
    # For PyInstaller EXEs, scan the folder where the EXE lives.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def should_auto_pause() -> bool:
    # Double-click EXE launch typically has no args and should pause before close.
    return getattr(sys, "frozen", False) and len(sys.argv) == 1


def pause_before_exit() -> None:
    try:
        input("\n[pipeline] Press Enter to close...")
    except EOFError:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Pipeline survey_unformatter.py -> surveyConvertJSON.py -> optional wincrossTableCompile.py"
    )
    ap.add_argument("--docx", help="Input DOCX survey path. If omitted, auto-process matching DOCX/PDF pairs in --root.")
    ap.add_argument("--pdf", help="Optional PDF path passed to survey_unformatter.py.")
    ap.add_argument("--raw-input", help="Optional pre-numbered RAW .txt input. If provided, skips survey_unformatter step.")
    ap.add_argument("--raw-out", help="Flattened text output path.")
    ap.add_argument("--translated-raw-out", help="Spanish translated RAW output path.")
    ap.add_argument("--json-out", help="Parsed JSON output path.")
    ap.add_argument("--tables-out", help="Wincross tables output path.")
    ap.add_argument("--banners-out", help="Wincross banners output path.")
    ap.add_argument("--cover-out", help="Subgroup definitions cover DOCX output path.")
    ap.add_argument("--translate-spanish", action="store_true", help="Run TOMAS translation before JSON conversion.")
    ap.add_argument("--skip-tables", action="store_true", help="Skip TABLES compilation stage.")
    ap.add_argument("--skip-banners", action="store_true", help="Skip BANNERS compilation stage.")
    ap.add_argument("--skip-cover", action="store_true", help="Skip COVER DOCX generation stage.")
    ap.add_argument("--tomas-mode", choices=["cati", "sms"], default="cati")
    ap.add_argument("--tomas-locale", default="es-US")
    ap.add_argument("--tomas-register", default="usted")
    ap.add_argument("--tomas-model", default="gpt-5.4")
    ap.add_argument(
        "--tomas-reasoning-effort",
        choices=["minimal", "low", "medium", "high", "xhigh"],
        default="high",
    )
    ap.add_argument("--tomas-temperature", type=float, default=0.0)
    ap.add_argument("--tomas-max-output-tokens", type=int, default=0)
    ap.add_argument("--tomas-glossary", help="Path to TOMAS glossary JSON file.")
    ap.add_argument("--tomas-scale-map", help="Path to TOMAS scale-map JSON file.")
    ap.add_argument("--no-tomas-strict", action="store_true", help="Disable strict TOMAS translation validation.")
    ap.add_argument(
        "--root",
        help="Directory to scan for same-name DOCX/PDF pairs when --docx is omitted (default: script/exe directory).",
    )
    ap.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable to use for child scripts (default: current interpreter).",
    )
    args = ap.parse_args()

    tomas_glossary = Path(args.tomas_glossary) if args.tomas_glossary else None
    tomas_scale_map = Path(args.tomas_scale_map) if args.tomas_scale_map else None
    tomas_max_tokens = None if args.tomas_max_output_tokens == 0 else int(args.tomas_max_output_tokens)

    if args.raw_input:
        raw_input = Path(args.raw_input)
        if not raw_input.exists():
            raise SystemExit(f"RAW input not found: {raw_input}")

        if args.translate_spanish:
            raw_default, raw_es_default, json_default, tables_default = default_translation_output_paths(raw_input)
            banners_default = banners_output_path_for_tables(tables_default)
            translated_raw_out = Path(args.translated_raw_out) if args.translated_raw_out else raw_es_default
        else:
            stem = raw_input.stem
            parent = raw_input.parent if raw_input.parent != Path("") else Path(".")
            raw_default = parent / f"{stem}.txt"
            json_default = parent / f"{stem}JSON.json"
            tables_default = parent / f"{stem}TABLES.autogen.txt"
            banners_default = banners_output_path_for_tables(tables_default)
            translated_raw_out = Path(args.translated_raw_out) if args.translated_raw_out else None

        raw_out = Path(args.raw_out) if args.raw_out else raw_default
        json_out = Path(args.json_out) if args.json_out else json_default
        tables_out = Path(args.tables_out) if args.tables_out else tables_default
        banners_out = Path(args.banners_out) if args.banners_out else banners_default
        cover_out = Path(args.cover_out) if args.cover_out else cover_output_path_for_tables(tables_out)

        run_one(
            None,
            None,
            raw_out,
            json_out,
            tables_out,
            args.python,
            banners_out=banners_out,
            cover_out=cover_out,
            raw_input=raw_input,
            translate_spanish=args.translate_spanish,
            translated_raw_out=translated_raw_out,
            skip_tables=args.skip_tables,
            skip_banners=args.skip_banners,
            skip_cover=args.skip_cover,
            tomas_mode=args.tomas_mode,
            tomas_locale=args.tomas_locale,
            tomas_register=args.tomas_register,
            tomas_model=args.tomas_model,
            tomas_reasoning_effort=args.tomas_reasoning_effort,
            tomas_temperature=args.tomas_temperature,
            tomas_max_output_tokens=tomas_max_tokens,
            tomas_glossary=tomas_glossary,
            tomas_scale_map=tomas_scale_map,
            tomas_strict=(not args.no_tomas_strict),
        )
        return

    if args.docx:
        docx = Path(args.docx)
        if not docx.exists():
            raise SystemExit(f"DOCX not found: {docx}")

        pdf = Path(args.pdf) if args.pdf else None
        if pdf and not pdf.exists():
            raise SystemExit(f"PDF not found: {pdf}")

        if args.translate_spanish:
            raw_default, raw_es_default, json_default, tables_default = default_translation_output_paths(docx)
            banners_default = banners_output_path_for_tables(tables_default)
            translated_raw_out = Path(args.translated_raw_out) if args.translated_raw_out else raw_es_default
        else:
            raw_default, json_default, tables_default = default_output_paths(docx)
            banners_default = default_banners_output_path(docx)
            translated_raw_out = Path(args.translated_raw_out) if args.translated_raw_out else None

        raw_out = Path(args.raw_out) if args.raw_out else raw_default
        json_out = Path(args.json_out) if args.json_out else json_default
        tables_out = Path(args.tables_out) if args.tables_out else tables_default
        banners_out = Path(args.banners_out) if args.banners_out else banners_default
        cover_out = Path(args.cover_out) if args.cover_out else cover_output_path_for_tables(tables_out)

        run_one(
            docx,
            pdf,
            raw_out,
            json_out,
            tables_out,
            args.python,
            banners_out=banners_out,
            cover_out=cover_out,
            translate_spanish=args.translate_spanish,
            translated_raw_out=translated_raw_out,
            skip_tables=args.skip_tables,
            skip_banners=args.skip_banners,
            skip_cover=args.skip_cover,
            tomas_mode=args.tomas_mode,
            tomas_locale=args.tomas_locale,
                tomas_register=args.tomas_register,
                tomas_model=args.tomas_model,
                tomas_reasoning_effort=args.tomas_reasoning_effort,
                tomas_temperature=args.tomas_temperature,
                tomas_max_output_tokens=tomas_max_tokens,
            tomas_glossary=tomas_glossary,
            tomas_scale_map=tomas_scale_map,
            tomas_strict=(not args.no_tomas_strict),
        )
        return

    root = Path(args.root) if args.root else default_scan_root()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Root directory not found: {root}")

    pairs = find_docx_pdf_pairs(root)
    if not pairs:
        raise SystemExit(f"No same-name DOCX/PDF pairs found in: {root.resolve()}")

    print(f"[pipeline] Found {len(pairs)} DOCX/PDF pair(s) in {root.resolve()}")
    for docx, pdf in pairs:
        if args.translate_spanish:
            raw_out, translated_raw_out, json_out, tables_out = default_translation_output_paths(docx)
            banners_out = banners_output_path_for_tables(tables_out)
            cover_out = cover_output_path_for_tables(tables_out)
        else:
            raw_out, json_out, tables_out = default_output_paths(docx)
            banners_out = default_banners_output_path(docx)
            cover_out = cover_output_path_for_tables(tables_out)
            translated_raw_out = None
        print(f"[pipeline] Processing stem: {docx.stem}")
        run_one(
            docx,
            pdf,
            raw_out,
            json_out,
            tables_out,
            args.python,
            banners_out=banners_out,
            cover_out=cover_out,
            translate_spanish=args.translate_spanish,
            translated_raw_out=translated_raw_out,
            skip_tables=args.skip_tables,
            skip_banners=args.skip_banners,
            skip_cover=args.skip_cover,
            tomas_mode=args.tomas_mode,
            tomas_locale=args.tomas_locale,
            tomas_register=args.tomas_register,
            tomas_model=args.tomas_model,
            tomas_reasoning_effort=args.tomas_reasoning_effort,
            tomas_temperature=args.tomas_temperature,
            tomas_max_output_tokens=tomas_max_tokens,
            tomas_glossary=tomas_glossary,
            tomas_scale_map=tomas_scale_map,
            tomas_strict=(not args.no_tomas_strict),
        )

    print("[pipeline] Batch processing complete.")


if __name__ == "__main__":
    pause = should_auto_pause()
    try:
        main()
    except Exception as exc:
        print(f"[pipeline] ERROR: {exc}", file=sys.stderr)
        if pause:
            pause_before_exit()
        raise
    if pause:
        pause_before_exit()
