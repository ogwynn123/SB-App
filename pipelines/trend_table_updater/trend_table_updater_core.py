from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re


TABLE_HEADER_PATTERN = r"(?:TTREND\d+|TQ[^\r\n^]*)\^\d+[ \t]*(?:\r?$)"
TABLE_HEADER_RE = re.compile(
    rf"^{TABLE_HEADER_PATTERN}",
    re.MULTILINE | re.IGNORECASE,
)
TABLE_START_RE = re.compile(
    rf"(?=^{TABLE_HEADER_PATTERN})",
    re.MULTILINE | re.IGNORECASE,
)
WAVE_RE = re.compile(
    r"^(?P<indent>\s*)(?P<label>[A-Z]+(?:\s+[A-Z]+)?\s+\d{4})"
    r"\^TIMESERIES\s*\((?P<series>\d+)\)(?P<tail>\^.*)$",
    re.IGNORECASE,
)
POSITION_RE = re.compile(r"\^(?P<position>\d+)(?P<tail>,[^\r\n]*)$")
CALC_RE = re.compile(r"(\^CALC\s+)V\d+(\s*-\s*)V\d+", re.IGNORECASE)
ARCHIVE_TITLE_RE = re.compile(r"Trend Table\s*-\s*\[\d{4}\]", re.IGNORECASE)


@dataclass(frozen=True)
class TrendUpdateResult:
    text: str
    updated_tables: int
    skipped_tables: int
    messages: tuple[str, ...]
    prior_series: int
    new_series: int
    new_label: str


def read_glossary_text(path: Path | str) -> tuple[str, str]:
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    for encoding in ("utf-8", "cp1252"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not decode glossary text: {path}")


def write_glossary_text(path: Path | str, text: str, encoding: str = "utf-8-sig") -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding=encoding, newline="") as handle:
        handle.write(text)


def split_table_chunks(text: str) -> list[str]:
    return TABLE_START_RE.split(text)


def _table_title(lines: list[str]) -> str:
    return next(
        (line.strip() for line in lines if "trend table -" in line.casefold()),
        lines[0].strip() if lines else "Unknown trend table",
    )


def _is_trend_table_chunk(chunk: str) -> bool:
    if not TABLE_HEADER_RE.match(chunk):
        return False
    return any("trend table -" in line.casefold() for line in chunk.splitlines())


def _wave_rows(lines: list[str]) -> list[tuple[int, re.Match[str]]]:
    rows: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = WAVE_RE.match(line.rstrip("\r\n"))
        if match:
            rows.append((index, match))
    return rows


def infer_prior_series(text: str, skip_bracketed_year_titles: bool = True) -> int:
    latest_series: list[int] = []
    for chunk in split_table_chunks(text):
        if not _is_trend_table_chunk(chunk):
            continue
        lines = chunk.splitlines(keepends=True)
        title = _table_title(lines)
        if skip_bracketed_year_titles and ARCHIVE_TITLE_RE.search(title):
            continue
        waves = _wave_rows(lines)
        if waves:
            latest_series.append(int(waves[-1][1].group("series")))
    if not latest_series:
        raise ValueError("No trend-table timeseries headers were found.")
    counts = Counter(latest_series)
    return max(counts, key=lambda value: (counts[value], value))


def _response_label(line: str) -> str:
    return line.split("^", 1)[0].strip().casefold()


def _match_net_label(net_label: str, response_labels: set[str]) -> str | None:
    if net_label in response_labels:
        return net_label
    aliases = {
        alias.strip()
        for alias in re.split(r"\s*/\s*", net_label)
        if alias.strip() in response_labels
    }
    return next(iter(aliases)) if len(aliases) == 1 else None


def _replace_position(line: str, new_start: int) -> str:
    ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    content = line[: -len(ending)] if ending else line
    match = POSITION_RE.search(content)
    if not match:
        raise ValueError(f"No vertical position found: {content.strip()}")
    updated = POSITION_RE.sub(
        lambda found: f"^{new_start}{found.group('tail')}",
        content,
    )
    return updated + ending


