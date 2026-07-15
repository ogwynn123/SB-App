#!/usr/bin/env python3
"""Dual-channel TOMAS pipeline: phone + sms DOCX/PDF to Spanish JSON outputs."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
_wincross_candidates = [
    BASE_DIR / "wincross_table_generator",  # PyInstaller one-file extraction layout (new)
    BASE_DIR / "wincrossTableGenerator",  # PyInstaller one-file extraction layout
    BASE_DIR.parent / "wincross_table_generator",  # sibling layout under pipelines/
    BASE_DIR.parent / "wincrossTableGenerator",  # source tree layout
    BASE_DIR.parent / "pipelines" / "wincross_table_generator",  # source tree root layout
]
WINCROSS_DIR = next((p for p in _wincross_candidates if p.exists()), _wincross_candidates[0])
if str(WINCROSS_DIR) not in sys.path:
    sys.path.insert(0, str(WINCROSS_DIR))

try:
    import survey_pipeline as pipeline_core
except Exception as exc:  # pragma: no cover - import guard
    raise SystemExit(f"Failed to import survey pipeline core: {exc}") from exc


OPS_LINE_RE = re.compile(
    r"^\s*("
    r"If\b.*\b(skip|go to|goto|terminate)\b.*|"
    r"Skip\s+to\b.*|"
    r"Go\s+to\b.*|"
    r"TERMINATE\b.*|"
    r"Programmer\s+note:.*|"
    r"Interviewer\s+note:.*|"
    r"Routing\s+note:.*|"
    r"Logic\s+note:.*|"
    r"Quota\s+note:.*|"
    r"Soft\s+check:.*|"
    r"Hard\s+check:.*"
    r")\s*$",
    re.IGNORECASE,
)
ONLY_BRACKET_TAGS_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)+$")


@dataclass(frozen=True)
class ChannelOutputs:
    raw_en: Path
    raw_es: Path
    json_es: Path
    json_en: Path | None


@dataclass(frozen=True)
class ChannelDocxOutputs:
    docx_es: Path
    report_json: Path


@dataclass(frozen=True)
class ChannelJob:
    name: str
    mode: str
    docx: Path
    pdf: Path
    outputs: ChannelOutputs


def _is_ops_line(line: str) -> bool:
    return bool(OPS_LINE_RE.match(line) or ONLY_BRACKET_TAGS_RE.match(line))


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def _dominant_variant(variants: Counter[str]) -> str:
    best = sorted(variants.items(), key=lambda item: (-item[1], item[0]))
    return best[0][0]


def _collect_source_to_translation(src_lines: list[str], out_lines: list[str]) -> dict[str, Counter[str]]:
    mapping: dict[str, Counter[str]] = defaultdict(Counter)
    for src_raw, out_raw in zip(src_lines, out_lines):
        src = src_raw.rstrip("\r\n")
        if not src.strip() or _is_ops_line(src):
            continue
        out = out_raw.rstrip("\r\n")
        mapping[src][out] += 1
    return mapping


_PARALLEL_SOURCE_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "delivery_wrapper",
        "phone_tell",
        re.compile(
            r"^\s*(?:now\s+)?(?:let me|i(?:'m| am)?(?:\s+going\s+to)?|i(?:'ll| will))\s+"
            r"(?:tell(?:\s+you)?|talk(?:\s+to\s+you)?)\s+(?:about\s+)?(?P<body>.+?)\s*$",
            re.IGNORECASE,
        ),
    ),
    (
        "delivery_wrapper",
        "phone_read",
        re.compile(
            r"^\s*(?:now\s+)?(?:let me|i(?:'m| am)?(?:\s+going\s+to)?|i(?:'ll| will))\s+"
            r"read(?:\s+(?:you|to\s+you))?\s+(?:about\s+)?(?P<body>.+?)\s*$",
            re.IGNORECASE,
        ),
    ),
    (
        "delivery_wrapper",
        "sms_read",
        re.compile(
            r"^\s*(?:now\s+)?you(?:'ll| will)\s+read\s+(?:about\s+)?(?P<body>.+?)\s*$",
            re.IGNORECASE,
        ),
    ),
]

_PARALLEL_TARGET_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "phone_tell": [
        re.compile(
            r"^(?P<wrapper>\s*(?:ahora\s+)?(?:le\s+)?(?:voy(?:\s+a)?|quiero|vengo\s+a)\s+"
            r"(?:decir(?:le)?|hablar(?:le)?|contar(?:le)?)\s+(?:de|sobre|acerca\s+de)\s+)"
            r"(?P<body>.+?)\s*$",
            re.IGNORECASE,
        )
    ],
    "phone_read": [
        re.compile(
            r"^(?P<wrapper>\s*(?:ahora\s+)?(?:le\s+)?(?:voy(?:\s+a)?|quiero|vengo\s+a)\s+"
            r"leer(?:le)?\s+(?:de|sobre|acerca\s+de)?\s*)"
            r"(?P<body>.+?)\s*$",
            re.IGNORECASE,
        )
    ],
    "sms_read": [
        re.compile(
            r"^(?P<wrapper>\s*(?:ahora\s+)?(?:(?:usted\s+)?leer[aá]|(?:usted\s+)?va\s+a\s+leer)\s+"
            r"(?:de|sobre|acerca\s+de)?\s*)"
            r"(?P<body>.+?)\s*$",
            re.IGNORECASE,
        )
    ],
}


def _normalize_parallel_text(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.casefold()
    folded = re.sub(r"[^\w\s]", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def _parallel_source_info(line: str) -> dict[str, str] | None:
    for family, role, pattern in _PARALLEL_SOURCE_PATTERNS:
        match = pattern.match(line)
        if not match:
            continue
        body = match.group("body").strip()
        key = _normalize_parallel_text(body)
        if not key:
            return None
        return {
            "family": family,
            "role": role,
            "body": body,
            "key": key,
        }
    return None


def _parallel_target_info(line: str, *, role: str) -> dict[str, str] | None:
    for pattern in _PARALLEL_TARGET_PATTERNS.get(role, []):
        match = pattern.match(line)
        if not match:
            continue
        wrapper = match.group("wrapper")
        body = match.group("body").strip()
        if not body:
            return None
        return {
            "wrapper": wrapper,
            "body": body,
            "key": _normalize_parallel_text(body),
        }
    return None


def _apply_parallel_delivery_consistency(
    *,
    phone_src_lines: list[str],
    phone_es_lines: list[str],
    sms_src_lines: list[str],
    sms_es_lines: list[str],
    prefer: str,
) -> dict[str, int]:
    phone_candidates: dict[tuple[str, str], list[int]] = defaultdict(list)
    sms_candidates: dict[tuple[str, str], list[int]] = defaultdict(list)
    phone_info_by_idx: dict[int, dict[str, str]] = {}
    sms_info_by_idx: dict[int, dict[str, str]] = {}

    def collect(
        src_lines: list[str],
        bucket: dict[tuple[str, str], list[int]],
        info_by_idx: dict[int, dict[str, str]],
    ) -> None:
        for idx, src_raw in enumerate(src_lines):
            src = src_raw.rstrip("\r\n")
            if not src.strip() or _is_ops_line(src):
                continue
            info = _parallel_source_info(src)
            if not info:
                continue
            key = (info["family"], info["key"])
            bucket[key].append(idx)
            info_by_idx[idx] = info

    collect(phone_src_lines, phone_candidates, phone_info_by_idx)
    collect(sms_src_lines, sms_candidates, sms_info_by_idx)

    shared_keys = set(phone_candidates).intersection(sms_candidates)
    harmonized_pairs = 0
    already_parallel_pairs = 0
    changed_phone = 0
    changed_sms = 0

    for key in shared_keys:
        phone_indices = phone_candidates[key]
        sms_indices = sms_candidates[key]
        if len(phone_indices) != 1 or len(sms_indices) != 1:
            continue

        phone_idx = phone_indices[0]
        sms_idx = sms_indices[0]
        phone_info = phone_info_by_idx[phone_idx]
        sms_info = sms_info_by_idx[sms_idx]

        phone_out = _parallel_target_info(
            phone_es_lines[phone_idx].rstrip("\r\n"),
            role=phone_info["role"],
        )
        sms_out = _parallel_target_info(
            sms_es_lines[sms_idx].rstrip("\r\n"),
            role=sms_info["role"],
        )
        if not phone_out or not sms_out:
            continue

        if phone_out["key"] == sms_out["key"]:
            already_parallel_pairs += 1
            continue

        if prefer == "phone":
            new_sms = sms_out["wrapper"] + phone_out["body"]
            if new_sms != sms_es_lines[sms_idx].rstrip("\r\n"):
                sms_es_lines[sms_idx] = new_sms + _line_ending(sms_es_lines[sms_idx])
                changed_sms += 1
                harmonized_pairs += 1
        else:
            new_phone = phone_out["wrapper"] + sms_out["body"]
            if new_phone != phone_es_lines[phone_idx].rstrip("\r\n"):
                phone_es_lines[phone_idx] = new_phone + _line_ending(phone_es_lines[phone_idx])
                changed_phone += 1
                harmonized_pairs += 1

    return {
        "shared_parallel_source_lines": len(shared_keys),
        "already_parallel_pairs": already_parallel_pairs,
        "harmonized_pairs": harmonized_pairs,
        "changed_phone_lines": changed_phone,
        "changed_sms_lines": changed_sms,
    }


def _build_json_from_raw(*, raw_input: Path, json_out: Path, py_exe: str) -> None:
    converter = WINCROSS_DIR / "surveyConvertJSON.py"
    if not converter.exists():
        raise SystemExit(f"Required script not found: {converter}")
    pipeline_core.run_script(
        converter,
        ["--input", str(raw_input), "--out", str(json_out)],
        py_exe,
        on_message=None,
    )


BRACKET_TAG_RE = re.compile(r"\[[^\]]+\]")
ONLY_TAG_RE = re.compile(r"^\s*(?:\[[^\]]+\]\s*)+$")
ENGLISH_HINT_RE = re.compile(
    r"\b("
    r"the|and|you|your|with|from|will|would|now|more|some|other|issue|issues|talk|read|"
    r"if|when|what|which|who|why|how|don'?t|can'?t|none|refused"
    r")\b",
    re.IGNORECASE,
)


def _normalize_compare_text(text: str) -> str:
    s = BRACKET_TAG_RE.sub(" ", text)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _extract_text_fields(obj: Any, *, path: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for key, val in obj.items():
            child = f"{path}.{key}" if path else key
            if key in {"text", "item_text"} and isinstance(val, str):
                out[child] = val
            nested = _extract_text_fields(val, path=child)
            if nested:
                out.update(nested)
        return out
    if isinstance(obj, list):
        for idx, val in enumerate(obj):
            child = f"{path}[{idx}]"
            nested = _extract_text_fields(val, path=child)
            if nested:
                out.update(nested)
        return out
    return out


def _json_english_tokens(text: str) -> list[str]:
    return [m.group(0).lower() for m in ENGLISH_HINT_RE.finditer(BRACKET_TAG_RE.sub(" ", text))]


def _write_json_compare_report(
    *,
    json_en: Path,
    json_es: Path,
    report_out: Path,
) -> dict[str, int]:
    en_obj = json.loads(json_en.read_text(encoding="utf-8", errors="replace"))
    es_obj = json.loads(json_es.read_text(encoding="utf-8", errors="replace"))

    en_fields = _extract_text_fields(en_obj)
    es_fields = _extract_text_fields(es_obj)
    shared_paths = sorted(set(en_fields).intersection(es_fields))

    suspicious: list[dict[str, object]] = []
    unchanged_english_like = 0
    english_like_in_es = 0

    for path in shared_paths:
        en_text = en_fields[path]
        es_text = es_fields[path]
        if not es_text.strip() or ONLY_TAG_RE.match(es_text):
            continue
        en_hits = _json_english_tokens(en_text)
        es_hits = _json_english_tokens(es_text)
        if _normalize_compare_text(en_text) == _normalize_compare_text(es_text) and len(en_hits) >= 2:
            unchanged_english_like += 1
            suspicious.append(
                {
                    "kind": "unchanged_english_like",
                    "path": path,
                    "english_tokens": sorted(set(en_hits)),
                    "en_text": en_text,
                    "es_text": es_text,
                }
            )
            continue
        if len(es_hits) >= 3:
            english_like_in_es += 1
            suspicious.append(
                {
                    "kind": "english_like_in_spanish_field",
                    "path": path,
                    "english_tokens": sorted(set(es_hits)),
                    "en_text": en_text,
                    "es_text": es_text,
                }
            )

    payload = {
        "summary": {
            "shared_text_fields": len(shared_paths),
            "unchanged_english_like": unchanged_english_like,
            "english_like_in_spanish_fields": english_like_in_es,
            "suspicious_total": len(suspicious),
        },
        "suspicious": suspicious,
    }
    if report_out.parent and not report_out.parent.exists():
        report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "shared_text_fields": len(shared_paths),
        "unchanged_english_like": unchanged_english_like,
        "english_like_in_spanish_fields": english_like_in_es,
        "suspicious_total": len(suspicious),
    }


def _enforce_cross_channel_consistency(
    *,
    phone_outputs: ChannelOutputs,
    sms_outputs: ChannelOutputs,
    prefer: str,
) -> dict[str, int]:
    phone_src_lines = phone_outputs.raw_en.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    phone_es_lines = phone_outputs.raw_es.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    sms_src_lines = sms_outputs.raw_en.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    sms_es_lines = sms_outputs.raw_es.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

    if len(phone_src_lines) != len(phone_es_lines):
        raise SystemExit(
            "Cannot enforce cross consistency: phone RAW.en and RAW.es line counts differ "
            f"({len(phone_src_lines)} vs {len(phone_es_lines)})."
        )
    if len(sms_src_lines) != len(sms_es_lines):
        raise SystemExit(
            "Cannot enforce cross consistency: sms RAW.en and RAW.es line counts differ "
            f"({len(sms_src_lines)} vs {len(sms_es_lines)})."
        )

    phone_map_counts = _collect_source_to_translation(phone_src_lines, phone_es_lines)
    sms_map_counts = _collect_source_to_translation(sms_src_lines, sms_es_lines)
    phone_map = {src: _dominant_variant(variants) for src, variants in phone_map_counts.items()}
    sms_map = {src: _dominant_variant(variants) for src, variants in sms_map_counts.items()}

    shared_sources = set(phone_map).intersection(sms_map)
    mismatched_sources = {src for src in shared_sources if phone_map[src] != sms_map[src]}
    print(
        "[tomas-pipeline] Cross consistency check: "
        f"{len(shared_sources)} shared substantive source lines, "
        f"{len(mismatched_sources)} mismatch(es)."
    )

    preferred_map = phone_map if prefer == "phone" else sms_map
    fallback_map = sms_map if prefer == "phone" else phone_map
    canonical_by_source: dict[str, str] = dict(preferred_map)
    for src, out in fallback_map.items():
        canonical_by_source.setdefault(src, out)

    def rewrite(src_lines: list[str], out_lines: list[str]) -> int:
        changed = 0
        for idx, (src_raw, out_raw) in enumerate(zip(src_lines, out_lines)):
            src = src_raw.rstrip("\r\n")
            if not src.strip() or _is_ops_line(src):
                continue
            target = canonical_by_source.get(src)
            if target is None:
                continue
            current = out_raw.rstrip("\r\n")
            if current == target:
                continue
            out_lines[idx] = target + _line_ending(out_raw)
            changed += 1
        return changed

    changed_phone = rewrite(phone_src_lines, phone_es_lines)
    changed_sms = rewrite(sms_src_lines, sms_es_lines)

    parallel_report = _apply_parallel_delivery_consistency(
        phone_src_lines=phone_src_lines,
        phone_es_lines=phone_es_lines,
        sms_src_lines=sms_src_lines,
        sms_es_lines=sms_es_lines,
        prefer=prefer,
    )
    changed_phone += parallel_report["changed_phone_lines"]
    changed_sms += parallel_report["changed_sms_lines"]

    if changed_phone:
        phone_outputs.raw_es.write_text("".join(phone_es_lines), encoding="utf-8", newline="")
    if changed_sms:
        sms_outputs.raw_es.write_text("".join(sms_es_lines), encoding="utf-8", newline="")

    print(
        "[tomas-pipeline] Cross consistency applied: "
        f"phone lines changed={changed_phone}, sms lines changed={changed_sms}."
    )
    if parallel_report["shared_parallel_source_lines"]:
        print(
            "[tomas-pipeline] Parallel delivery alignment: "
            f"shared candidates={parallel_report['shared_parallel_source_lines']}, "
            f"already parallel={parallel_report['already_parallel_pairs']}, "
            f"harmonized={parallel_report['harmonized_pairs']}."
        )

    return {
        "shared_source_lines": len(shared_sources),
        "mismatched_source_lines": len(mismatched_sources),
        "changed_phone_lines": changed_phone,
        "changed_sms_lines": changed_sms,
        "shared_parallel_source_lines": parallel_report["shared_parallel_source_lines"],
        "already_parallel_pairs": parallel_report["already_parallel_pairs"],
        "harmonized_parallel_pairs": parallel_report["harmonized_pairs"],
    }


def _resolve_channel_outputs(
    *,
    channel: str,
    docx: Path,
    out_dir: Path,
    raw_en_out: str | None,
    raw_es_out: str | None,
    json_out: str | None,
    json_en_out: str | None,
    emit_json_en: bool,
) -> ChannelOutputs:
    stem = docx.stem
    default_prefix = f"{stem}.{channel}"

    raw_en = Path(raw_en_out) if raw_en_out else out_dir / f"{default_prefix}.RAW.en.txt"
    raw_es = Path(raw_es_out) if raw_es_out else out_dir / f"{default_prefix}.RAW.es.txt"
    json_es = Path(json_out) if json_out else out_dir / f"{default_prefix}.JSON.es.json"
    json_en = None
    if emit_json_en:
        json_en = Path(json_en_out) if json_en_out else out_dir / f"{default_prefix}.JSON.en.json"
    return ChannelOutputs(raw_en=raw_en, raw_es=raw_es, json_es=json_es, json_en=json_en)


def _resolve_channel_docx_outputs(
    *,
    channel: str,
    docx: Path,
    out_dir: Path,
    docx_es_out: str | None,
    report_out: str | None,
) -> ChannelDocxOutputs:
    stem = docx.stem
    default_prefix = f"{stem}.{channel}"
    docx_es = Path(docx_es_out) if docx_es_out else out_dir / f"{default_prefix}.es.docx"
    report_json = Path(report_out) if report_out else docx_es.with_suffix(docx_es.suffix + ".replace_report.json")
    return ChannelDocxOutputs(docx_es=docx_es, report_json=report_json)


def _validate_inputs(paths: list[Path]) -> None:
    missing = [p for p in paths if not p.exists()]
    if missing:
        joined = "\n".join(f"- {p}" for p in missing)
        raise SystemExit(f"Required input file(s) not found:\n{joined}")


def _resolve_tomas_translate_script() -> Path:
    candidates = [
        BASE_DIR / "tomas_translate.py",
        BASE_DIR / "thomas_in_a_box" / "tomas_translate.py",
        BASE_DIR.parent / "tomasInaBox" / "tomas_translate.py",
    ]
    return next((p for p in candidates if p.exists()), candidates[0])


def _resolve_wincross_script(name: str) -> Path:
    return WINCROSS_DIR / name


def _browser_packet_path(raw_en: Path) -> Path:
    return raw_en.with_name(f"{raw_en.name}.browser_gpt_request.txt")


def _prepare_channel_raw(
    job: ChannelJob,
    *,
    py_exe: str,
) -> None:
    unformatter = _resolve_wincross_script("survey_unformatter.py")
    if not unformatter.exists():
        raise SystemExit(f"Required script not found: {unformatter}")
    if job.outputs.raw_en.parent and not job.outputs.raw_en.parent.exists():
        job.outputs.raw_en.parent.mkdir(parents=True, exist_ok=True)
    step_args = ["--docx", str(job.docx), "--output", str(job.outputs.raw_en)]
    if job.pdf:
        step_args.extend(["--pdf", str(job.pdf)])
    pipeline_core.run_script(unformatter, step_args, py_exe, on_message=None)


def _export_browser_gpt_packet(
    *,
    raw_en: Path,
    packet_out: Path,
    py_exe: str,
    mode: str,
    locale: str,
    register: str,
    glossary_path: Path | None,
    scale_map_path: Path | None,
) -> None:
    tomas_script = _resolve_tomas_translate_script()
    if not tomas_script.exists():
        raise SystemExit(f"Required script not found: {tomas_script}")
    args = [
        str(raw_en),
        "--browser-gpt-packet-out",
        str(packet_out),
        "--mode",
        mode,
        "--locale",
        locale,
        "--register",
        register,
    ]
    if glossary_path is not None:
        args.extend(["--glossary", str(glossary_path)])
    if scale_map_path is not None:
        args.extend(["--scale-map", str(scale_map_path)])
    pipeline_core.run_script(tomas_script, args, py_exe, on_message=None)


def _validate_existing_raw_translation(
    *,
    raw_en: Path,
    raw_es: Path,
    py_exe: str,
    mode: str,
    locale: str,
    register: str,
    glossary_path: Path | None,
    scale_map_path: Path | None,
    strict: bool,
) -> None:
    tomas_script = _resolve_tomas_translate_script()
    if not tomas_script.exists():
        raise SystemExit(f"Required script not found: {tomas_script}")
    if not raw_es.exists():
        raise SystemExit(f"Spanish RAW file not found: {raw_es}")
    args = [
        str(raw_en),
        "--validate-existing-output",
        str(raw_es),
        "-o",
        str(raw_es),
        "--mode",
        mode,
        "--locale",
        locale,
        "--register",
        register,
    ]
    if glossary_path is not None:
        args.extend(["--glossary", str(glossary_path)])
    if scale_map_path is not None:
        args.extend(["--scale-map", str(scale_map_path)])
    if not strict:
        args.append("--no-strict")
    pipeline_core.run_script(tomas_script, args, py_exe, on_message=None)


def _quote_cmd_part(part: str) -> str:
    return f'"{part}"' if any(ch.isspace() for ch in part) else part


def _is_frozen_runtime() -> bool:
    return bool(getattr(sys, "frozen", False))


def _missing_modules_for_python(py_exe: str, modules: list[str]) -> list[str]:
    probe_code = (
        "import importlib.util, json; "
        f"mods = {modules!r}; "
        "missing = [m for m in mods if importlib.util.find_spec(m) is None]; "
        "print(json.dumps(missing))"
    )
    try:
        probe = subprocess.run(
            [py_exe, "-c", probe_code],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"Python interpreter not found: {py_exe}") from exc
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "").strip()
        if not details:
            details = str(exc)
        raise SystemExit(
            "Failed while checking Python dependencies for TOMAS pipeline "
            f"with interpreter {py_exe}:\n{details}"
        ) from exc

    raw = probe.stdout.strip()
    try:
        parsed = json.loads(raw) if raw else []
    except Exception as exc:
        raise SystemExit(f"Dependency check returned invalid output: {raw!r}") from exc
    return [m for m in parsed if isinstance(m, str)]


def _preflight_runtime_dependencies(py_exe: str) -> None:
    # Packaged EXEs already contain the required runtime modules, and the worker
    # executable is not a Python interpreter that can answer `-c ...` probes.
    if _is_frozen_runtime():
        return

    required_modules = ["docx", "pdfplumber", "openai"]
    package_name_by_module = {
        "docx": "python-docx",
        "pdfplumber": "pdfplumber",
        "openai": "openai",
    }
    missing_modules = _missing_modules_for_python(py_exe, required_modules)
    if not missing_modules:
        return

    missing_packages = [package_name_by_module.get(mod, mod) for mod in missing_modules]
    install_cmd = f"{_quote_cmd_part(py_exe)} -m pip install {' '.join(sorted(set(missing_packages)))}"
    joined_modules = ", ".join(missing_modules)
    raise SystemExit(
        "Missing required Python package(s) for TOMAS pipeline: "
        f"{joined_modules}\nInstall them with:\n{install_cmd}"
    )


def _run_channel(
    job: ChannelJob,
    *,
    py_exe: str,
    model: str,
    reasoning_effort: str,
    temperature: float,
    max_output_tokens: int | None,
    locale: str,
    register: str,
    glossary_path: Path | None,
    scale_map_path: Path | None,
    strict: bool,
) -> None:
    print(f"[tomas-pipeline] Running channel '{job.name}' ({job.mode})")

    # survey_pipeline.run_one requires a tables_out path even when skip_tables=True.
    tables_dummy = job.outputs.json_es.with_name(f"{job.outputs.json_es.stem}.TABLES.autogen.txt")

    pipeline_core.run_one(
        docx=job.docx,
        pdf=job.pdf,
        raw_out=job.outputs.raw_en,
        json_out=job.outputs.json_es,
        tables_out=tables_dummy,
        py_exe=py_exe,
        raw_input=None,
        on_message=None,
        translate_spanish=True,
        translated_raw_out=job.outputs.raw_es,
        skip_tables=True,
        tomas_mode=job.mode,
        tomas_locale=locale,
        tomas_register=register,
        tomas_model=model,
        tomas_reasoning_effort=reasoning_effort,
        tomas_temperature=temperature,
        tomas_max_output_tokens=max_output_tokens,
        tomas_glossary=glossary_path,
        tomas_scale_map=scale_map_path,
        tomas_strict=strict,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run TOMAS Spanish pipeline for both phone and SMS instruments in one command. "
            "Inputs: 4 files (phone docx/pdf + sms docx/pdf). "
            "Outputs: phone JSON.es + sms JSON.es (plus RAW intermediates)."
        )
    )

    parser.add_argument("--phone-docx", required=True)
    parser.add_argument("--phone-pdf", required=True)
    parser.add_argument("--sms-docx", required=True)
    parser.add_argument("--sms-pdf", required=True)

    parser.add_argument("--out-dir", default=str(BASE_DIR / "outputs"))

    parser.add_argument("--phone-raw-en-out")
    parser.add_argument("--phone-raw-es-out")
    parser.add_argument("--phone-json-out")
    parser.add_argument("--phone-json-en-out")

    parser.add_argument("--sms-raw-en-out")
    parser.add_argument("--sms-raw-es-out")
    parser.add_argument("--sms-json-out")
    parser.add_argument("--sms-json-en-out")
    parser.add_argument(
        "--no-json-en",
        action="store_true",
        help="Disable generation of channel JSON.en files from RAW.en for QA/debug comparisons.",
    )
    parser.add_argument(
        "--no-json-compare",
        action="store_true",
        help="Disable JSON.en vs JSON.es QA compare reports.",
    )

    parser.add_argument(
        "--build-formatted-docx",
        action="store_true",
        help="After translation, rebuild formatted Spanish DOCX outputs using RAW.en/RAW.es mappings.",
    )
    parser.add_argument(
        "--prepare-browser-gpt",
        action="store_true",
        help="Generate RAW.en files plus browser-GPT request packets, then stop before translation.",
    )
    parser.add_argument(
        "--resume-browser-gpt",
        action="store_true",
        help="Skip API translation and finish the pipeline from existing RAW.es files.",
    )
    parser.add_argument("--phone-docx-es-out", help="Optional output path for formatted Spanish phone DOCX.")
    parser.add_argument("--phone-docx-report-out", help="Optional JSON report path for phone DOCX replacements.")
    parser.add_argument("--sms-docx-es-out", help="Optional output path for formatted Spanish SMS DOCX.")
    parser.add_argument("--sms-docx-report-out", help="Optional JSON report path for SMS DOCX replacements.")

    parser.add_argument("--phone-mode", choices=["cati", "sms"], default="cati")
    parser.add_argument("--sms-mode", choices=["cati", "sms"], default="sms")

    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument(
        "--reasoning-effort",
        choices=["minimal", "low", "medium", "high", "xhigh"],
        default="high",
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-output-tokens", type=int, default=0, help="0 means SDK default")
    parser.add_argument("--locale", default="es-US")
    parser.add_argument("--register", default="usted")
    parser.add_argument("--api-key", default="", help="Optional OpenAI API key override for this run.")
    parser.add_argument("--glossary", help="Path to glossary JSON")
    parser.add_argument("--scale-map", help="Path to scale-map JSON")
    parser.add_argument("--no-strict", action="store_true", help="Disable strict TOMAS validation")
    parser.add_argument(
        "--enforce-cross-consistency",
        action="store_true",
        help="Force identical Spanish when phone/SMS source line text is identical.",
    )
    parser.add_argument(
        "--consistency-prefer",
        choices=["phone", "sms"],
        default="phone",
        help="Preferred channel wording if cross-consistency rewrites are needed.",
    )

    parser.add_argument(
        "--manifest-out",
        default="",
        help="Optional JSON manifest path. Defaults to <out-dir>/tomas_pipeline_manifest.json",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.prepare_browser_gpt and args.resume_browser_gpt:
        raise SystemExit("Choose only one of --prepare-browser-gpt or --resume-browser-gpt.")

    if args.api_key:
        os.environ["OPENAI_API_KEY"] = args.api_key

    _preflight_runtime_dependencies(args.python)

    phone_docx = Path(args.phone_docx)
    phone_pdf = Path(args.phone_pdf)
    sms_docx = Path(args.sms_docx)
    sms_pdf = Path(args.sms_pdf)

    _validate_inputs([phone_docx, phone_pdf, sms_docx, sms_pdf])

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    glossary_path = Path(args.glossary) if args.glossary else None
    scale_map_path = Path(args.scale_map) if args.scale_map else None
    if glossary_path and not glossary_path.exists():
        raise SystemExit(f"Glossary file not found: {glossary_path}")
    if scale_map_path and not scale_map_path.exists():
        raise SystemExit(f"Scale-map file not found: {scale_map_path}")

    phone_outputs = _resolve_channel_outputs(
        channel="phone",
        docx=phone_docx,
        out_dir=out_dir,
        raw_en_out=args.phone_raw_en_out,
        raw_es_out=args.phone_raw_es_out,
        json_out=args.phone_json_out,
        json_en_out=args.phone_json_en_out,
        emit_json_en=(not args.no_json_en),
    )
    sms_outputs = _resolve_channel_outputs(
        channel="sms",
        docx=sms_docx,
        out_dir=out_dir,
        raw_en_out=args.sms_raw_en_out,
        raw_es_out=args.sms_raw_es_out,
        json_out=args.sms_json_out,
        json_en_out=args.sms_json_en_out,
        emit_json_en=(not args.no_json_en),
    )

    max_tokens = None if args.max_output_tokens == 0 else int(args.max_output_tokens)

    phone_job = ChannelJob(
        name="phone",
        mode=args.phone_mode,
        docx=phone_docx,
        pdf=phone_pdf,
        outputs=phone_outputs,
    )
    sms_job = ChannelJob(
        name="sms",
        mode=args.sms_mode,
        docx=sms_docx,
        pdf=sms_pdf,
        outputs=sms_outputs,
    )

    if args.prepare_browser_gpt:
        for job in (phone_job, sms_job):
            _prepare_channel_raw(job, py_exe=args.python)

        phone_packet = _browser_packet_path(phone_outputs.raw_en)
        sms_packet = _browser_packet_path(sms_outputs.raw_en)
        _export_browser_gpt_packet(
            raw_en=phone_outputs.raw_en,
            packet_out=phone_packet,
            py_exe=args.python,
            mode=phone_job.mode,
            locale=args.locale,
            register=args.register,
            glossary_path=glossary_path,
            scale_map_path=scale_map_path,
        )
        _export_browser_gpt_packet(
            raw_en=sms_outputs.raw_en,
            packet_out=sms_packet,
            py_exe=args.python,
            mode=sms_job.mode,
            locale=args.locale,
            register=args.register,
            glossary_path=glossary_path,
            scale_map_path=scale_map_path,
        )

        manifest_path = Path(args.manifest_out) if args.manifest_out else (out_dir / "tomas_browser_gpt_manifest.json")
        manifest = {
            "mode": "prepare_browser_gpt",
            "phone": {
                "raw_en": str(phone_outputs.raw_en),
                "expected_raw_es": str(phone_outputs.raw_es),
                "browser_gpt_packet": str(phone_packet),
            },
            "sms": {
                "raw_en": str(sms_outputs.raw_en),
                "expected_raw_es": str(sms_outputs.raw_es),
                "browser_gpt_packet": str(sms_packet),
            },
            "next_step": (
                "Use the browser-GPT request files, save the translated outputs to the expected RAW.es paths, "
                "then run this pipeline again with --resume-browser-gpt."
            ),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        print("[tomas-pipeline] Browser-GPT prep complete.")
        print(f"[tomas-pipeline] Phone RAW.en: {phone_outputs.raw_en}")
        print(f"[tomas-pipeline] Phone browser packet: {phone_packet}")
        print(f"[tomas-pipeline] Expected phone RAW.es: {phone_outputs.raw_es}")
        print(f"[tomas-pipeline] SMS RAW.en: {sms_outputs.raw_en}")
        print(f"[tomas-pipeline] SMS browser packet: {sms_packet}")
        print(f"[tomas-pipeline] Expected SMS RAW.es: {sms_outputs.raw_es}")
        print(f"[tomas-pipeline] Manifest: {manifest_path}")
        return 0

    if args.resume_browser_gpt:
        for job in (phone_job, sms_job):
            if not job.outputs.raw_en.exists():
                _prepare_channel_raw(job, py_exe=args.python)
        _validate_existing_raw_translation(
            raw_en=phone_outputs.raw_en,
            raw_es=phone_outputs.raw_es,
            py_exe=args.python,
            mode=phone_job.mode,
            locale=args.locale,
            register=args.register,
            glossary_path=glossary_path,
            scale_map_path=scale_map_path,
            strict=(not args.no_strict),
        )
        _validate_existing_raw_translation(
            raw_en=sms_outputs.raw_en,
            raw_es=sms_outputs.raw_es,
            py_exe=args.python,
            mode=sms_job.mode,
            locale=args.locale,
            register=args.register,
            glossary_path=glossary_path,
            scale_map_path=scale_map_path,
            strict=(not args.no_strict),
        )
    else:
        _run_channel(
            phone_job,
            py_exe=args.python,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            temperature=args.temperature,
            max_output_tokens=max_tokens,
            locale=args.locale,
            register=args.register,
            glossary_path=glossary_path,
            scale_map_path=scale_map_path,
            strict=(not args.no_strict),
        )
        _run_channel(
            sms_job,
            py_exe=args.python,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            temperature=args.temperature,
            max_output_tokens=max_tokens,
            locale=args.locale,
            register=args.register,
            glossary_path=glossary_path,
            scale_map_path=scale_map_path,
            strict=(not args.no_strict),
        )

    consistency_report: dict[str, int] | None = None
    if args.enforce_cross_consistency:
        consistency_report = _enforce_cross_channel_consistency(
            phone_outputs=phone_outputs,
            sms_outputs=sms_outputs,
            prefer=args.consistency_prefer,
        )
        if (not args.resume_browser_gpt) and consistency_report["changed_phone_lines"] > 0:
            _build_json_from_raw(raw_input=phone_outputs.raw_es, json_out=phone_outputs.json_es, py_exe=args.python)
        if (not args.resume_browser_gpt) and consistency_report["changed_sms_lines"] > 0:
            _build_json_from_raw(raw_input=sms_outputs.raw_es, json_out=sms_outputs.json_es, py_exe=args.python)

    phone_json_compare_report: str | None = None
    sms_json_compare_report: str | None = None
    phone_json_compare_summary: dict[str, int] | None = None
    sms_json_compare_summary: dict[str, int] | None = None
    if args.resume_browser_gpt:
        _build_json_from_raw(raw_input=phone_outputs.raw_es, json_out=phone_outputs.json_es, py_exe=args.python)
        _build_json_from_raw(raw_input=sms_outputs.raw_es, json_out=sms_outputs.json_es, py_exe=args.python)
    if phone_outputs.json_en is not None:
        _build_json_from_raw(raw_input=phone_outputs.raw_en, json_out=phone_outputs.json_en, py_exe=args.python)
    if sms_outputs.json_en is not None:
        _build_json_from_raw(raw_input=sms_outputs.raw_en, json_out=sms_outputs.json_en, py_exe=args.python)

    if (not args.no_json_compare) and phone_outputs.json_en is not None and sms_outputs.json_en is not None:
        phone_compare_path = Path(str(phone_outputs.json_es) + ".compare_report.json")
        sms_compare_path = Path(str(sms_outputs.json_es) + ".compare_report.json")
        phone_json_compare_summary = _write_json_compare_report(
            json_en=phone_outputs.json_en,
            json_es=phone_outputs.json_es,
            report_out=phone_compare_path,
        )
        sms_json_compare_summary = _write_json_compare_report(
            json_en=sms_outputs.json_en,
            json_es=sms_outputs.json_es,
            report_out=sms_compare_path,
        )
        phone_json_compare_report = str(phone_compare_path)
        sms_json_compare_report = str(sms_compare_path)
        print(
            "[tomas-pipeline] JSON QA compare: "
            f"phone suspicious={phone_json_compare_summary['suspicious_total']}, "
            f"sms suspicious={sms_json_compare_summary['suspicious_total']}"
        )

    phone_docx_outputs: ChannelDocxOutputs | None = None
    sms_docx_outputs: ChannelDocxOutputs | None = None
    phone_docx_report_summary: dict[str, int] | None = None
    sms_docx_report_summary: dict[str, int] | None = None
    if args.build_formatted_docx:
        try:
            from tomas_docx_rebuilder import rebuild_docx, write_report
        except Exception as exc:
            raise SystemExit(f"Failed to import tomas_docx_rebuilder.py: {exc}") from exc

        phone_docx_outputs = _resolve_channel_docx_outputs(
            channel="phone",
            docx=phone_docx,
            out_dir=out_dir,
            docx_es_out=args.phone_docx_es_out,
            report_out=args.phone_docx_report_out,
        )
        sms_docx_outputs = _resolve_channel_docx_outputs(
            channel="sms",
            docx=sms_docx,
            out_dir=out_dir,
            docx_es_out=args.sms_docx_es_out,
            report_out=args.sms_docx_report_out,
        )

        print("[tomas-pipeline] Rebuilding formatted Spanish DOCX outputs...")
        phone_rebuild = rebuild_docx(
            docx_in=phone_docx,
            raw_en=phone_outputs.raw_en,
            raw_es=phone_outputs.raw_es,
            json_en=phone_outputs.json_en,
            json_es=phone_outputs.json_es if phone_outputs.json_en is not None else None,
            docx_out=phone_docx_outputs.docx_es,
        )
        write_report(phone_docx_outputs.report_json, phone_rebuild)

        sms_rebuild = rebuild_docx(
            docx_in=sms_docx,
            raw_en=sms_outputs.raw_en,
            raw_es=sms_outputs.raw_es,
            json_en=sms_outputs.json_en,
            json_es=sms_outputs.json_es if sms_outputs.json_en is not None else None,
            docx_out=sms_docx_outputs.docx_es,
        )
        write_report(sms_docx_outputs.report_json, sms_rebuild)

        phone_docx_report_summary = {
            "matched_segments": phone_rebuild.matched_segments,
            "unmatched_segments": phone_rebuild.unmatched_segments,
            "changed_paragraphs": phone_rebuild.changed_paragraphs,
            "total_paragraphs": phone_rebuild.total_paragraphs,
            "mapping_json_pairs_used": phone_rebuild.mapping.json_pairs_used,
        }
        sms_docx_report_summary = {
            "matched_segments": sms_rebuild.matched_segments,
            "unmatched_segments": sms_rebuild.unmatched_segments,
            "changed_paragraphs": sms_rebuild.changed_paragraphs,
            "total_paragraphs": sms_rebuild.total_paragraphs,
            "mapping_json_pairs_used": sms_rebuild.mapping.json_pairs_used,
        }

        print(
            "[tomas-pipeline] Formatted DOCX ready: "
            f"phone={phone_docx_outputs.docx_es}, sms={sms_docx_outputs.docx_es}"
        )

    manifest_path = Path(args.manifest_out) if args.manifest_out else (out_dir / "tomas_pipeline_manifest.json")
    manifest = {
        "mode": "resume_browser_gpt" if args.resume_browser_gpt else "api_pipeline",
        "phone": {
            "mode": phone_job.mode,
            "docx": str(phone_job.docx),
            "pdf": str(phone_job.pdf),
            "raw_en": str(phone_job.outputs.raw_en),
            "raw_es": str(phone_job.outputs.raw_es),
            "json_es": str(phone_job.outputs.json_es),
            "json_en": str(phone_job.outputs.json_en) if phone_job.outputs.json_en else "",
        },
        "sms": {
            "mode": sms_job.mode,
            "docx": str(sms_job.docx),
            "pdf": str(sms_job.pdf),
            "raw_en": str(sms_job.outputs.raw_en),
            "raw_es": str(sms_job.outputs.raw_es),
            "json_es": str(sms_job.outputs.json_es),
            "json_en": str(sms_job.outputs.json_en) if sms_job.outputs.json_en else "",
        },
        "json_compare": {
            "enabled": bool((not args.no_json_compare) and phone_outputs.json_en is not None and sms_outputs.json_en is not None),
            "phone_report_json": phone_json_compare_report or "",
            "phone_summary": phone_json_compare_summary,
            "sms_report_json": sms_json_compare_report or "",
            "sms_summary": sms_json_compare_summary,
        },
        "formatted_docx": {
            "enabled": bool(args.build_formatted_docx),
            "phone_docx_es": str(phone_docx_outputs.docx_es) if phone_docx_outputs else "",
            "phone_report_json": str(phone_docx_outputs.report_json) if phone_docx_outputs else "",
            "phone_summary": phone_docx_report_summary,
            "sms_docx_es": str(sms_docx_outputs.docx_es) if sms_docx_outputs else "",
            "sms_report_json": str(sms_docx_outputs.report_json) if sms_docx_outputs else "",
            "sms_summary": sms_docx_report_summary,
        },
        "skip_tables": True,
        "translate_spanish": not args.resume_browser_gpt,
        "manual_browser_gpt": bool(args.resume_browser_gpt),
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "enforce_cross_consistency": bool(args.enforce_cross_consistency),
        "consistency_prefer": args.consistency_prefer,
        "cross_consistency_report": consistency_report,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[tomas-pipeline] Complete.")
    print(f"[tomas-pipeline] Phone JSON: {phone_job.outputs.json_es}")
    print(f"[tomas-pipeline] SMS JSON: {sms_job.outputs.json_es}")
    if phone_job.outputs.json_en:
        print(f"[tomas-pipeline] Phone JSON (English): {phone_job.outputs.json_en}")
    if sms_job.outputs.json_en:
        print(f"[tomas-pipeline] SMS JSON (English): {sms_job.outputs.json_en}")
    if phone_json_compare_report and sms_json_compare_report:
        print(f"[tomas-pipeline] Phone JSON compare report: {phone_json_compare_report}")
        print(f"[tomas-pipeline] SMS JSON compare report: {sms_json_compare_report}")
    if phone_docx_outputs and sms_docx_outputs:
        print(f"[tomas-pipeline] Phone DOCX (Spanish): {phone_docx_outputs.docx_es}")
        print(f"[tomas-pipeline] SMS DOCX (Spanish): {sms_docx_outputs.docx_es}")
    print(f"[tomas-pipeline] Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

