"""
02_filter.py -- Build a filtering manifest for the MicrosoftDocs-SupportArticles corpus.

Decides, per Markdown file, whether it should enter the KB pipeline, and records why.
Read-only against the input directory; writes only the manifest under the output directory.

Rules (first match wins for exclusion):
  1. Path-based exclusion: files under includes/, templates/, .github/, or sitting at the
     repo root (README.md, SECURITY.md, ThirdPartyNotices.md, ...) are repository/boilerplate
     files, not support articles.
  2. Tiny files (word count below --min-words) are boilerplate/include fragments.
  3. Structural ms.topic values (landing-page, include) are navigation pages, not articles.
  4. Otherwise the file is included:
       - "troubleshooting_topic" if ms.topic is a troubleshooting-family value
       - "how_to_topic"          if ms.topic is how-to
       - "other_substantive_content" for everything else that survived the filters above
         (including files with no ms.topic at all -- profiling showed ~2,900 such files
         that may still contain real support knowledge)

Nothing is deleted or modified. Every file gets a manifest record, included or not.

Usage:
    python scripts/02_filter.py
    python scripts/02_filter.py --input data/raw/MicrosoftDocs-SupportArticles --output data/processed
    python scripts/02_filter.py --min-words 20
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths / defaults
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "raw" / "MicrosoftDocs-SupportArticles"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed"

FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
MS_TOPIC_RE = re.compile(r"^ms\.topic:\s*(.+?)\s*$", re.MULTILINE)
TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
WORD_RE = re.compile(r"\S+")

EXCLUDE_DIR_PREFIXES = {"includes", "templates", ".github"}
EXCLUDE_TOPICS = {"landing-page", "include"}
TROUBLESHOOTING_TOPICS = {
    "troubleshooting",
    "troubleshooting-problem-resolution",
    "troubleshooting-general",
    "troubleshooting-known-issue",
}
HOWTO_TOPICS = {"how-to"}


# ---------------------------------------------------------------------------
# Extraction helpers (self-contained; mirrors 01_profile.py's approach)
# ---------------------------------------------------------------------------

def split_front_matter(text: str) -> tuple[str | None, str]:
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def extract_ms_topic(fm_block: str) -> str | None:
    m = MS_TOPIC_RE.search(fm_block)
    if not m:
        return None
    value = m.group(1).strip().strip("'\"")
    value = value.split("#", 1)[0].strip()  # drop trailing "#Required"-style comments
    return value or None


def extract_title(fm_block: str, body: str) -> str | None:
    m = TITLE_RE.search(fm_block)
    if m:
        return m.group(1).strip().strip("'\"")
    m = H1_RE.search(body)
    if m:
        return m.group(1).strip()
    return None


def count_words(body: str) -> int:
    return len(WORD_RE.findall(body))


def normalize_topic_for_rules(topic: str | None) -> str:
    return (topic or "").strip().lower()


# ---------------------------------------------------------------------------
# Filtering decision
# ---------------------------------------------------------------------------

def top_level_dir(rel_path: str) -> str:
    return rel_path.split("/", 1)[0] if "/" in rel_path else "(root)"


def process_file(full_path: Path, rel_path: str, min_words: int) -> dict:
    top_dir = top_level_dir(rel_path)

    record_base = {"rel_path": rel_path}

    if top_dir in EXCLUDE_DIR_PREFIXES:
        return {**record_base, "included": False, "reason": f"excluded_directory:{top_dir}",
                "ms_topic": None, "title": None, "word_count": 0}
    if top_dir == "(root)":
        return {**record_base, "included": False, "reason": "repo_root_file",
                "ms_topic": None, "title": None, "word_count": 0}

    try:
        text = full_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {**record_base, "included": False, "reason": f"read_error:{exc}",
                "ms_topic": None, "title": None, "word_count": 0}

    fm_block, body = split_front_matter(text)
    ms_topic = extract_ms_topic(fm_block) if fm_block else None
    title = extract_title(fm_block or "", body)
    word_count = count_words(body)

    # Rule 2: tiny files
    if word_count < min_words:
        return {**record_base, "included": False, "reason": f"too_small:{word_count}w",
                "ms_topic": ms_topic, "title": title, "word_count": word_count}

    # Rule 3: structural topics
    normalized_topic = normalize_topic_for_rules(ms_topic)
    if normalized_topic in EXCLUDE_TOPICS:
        return {**record_base, "included": False, "reason": f"excluded_topic:{normalized_topic}",
                "ms_topic": ms_topic, "title": title, "word_count": word_count}

    # Rule 4: include, with a reason describing why
    if normalized_topic in TROUBLESHOOTING_TOPICS:
        reason = "troubleshooting_topic"
    elif normalized_topic in HOWTO_TOPICS:
        reason = "how_to_topic"
    else:
        reason = "other_substantive_content"

    return {**record_base, "included": True, "reason": reason,
            "ms_topic": ms_topic, "title": title, "word_count": word_count}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the KB-pipeline filtering manifest.")
    parser.add_argument("--input", "-i", type=Path, default=DEFAULT_INPUT,
                         help=f"Root directory to scan (default: {DEFAULT_INPUT})")
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT,
                         help=f"Directory to write the manifest into (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--min-words", type=int, default=20,
                         help="Word-count threshold below which a file is excluded as boilerplate (default: 20)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir: Path = args.input.resolve()
    output_dir: Path = args.output.resolve()

    if not input_dir.exists():
        raise SystemExit(f"Input directory does not exist: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "filter_manifest.jsonl"

    md_files = sorted(input_dir.rglob("*.md"))
    print(f"Scanning {len(md_files)} Markdown files under {input_dir} ...")

    records: list[dict] = []
    for full_path in md_files:
        rel_path = full_path.relative_to(input_dir).as_posix()
        records.append(process_file(full_path, rel_path, args.min_words))

    with manifest_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # --- summary ---
    total = len(records)
    included = [r for r in records if r["included"]]
    excluded = [r for r in records if not r["included"]]

    exclusion_reason_counts = Counter(r["reason"] for r in excluded)
    inclusion_reason_counts = Counter(r["reason"] for r in included)
    topic_counts = Counter((r["ms_topic"] or "(missing)") for r in records)

    print()
    print("=== Filter summary ===")
    print(f"Total scanned : {total}")
    print(f"Included      : {len(included)}")
    print(f"Excluded      : {len(excluded)}")

    print()
    print("Included, by reason:")
    for reason, count in inclusion_reason_counts.most_common():
        print(f"  {reason:30s} {count}")

    print()
    print("Excluded, by reason:")
    for reason, count in exclusion_reason_counts.most_common():
        print(f"  {reason:30s} {count}")

    print()
    print("Counts by ms.topic (top 20):")
    for topic, count in topic_counts.most_common(20):
        print(f"  {topic:40s} {count}")

    print()
    print(f"Manifest written to: {manifest_path}")


if __name__ == "__main__":
    main()
