"""
01_profile.py -- Read-only profiling of the MicrosoftDocs-SupportArticles corpus.

Scans a directory tree of Markdown files and reports, without modifying anything:
  - file counts (total, per top-level directory)
  - front-matter presence and key frequency
  - ms.topic value distribution
  - heading counts (per level) and most common heading texts
  - word-count statistics and a histogram
  - empty / small files (below a word-count threshold)
  - files that could not be read or whose front matter failed to parse

Output: a JSON report (full detail) and a Markdown report (human-readable summary)
written to the output directory. Nothing under the input directory is touched.

Usage:
    python scripts/01_profile.py
    python scripts/01_profile.py --input data/raw/MicrosoftDocs-SupportArticles --output data/processed
    python scripts/01_profile.py --min-words 30 --top-n 25
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median

import yaml

# ---------------------------------------------------------------------------
# Paths / defaults
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "raw" / "MicrosoftDocs-SupportArticles"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed"

FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
FRONT_MATTER_KEY_RE = re.compile(r"^([A-Za-z0-9_.]+):", re.MULTILINE)
MS_TOPIC_RE = re.compile(r"^ms\.topic:\s*(.+?)\s*$", re.MULTILINE)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
WORD_RE = re.compile(r"\S+")

WORD_COUNT_BUCKETS = [
    (0, 50, "0-49"),
    (50, 200, "50-199"),
    (200, 500, "200-499"),
    (500, 1500, "500-1499"),
    (1500, 5000, "1500-4999"),
    (5000, None, "5000+"),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FileProfile:
    rel_path: str
    top_level_dir: str
    has_front_matter: bool
    front_matter_keys: list[str]
    front_matter_parse_ok: bool
    ms_topic: str | None
    heading_counts: dict[str, int]  # "H1".."H6" -> count
    top_headings: list[str]  # normalized H2 texts found in this file
    word_count: int
    is_small: bool


@dataclass
class ErrorEntry:
    rel_path: str
    stage: str  # "read" | "front_matter_yaml"
    error: str


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def split_front_matter(text: str) -> tuple[str | None, str]:
    """Return (front_matter_block_or_None, body_text)."""
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def extract_front_matter_keys(fm_block: str) -> list[str]:
    """Regex-based top-level key scan. Robust even if the block isn't valid YAML."""
    return FRONT_MATTER_KEY_RE.findall(fm_block)


def try_parse_yaml(fm_block: str) -> tuple[bool, str | None]:
    """Attempt a real YAML parse, purely to count parse failures. Returns (ok, error_message)."""
    try:
        yaml.safe_load(fm_block)
        return True, None
    except yaml.YAMLError as exc:
        return False, str(exc)


def extract_ms_topic(fm_block: str) -> str | None:
    m = MS_TOPIC_RE.search(fm_block)
    if not m:
        return None
    return m.group(1).strip().strip("'\"")


def extract_headings(body: str) -> tuple[dict[str, int], list[str]]:
    counts = {f"H{i}": 0 for i in range(1, 7)}
    h2_texts: list[str] = []
    for hashes, text in HEADING_RE.findall(body):
        level = len(hashes)
        counts[f"H{level}"] += 1
        if level == 2:
            h2_texts.append(text.strip().lower())
    return counts, h2_texts


def count_words(body: str) -> int:
    return len(WORD_RE.findall(body))


def bucket_for(word_count: int) -> str:
    for low, high, label in WORD_COUNT_BUCKETS:
        if high is None or word_count < high:
            if word_count >= low:
                return label
    return WORD_COUNT_BUCKETS[-1][2]


# ---------------------------------------------------------------------------
# Per-file profiling
# ---------------------------------------------------------------------------

