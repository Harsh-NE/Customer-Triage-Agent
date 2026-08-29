"""
03_clean.py -- Clean and normalize the Markdown files selected by 02_filter.py.

For every file marked included=true in filter_manifest.jsonl:
  - parse front matter (YAML, best-effort)
  - resolve [!INCLUDE [..](path)] transclusions (one level of recursion)
  - convert admonition callouts (> [!NOTE] etc.) into plain "**Note:** ..." text
  - unescape HTML entities, collapse simple <a href="url">text</a> tags to "text (url)"
  - normalize whitespace (trailing spaces, excess blank lines)

Read-only against data/raw/. Writes a single JSONL file of cleaned documents.

Usage:
    python scripts/03_clean.py
    python scripts/03_clean.py --input data/raw/MicrosoftDocs-SupportArticles \
                                --manifest data/processed/filter_manifest.jsonl \
                                --output data/processed
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "raw" / "MicrosoftDocs-SupportArticles"
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "processed" / "filter_manifest.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed"

FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
WORD_RE = re.compile(r"\S+")

INCLUDE_RE = re.compile(r"\[!INCLUDE\s*\[[^\]]*\]\(([^)]+)\)\]?")
CALLOUT_RE = re.compile(
    r"^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*\r?\n((?:^>.*\r?\n?)*)",
    re.MULTILINE,
)
HTML_LINK_RE = re.compile(r"<a\s+[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
BLANK_LINES_RE = re.compile(r"\n{3,}")
TRAILING_SPACE_RE = re.compile(r"[ \t]+$", re.MULTILINE)

CALLOUT_LABELS = {
    "NOTE": "Note",
    "TIP": "Tip",
    "IMPORTANT": "Important",
    "WARNING": "Warning",
    "CAUTION": "Caution",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def split_front_matter(text: str) -> tuple[str | None, str]:
    m = FRONT_MATTER_RE.match(text)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def parse_front_matter(fm_block: str | None) -> dict:
    if not fm_block:
        return {}
    try:
        data = yaml.safe_load(fm_block)
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def extract_title(fm_block: str | None, body: str, fm_dict: dict) -> str | None:
    if isinstance(fm_dict.get("title"), str) and fm_dict["title"].strip():
        return fm_dict["title"].strip()
    if fm_block:
        m = TITLE_RE.search(fm_block)
        if m:
            return m.group(1).strip().strip("'\"")
    m = H1_RE.search(body)
    return m.group(1).strip() if m else None


def resolve_include_path(raw_path: str, current_file: Path, input_dir: Path) -> Path:
    raw_path = raw_path.strip()
    if raw_path.startswith("~/"):
        return (input_dir / raw_path[2:]).resolve()
    return (current_file.parent / raw_path).resolve()


def load_include_body(raw_path: str, current_file: Path, input_dir: Path) -> str | None:
    target = resolve_include_path(raw_path, current_file, input_dir)
    if not target.exists() or target.suffix.lower() != ".md":
        return None
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    _, body = split_front_matter(text)
    return body.strip()


def resolve_includes(body: str, current_file: Path, input_dir: Path, depth: int = 0) -> tuple[str, int, int]:
    """Returns (resolved_body, resolved_count, unresolved_count). Max recursion depth 2."""
    resolved = 0
    unresolved = 0

    def _sub(match: re.Match) -> str:
        nonlocal resolved, unresolved
        included_body = load_include_body(match.group(1), current_file, input_dir)
        if included_body is None:
            unresolved += 1
            return ""  # drop unresolvable include silently rather than leaving raw directive text
        resolved += 1
        if depth < 2:
            nested_body, r, u = resolve_includes(included_body, current_file, input_dir, depth + 1)
            resolved += r
            unresolved += u
            return nested_body
        return included_body

    new_body = INCLUDE_RE.sub(_sub, body)
    return new_body, resolved, unresolved


def convert_callouts(body: str) -> str:
    def _sub(match: re.Match) -> str:
        kind = CALLOUT_LABELS.get(match.group(1), match.group(1).title())
        block = match.group(2)
        lines = [re.sub(r"^>\s?", "", line) for line in block.splitlines()]
        text = " ".join(line.strip() for line in lines if line.strip())
        return f"**{kind}:** {text}\n"

    return CALLOUT_RE.sub(_sub, body)


def simplify_html_links(body: str) -> str:
    return HTML_LINK_RE.sub(lambda m: f"{m.group(2).strip()} ({m.group(1).strip()})", body)


def normalize_whitespace(body: str) -> str:
    body = TRAILING_SPACE_RE.sub("", body)
    body = BLANK_LINES_RE.sub("\n\n", body)
    return body.strip()


def clean_body(raw_body: str, current_file: Path, input_dir: Path) -> tuple[str, int, int]:
    body, resolved, unresolved = resolve_includes(raw_body, current_file, input_dir)
    body = convert_callouts(body)
    body = html.unescape(body)
    body = simplify_html_links(body)
    body = normalize_whitespace(body)
    return body, resolved, unresolved


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean and normalize included Markdown files.")
    parser.add_argument("--input", "-i", type=Path, default=DEFAULT_INPUT,
                         help=f"Raw corpus root (default: {DEFAULT_INPUT})")
    parser.add_argument("--manifest", "-m", type=Path, default=DEFAULT_MANIFEST,
                         help=f"filter_manifest.jsonl from 02_filter.py (default: {DEFAULT_MANIFEST})")
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT,
                         help=f"Directory to write cleaned_docs.jsonl into (default: {DEFAULT_OUTPUT})")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir: Path = args.input.resolve()
    manifest_path: Path = args.manifest.resolve()
    output_dir: Path = args.output.resolve()

    if not input_dir.exists():
        raise SystemExit(f"Input directory does not exist: {input_dir}")
    if not manifest_path.exists():
        raise SystemExit(f"Manifest not found: {manifest_path} (run 02_filter.py first)")

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "cleaned_docs.jsonl"

    included_paths = []
    with manifest_path.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("included"):
                included_paths.append(rec["rel_path"])

    print(f"{len(included_paths)} included files to clean ...")

    cleaned = 0
    errors = 0
    total_resolved_includes = 0
    total_unresolved_includes = 0
    docs_with_includes = 0

    with out_path.open("w", encoding="utf-8") as out_f:
        for rel_path in included_paths:
            full_path = input_dir / rel_path
            try:
                raw_text = full_path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                errors += 1
                print(f"  [error] {rel_path}: {exc}")
                continue

            fm_block, raw_body = split_front_matter(raw_text)
            fm_dict = parse_front_matter(fm_block)
            title = extract_title(fm_block, raw_body, fm_dict)
            ms_topic = fm_dict.get("ms.topic") if isinstance(fm_dict.get("ms.topic"), str) else None

            body, resolved, unresolved = clean_body(raw_body, full_path, input_dir)
            if resolved or unresolved:
                docs_with_includes += 1
            total_resolved_includes += resolved
            total_unresolved_includes += unresolved

            record = {
                "rel_path": rel_path,
                "title": title,
                "ms_topic": ms_topic,
                "front_matter": fm_dict,
                "cleaned_markdown": body,
                "word_count": count_words(body),
                "includes_resolved": resolved,
                "includes_unresolved": unresolved,
            }
            out_f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            cleaned += 1

    print()
    print("=== Clean summary ===")
    print(f"Docs cleaned              : {cleaned}")
    print(f"Docs with read errors     : {errors}")
    print(f"Docs containing includes  : {docs_with_includes}")
    print(f"Includes resolved (total) : {total_resolved_includes}")
    print(f"Includes unresolved (total): {total_unresolved_includes}")
    print(f"Output written to: {out_path}")


if __name__ == "__main__":
    main()