def _update_table(
    table: str,
    *,
    prior_series: int,
    new_series: int,
    new_label: str,
    skip_bracketed_year_titles: bool,
) -> tuple[str, bool, str]:
    lines = table.splitlines(keepends=True)
    title = _table_title(lines)
    if skip_bracketed_year_titles and ARCHIVE_TITLE_RE.search(title):
        return table, False, f"Skipped archive: {title}"

    waves = _wave_rows(lines)
    if not waves:
        return table, False, f"Skipped; no timeseries headers: {title}"
    wave_index, wave_match = waves[-1]
    last_series = int(wave_match.group("series"))
    if last_series != prior_series:
        return table, False, f"Skipped; latest timeseries is {last_series}: {title}"

    net_index = next(
        (
            index
            for index in range(wave_index + 1, len(lines))
            if lines[index].strip().startswith("NET CHANGE^")
        ),
        None,
    )
    body_end = net_index if net_index is not None else len(lines)
    latest_body = lines[wave_index + 1 : body_end]
    response_indices = [
        index
        for index, line in enumerate(latest_body)
        if re.search(rf"TIMESERIES\s*\({prior_series}\)", line, re.IGNORECASE)
    ]
    if not response_indices:
        raise ValueError(f"No response rows found in the latest wave of {title}")

    positions: list[int] = []
    for index in response_indices:
        match = POSITION_RE.search(latest_body[index].rstrip("\r\n"))
        if not match:
            raise ValueError(f"No vertical position found in {title}: {latest_body[index].strip()}")
        positions.append(int(match.group("position")))
    if len(set(positions)) != 1:
        raise ValueError(f"Latest wave has inconsistent vertical positions in {title}: {positions}")

    old_start = positions[0]
    new_start = old_start + len(response_indices) + 2
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    new_header = (
        f"{wave_match.group('indent')}{new_label}^TIMESERIES ({new_series})"
        f"{wave_match.group('tail')}{newline}"
    )

    new_body: list[str] = []
    new_series_re = re.compile(
        rf"(TIMESERIES\s*\(){prior_series}(\))",
        re.IGNORECASE,
    )
    for line in latest_body:
        cloned = new_series_re.sub(rf"\g<1>{new_series}\2", line)
        if re.search(rf"TIMESERIES\s*\({new_series}\)", cloned, re.IGNORECASE):
            cloned = _replace_position(cloned, new_start)
        new_body.append(cloned)

    latest_rows = [latest_body[index] for index in response_indices]
    labels = [_response_label(line) for line in latest_rows]
    if len(set(labels)) != len(labels):
        raise ValueError(f"Latest wave has duplicate response labels in {title}")
    label_positions = {
        label: (new_start + index + 1, old_start + index + 1)
        for index, label in enumerate(labels)
    }

    if net_index is None:
        separator = next(
            (
                line
                for line in reversed(lines[:wave_index])
                if line.strip().upper() == "^ ^NS,DV"
            ),
            f"{wave_match.group('indent')} ^ ^NS,DV{newline}",
        )
        prefix = list(lines)
        if prefix and not prefix[-1].endswith(("\r", "\n")):
            prefix[-1] += newline
        bridge = [] if latest_body and latest_body[-1].strip().upper() == "^ ^NS,DV" else [separator]
        updated = "".join(prefix + bridge + [new_header] + new_body)
        return (
            updated,
            True,
            f"Updated {len(response_indices)} row(s) without NET rows: {title}",
        )

    net_lines = list(lines[net_index:])
    changed_nets = 0
    for index, line in enumerate(net_lines[1:], start=1):
        if "^CALC" not in line.upper():
            continue
        net_label = _response_label(line)
        label = _match_net_label(net_label, set(label_positions))
        if label is None:
            raise ValueError(f"NET row does not match a response in {title}: {line.strip()}")
        new_v, old_v = label_positions[label]
        updated, count = CALC_RE.subn(
            lambda found: f"{found.group(1)}V{new_v}{found.group(2)}V{old_v}",
            line,
            count=1,
        )
        if count != 1:
            raise ValueError(f"Could not rewrite NET formula in {title}: {line.strip()}")
        net_lines[index] = updated
        changed_nets += 1

    if changed_nets == 0:
        raise ValueError(f"No NET formulas found in {title}")

    updated = "".join(lines[:net_index] + [new_header] + new_body + net_lines)
    return (
        updated,
        True,
        f"Updated {len(response_indices)} row(s) and {changed_nets} NET(s): {title}",
    )


def update_trend_tables(
    text: str,
    *,
    prior_series: int | None,
    new_series: int,
    new_label: str,
    skip_bracketed_year_titles: bool = True,
) -> TrendUpdateResult:
    label = re.sub(r"\s+", " ", str(new_label)).strip().upper()
    if not label:
        raise ValueError("Enter a new wave label.")
    if new_series < 1:
        raise ValueError("New timeseries must be at least 1.")
    effective_prior = (
        infer_prior_series(text, skip_bracketed_year_titles)
        if prior_series is None
        else prior_series
    )
    if effective_prior < 1:
        raise ValueError("Prior timeseries must be at least 1.")
    if new_series == effective_prior:
        raise ValueError("New timeseries must differ from the prior timeseries.")

    output: list[str] = []
    messages: list[str] = []
    updated_count = 0
    skipped_count = 0
    for chunk in split_table_chunks(text):
        if not _is_trend_table_chunk(chunk):
            output.append(chunk)
            continue
        updated, changed, message = _update_table(
            chunk,
            prior_series=effective_prior,
            new_series=new_series,
            new_label=label,
            skip_bracketed_year_titles=skip_bracketed_year_titles,
        )
        output.append(updated)
        messages.append(message)
        if changed:
            updated_count += 1
        else:
            skipped_count += 1

    if updated_count == 0:
        raise ValueError(f"No tables ended at TIMESERIES ({effective_prior}).")
    return TrendUpdateResult(
        text="".join(output),
        updated_tables=updated_count,
        skipped_tables=skipped_count,
        messages=tuple(messages),
        prior_series=effective_prior,
        new_series=new_series,
        new_label=label,
    )


def suggested_output_path(input_path: Path | str, new_label: str) -> Path:
    source = Path(input_path)
    clean_label = re.sub(r"[^A-Za-z0-9]+", " ", new_label).strip().title()
    suffix = source.suffix or ".txt"
    return source.with_name(f"{source.stem} - {clean_label}{suffix}")