def profile_file(path: Path, root: Path, min_words: int) -> tuple[FileProfile | None, ErrorEntry | None]:
    rel_path = path.relative_to(root).as_posix()
    top_level_dir = rel_path.split("/", 1)[0] if "/" in rel_path else "(root)"

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, ErrorEntry(rel_path=rel_path, stage="read", error=str(exc))

    fm_block, body = split_front_matter(text)
    has_fm = fm_block is not None

    fm_keys: list[str] = []
    fm_ok = True
    ms_topic: str | None = None
    error: ErrorEntry | None = None

    if has_fm:
        fm_keys = extract_front_matter_keys(fm_block)
        ms_topic = extract_ms_topic(fm_block)
        fm_ok, err_msg = try_parse_yaml(fm_block)
        if not fm_ok:
            error = ErrorEntry(rel_path=rel_path, stage="front_matter_yaml", error=err_msg or "unknown error")

    heading_counts, h2_texts = extract_headings(body)
    word_count = count_words(body)
    is_small = word_count < min_words

    profile = FileProfile(
        rel_path=rel_path,
        top_level_dir=top_level_dir,
        has_front_matter=has_fm,
        front_matter_keys=fm_keys,
        front_matter_parse_ok=fm_ok,
        ms_topic=ms_topic,
        heading_counts=heading_counts,
        top_headings=h2_texts,
        word_count=word_count,
        is_small=is_small,
    )
    return profile, error


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate(profiles: list[FileProfile], errors: list[ErrorEntry], top_n: int) -> dict:
    total = len(profiles)
    with_fm = sum(1 for p in profiles if p.has_front_matter)
    without_fm = total - with_fm
    fm_parse_failures = sum(1 for p in profiles if p.has_front_matter and not p.front_matter_parse_ok)

    dir_counts = Counter(p.top_level_dir for p in profiles)

    fm_key_counter: Counter[str] = Counter()
    for p in profiles:
        fm_key_counter.update(set(p.front_matter_keys))  # count files-with-key, not raw occurrences

    ms_topic_counter: Counter[str] = Counter(p.ms_topic for p in profiles if p.ms_topic)
    ms_topic_missing = sum(1 for p in profiles if p.has_front_matter and not p.ms_topic)

    heading_level_totals: Counter[str] = Counter()
    for p in profiles:
        for level, c in p.heading_counts.items():
            heading_level_totals[level] += c

    docs_with_no_headings = sum(1 for p in profiles if sum(p.heading_counts.values()) == 0)
    docs_with_multiple_h1 = sum(1 for p in profiles if p.heading_counts.get("H1", 0) > 1)

    h2_text_counter: Counter[str] = Counter()
    for p in profiles:
        h2_text_counter.update(p.top_headings)

    word_counts = [p.word_count for p in profiles]
    word_stats = {
        "total_words": sum(word_counts),
        "mean": round(mean(word_counts), 1) if word_counts else 0,
        "median": median(word_counts) if word_counts else 0,
        "min": min(word_counts) if word_counts else 0,
        "max": max(word_counts) if word_counts else 0,
    }
    bucket_counter: Counter[str] = Counter(bucket_for(w) for w in word_counts)
    bucket_histogram = [
        {"range": label, "count": bucket_counter.get(label, 0)}
        for _, _, label in WORD_COUNT_BUCKETS
    ]

    small_files = sorted(
        [{"path": p.rel_path, "word_count": p.word_count} for p in profiles if p.is_small],
        key=lambda x: x["word_count"],
    )

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_files": total,
        "total_errors": len(errors),
        "front_matter": {
            "with_front_matter": with_fm,
            "without_front_matter": without_fm,
            "yaml_parse_failures": fm_parse_failures,
            "key_frequency_top_n": fm_key_counter.most_common(top_n),
        },
        "ms_topic": {
            "distribution_top_n": ms_topic_counter.most_common(top_n),
            "distinct_values": len(ms_topic_counter),
            "files_with_front_matter_but_no_ms_topic": ms_topic_missing,
        },
        "files_per_top_level_dir": dir_counts.most_common(),
        "headings": {
            "level_totals": dict(sorted(heading_level_totals.items())),
            "docs_with_no_headings": docs_with_no_headings,
            "docs_with_multiple_h1": docs_with_multiple_h1,
            "top_h2_texts": h2_text_counter.most_common(top_n),
        },
        "word_counts": {
            "stats": word_stats,
            "histogram": bucket_histogram,
        },
        "small_files": {
            "count": len(small_files),
            "examples": small_files[:top_n],
        },
        "errors": {
            "count": len(errors),
            "examples": [e.__dict__ for e in errors[:top_n]],
        },
    }


# ---------------------------------------------------------------------------
# Report writers
# ---------------------------------------------------------------------------

