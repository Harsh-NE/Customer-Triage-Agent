"""
02_filter.py -- Build a filtering manifest for the docker/docs corpus.

Decides, per Markdown file, whether it should enter the KB pipeline, and records why.
Read-only against the input directory; writes only the manifest under the output directory.

docker/docs is a full Hugo site repo, not a flat docs tree, so filtering here is an
*allowlist* of content directories rather than an excludelist of noise directories
(verified against the real repo tree: content/manuals, content/reference, content/guides,
and content/get-started are real docs -- 1,115 files; content/includes/ is Hugo partial
snippets (36 files, same role as Microsoft's includes/); _vendor/, layouts/, .agents/,
.github/, hack/, archetypes/, and root-level files (README.md, CONTRIBUTING.md, ...) are
repo tooling/boilerplate, not docs).

Rules (first match wins for exclusion):
  1. Path-based inclusion: only files under one of ALLOWED_CONTENT_DIRS enter the pipeline.
     Everything else (repo tooling, vendored docs, Hugo partials) is excluded.
  2. Tiny files (word count below --min-words) are boilerplate/partial fragments.
  3. Otherwise the file is included:
       - "troubleshooting_topic" if the front-matter "tags" list contains "Troubleshooting"
         (docker/docs' real convention, e.g. `tags: [Troubleshooting]` -- confirmed against
         live troubleshoot.md pages; there is no ms.topic equivalent)
       - "other_substantive_content" for everything else that survived the filters above

Nothing is deleted or modified. Every file gets a manifest record, included or not.

Usage:
    python scripts/02_filter.py
    python scripts/02_filter.py --input data/raw/docker-docs --output data/processed/docker
    python scripts/02_filter.py --min-words 20
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths / defaults
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "raw" / "docker-docs"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed" / "docker"

FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
WORD_RE = re.compile(r"\S+")

# Allowlist, not excludelist -- see module docstring for why.
ALLOWED_CONTENT_DIRS = {
    "content/manuals",
    "content/reference",
    "content/guides",
    "content/get-started",
}
TROUBLESHOOTING_TAG = "troubleshooting"


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def split_front_matter(text: str) -> tuple[str | None, str]:
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def parse_front_matter(fm_block: str | None) -> dict:
    """Real YAML parse -- needed because 'tags' is a list (flow or block style),
    not a single-line scalar like ms.topic was, so regex extraction is unreliable here."""
    if not fm_block:
        return {}
    try:
        data = yaml.safe_load(fm_block)
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def extract_tags(fm_dict: dict) -> list[str]:
    tags = fm_dict.get("tags")
    if isinstance(tags, list):
        return [str(t).strip() for t in tags if str(t).strip()]
    if isinstance(tags, str) and tags.strip():
        return [tags.strip()]
    return []


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


# ---------------------------------------------------------------------------
# Filtering decision
# ---------------------------------------------------------------------------

def is_allowed_dir(rel_path: str) -> bool:
    return any(rel_path == d or rel_path.startswith(d + "/") for d in ALLOWED_CONTENT_DIRS)


def process_file(full_path: Path, rel_path: str, min_words: int) -> dict:
    record_base = {"rel_path": rel_path}

    if not is_allowed_dir(rel_path):
        return {**record_base, "included": False, "reason": "not_in_allowed_content_dir",
                "tags": [], "title": None, "word_count": 0}

    try:
        text = full_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {**record_base, "included": False, "reason": f"read_error:{exc}",
                "tags": [], "title": None, "word_count": 0}

    fm_block, body = split_front_matter(text)
    fm_dict = parse_front_matter(fm_block)
    tags = extract_tags(fm_dict)
    title = extract_title(fm_block or "", body)
    word_count = count_words(body)

    # Rule 2: tiny files
    if word_count < min_words:
        return {**record_base, "included": False, "reason": f"too_small:{word_count}w",
                "tags": tags, "title": title, "word_count": word_count}

    # Rule 3: include, with a reason describing why
    normalized_tags = {t.strip().lower() for t in tags}
    reason = "troubleshooting_topic" if TROUBLESHOOTING_TAG in normalized_tags else "other_substantive_content"

    return {**record_base, "included": True, "reason": reason,
            "tags": tags, "title": title, "word_count": word_count}


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
    tag_counts = Counter(tag for r in records for tag in r["tags"]) or Counter({"(none)": 0})

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
    print("Counts by tag (top 20):")
    for tag, count in tag_counts.most_common(20):
        print(f"  {tag:40s} {count}")

    print()
    print(f"Manifest written to: {manifest_path}")


if __name__ == "__main__":
    main()