def write_json_report(stats: dict, small_files_full: list[dict], errors_full: list[dict], out_path: Path) -> None:
    payload = dict(stats)
    payload["small_files"] = dict(payload["small_files"])
    payload["small_files"]["all"] = small_files_full
    payload["errors"] = dict(payload["errors"])
    payload["errors"]["all"] = errors_full
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _table(rows: list[tuple], headers: tuple) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def write_markdown_report(stats: dict, min_words: int, input_dir: Path, out_path: Path) -> None:
    lines: list[str] = []
    lines.append("# MicrosoftDocs-SupportArticles — Profiling Report")
    lines.append("")
    lines.append(f"- Generated: {stats['generated_at_utc']}")
    lines.append(f"- Source directory: `{input_dir}`")
    lines.append(f"- Small-file threshold: < {min_words} words")
    lines.append(f"- Total files scanned: **{stats['total_files']}**")
    lines.append(f"- Files that raised errors: **{stats['total_errors']}**")
    lines.append("")

    lines.append("## Files per top-level directory")
    lines.append("")
    lines.append(_table(stats["files_per_top_level_dir"], ("directory", "file_count")))
    lines.append("")

    fm = stats["front_matter"]
    lines.append("## Front matter")
    lines.append("")
    lines.append(f"- With front matter: {fm['with_front_matter']}")
    lines.append(f"- Without front matter: {fm['without_front_matter']}")
    lines.append(f"- YAML parse failures (front matter present but invalid YAML): {fm['yaml_parse_failures']}")
    lines.append("")
    lines.append("Top front-matter keys (by number of files containing the key):")
    lines.append("")
    lines.append(_table(fm["key_frequency_top_n"], ("key", "file_count")))
    lines.append("")

    mt = stats["ms_topic"]
    lines.append("## ms.topic distribution")
    lines.append("")
    lines.append(f"- Distinct values: {mt['distinct_values']}")
    lines.append(f"- Files with front matter but no ms.topic: {mt['files_with_front_matter_but_no_ms_topic']}")
    lines.append("")
    lines.append(_table(mt["distribution_top_n"], ("ms.topic value", "file_count")))
    lines.append("")

    hd = stats["headings"]
    lines.append("## Headings")
    lines.append("")
    lines.append(_table(list(hd["level_totals"].items()), ("level", "total_occurrences")))
    lines.append("")
    lines.append(f"- Documents with no headings at all: {hd['docs_with_no_headings']}")
    lines.append(f"- Documents with more than one H1: {hd['docs_with_multiple_h1']}")
    lines.append("")
    lines.append("Most common H2 heading texts (lowercased):")
    lines.append("")
    lines.append(_table(hd["top_h2_texts"], ("h2 text", "occurrences")))
    lines.append("")

    wc = stats["word_counts"]
    lines.append("## Word counts (body, excluding front matter)")
    lines.append("")
    s = wc["stats"]
    lines.append(_table(
        [("total_words", s["total_words"]), ("mean", s["mean"]), ("median", s["median"]),
         ("min", s["min"]), ("max", s["max"])],
        ("metric", "value"),
    ))
    lines.append("")
    lines.append("Histogram:")
    lines.append("")
    lines.append(_table([(b["range"], b["count"]) for b in wc["histogram"]], ("word_count_range", "file_count")))
    lines.append("")

    sf = stats["small_files"]
    lines.append("## Small / near-empty files")
    lines.append("")
    lines.append(f"- Total files below {min_words} words: {sf['count']}")
    if sf["examples"]:
        lines.append("")
        lines.append(f"First {len(sf['examples'])} (see JSON report for the full list):")
        lines.append("")
        lines.append(_table([(e["path"], e["word_count"]) for e in sf["examples"]], ("path", "word_count")))
    lines.append("")

    er = stats["errors"]
    lines.append("## Errors")
    lines.append("")
    lines.append(f"- Total files with errors: {er['count']}")
    if er["examples"]:
        lines.append("")
        lines.append(f"First {len(er['examples'])} (see JSON report for the full list):")
        lines.append("")
        lines.append(_table([(e["rel_path"], e["stage"], e["error"][:120]) for e in er["examples"]],
                             ("path", "stage", "error")))
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only profiling of the SupportArticles Markdown corpus.")
    parser.add_argument("--input", "-i", type=Path, default=DEFAULT_INPUT,
                         help=f"Root directory to scan (default: {DEFAULT_INPUT})")
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT,
                         help=f"Directory to write reports into (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--min-words", type=int, default=20,
                         help="Word-count threshold below which a file is flagged 'small' (default: 20)")
    parser.add_argument("--top-n", type=int, default=20,
                         help="How many entries to show per top-N table (default: 20)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir: Path = args.input.resolve()
    output_dir: Path = args.output.resolve()

    if not input_dir.exists():
        raise SystemExit(f"Input directory does not exist: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    md_files = sorted(input_dir.rglob("*.md"))
    print(f"Scanning {len(md_files)} Markdown files under {input_dir} ...")

    profiles: list[FileProfile] = []
    errors: list[ErrorEntry] = []

    for path in md_files:
        profile, error = profile_file(path, input_dir, args.min_words)
        if profile is not None:
            profiles.append(profile)
        if error is not None:
            errors.append(error)

    stats = aggregate(profiles, errors, args.top_n)

    small_files_full = sorted(
        [{"path": p.rel_path, "word_count": p.word_count} for p in profiles if p.is_small],
        key=lambda x: x["word_count"],
    )
    errors_full = [e.__dict__ for e in errors]

    json_path = output_dir / "profile_report.json"
    md_path = output_dir / "profile_report.md"

    write_json_report(stats, small_files_full, errors_full, json_path)
    write_markdown_report(stats, args.min_words, input_dir, md_path)

    print(f"Total files scanned : {stats['total_files']}")
    print(f"Files with errors   : {stats['total_errors']}")
    print(f"Small files (<{args.min_words}w) : {stats['small_files']['count']}")
    print(f"JSON report written to : {json_path}")
    print(f"Markdown report written to : {md_path}")


if __name__ == "__main__":
    main()
