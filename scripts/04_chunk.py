"""
04_chunk.py -- Hierarchical chunking of cleaned documents (Article -> Section -> Subsection -> Chunk).

For every cleaned doc from 03_clean.py:
  - Article  = the whole document (title + doc-level metadata)
  - Section  = each H2 heading (content before the first H2 becomes an "Overview" section)
  - Subsection = each H3 heading within a section (H4+ headings are folded in as bold text,
                 not a new tree level -- the required hierarchy is exactly 3 levels deep)
  - Chunk    = the text of one Section/Subsection (the "leaf"), split further only if it
               exceeds --max-words, so a single troubleshooting step never gets separated
               from the sentence that introduces it

Every chunk carries its full heading path and a few useful article-level metadata fields,
so it is self-describing once pulled out of a vector/BM25 index.

Fenced code blocks (```...```) are treated as atomic: '#' lines inside them are never
mistaken for headings, and blank lines inside them never cause a paragraph split.

Read-only against 03_clean.py's output. Writes a single JSONL file of chunks.

Usage:
    python scripts/04_chunk.py
    python scripts/04_chunk.py --input data/processed/cleaned_docs.jsonl --output data/processed
    python scripts/04_chunk.py --max-words 400
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "processed" / "cleaned_docs.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
CODE_FENCE_RE = re.compile(r"^```")
WORD_RE = re.compile(r"\S+")


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


# ---------------------------------------------------------------------------
# Step 1: parse cleaned markdown into an Article -> Section -> Subsection tree
# ---------------------------------------------------------------------------

@dataclass
class Subsection:
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass
class Section:
    title: str
    lines: list[str] = field(default_factory=list)       # content before the first H3
    subsections: list[Subsection] = field(default_factory=list)


def build_tree(body: str) -> tuple[list[str], list[Section]]:
    """Walk the markdown line by line, respecting fenced code blocks, and group it
    into an intro (content before any H2) plus a list of Sections/Subsections."""
    intro_lines: list[str] = []
    sections: list[Section] = []
    current_section: Section | None = None
    current_subsection: Subsection | None = None
    in_code_fence = False

    def target() -> list[str]:
        if current_subsection is not None:
            return current_subsection.lines
        if current_section is not None:
            return current_section.lines
        return intro_lines

    for raw_line in body.splitlines():
        if CODE_FENCE_RE.match(raw_line.strip()):
            in_code_fence = not in_code_fence
            target().append(raw_line)
            continue

        heading = None if in_code_fence else HEADING_RE.match(raw_line)
        if heading is None:
            target().append(raw_line)
            continue

        level, text = len(heading.group(1)), heading.group(2)
        if level == 1:
            continue  # article title, not a section
        if level == 2:
            current_section = Section(title=text)
            current_subsection = None
            sections.append(current_section)
        elif level == 3:
            if current_section is None:
                current_section = Section(title="Overview")
                sections.append(current_section)
            current_subsection = Subsection(title=text)
            current_section.subsections.append(current_subsection)
        else:
            # H4+ : keep as emphasized inline text rather than a 4th hierarchy level
            target().append(f"**{text}**")

    return intro_lines, sections


# ---------------------------------------------------------------------------
# Step 2: flatten the tree into leaves (one leaf = one Section or one Subsection)
# ---------------------------------------------------------------------------

@dataclass
class Leaf:
    heading_path: list[str]
    text: str


def flatten_to_leaves(article_title: str, intro_lines: list[str], sections: list[Section]) -> list[Leaf]:
    leaves: list[Leaf] = []

    intro_text = "\n".join(intro_lines).strip()
    if intro_text:
        leaves.append(Leaf(heading_path=[article_title, "Overview"], text=intro_text))

    for section in sections:
        section_text = "\n".join(section.lines).strip()
        if section_text:
            leaves.append(Leaf(heading_path=[article_title, section.title], text=section_text))
        for sub in section.subsections:
            sub_text = "\n".join(sub.lines).strip()
            if sub_text:
                leaves.append(Leaf(heading_path=[article_title, section.title, sub.title], text=sub_text))

    return leaves


# ---------------------------------------------------------------------------
# Step 3: split an oversized leaf into word-capped chunks, on paragraph boundaries
# ---------------------------------------------------------------------------

def split_into_paragraphs(text: str) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    in_code_fence = False

    for line in text.splitlines():
        if CODE_FENCE_RE.match(line.strip()):
            in_code_fence = not in_code_fence
            current.append(line)
            continue
        if not line.strip() and not in_code_fence:
            if current:
                paragraphs.append("\n".join(current).strip())
                current = []
            continue
        current.append(line)

    if current:
        paragraphs.append("\n".join(current).strip())
    return [p for p in paragraphs if p]


def pack_paragraphs(paragraphs: list[str], max_words: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0

    for para in paragraphs:
        para_words = count_words(para)
        if current and current_words + para_words > max_words:
            chunks.append("\n\n".join(current))
            current, current_words = [], 0
        current.append(para)
        current_words += para_words

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def split_leaf(leaf: Leaf, max_words: int) -> list[str]:
    if count_words(leaf.text) <= max_words:
        return [leaf.text]
    paragraphs = split_into_paragraphs(leaf.text)
    return pack_paragraphs(paragraphs, max_words) or [leaf.text]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def doc_id_from_rel_path(rel_path: str) -> str:
    return rel_path[:-3].replace("/", "__") if rel_path.endswith(".md") else rel_path.replace("/", "__")


def chunk_document(doc: dict, max_words: int) -> list[dict]:
    article_title = doc.get("title") or doc["rel_path"]
    intro_lines, sections = build_tree(doc["cleaned_markdown"])
    leaves = flatten_to_leaves(article_title, intro_lines, sections)

    front_matter = doc.get("front_matter") or {}
    doc_id = doc_id_from_rel_path(doc["rel_path"])

    chunks: list[dict] = []
    seq = 0
    for leaf in leaves:
        pieces = split_leaf(leaf, max_words)
        for i, piece in enumerate(pieces):
            chunks.append({
                "chunk_id": f"{doc_id}__{seq:04d}",
                "source_path": doc["rel_path"],
                "article_title": article_title,
                "section_title": leaf.heading_path[1] if len(leaf.heading_path) > 1 else None,
                "subsection_title": leaf.heading_path[2] if len(leaf.heading_path) > 2 else None,
                "heading_path": leaf.heading_path,
                "split_part": f"{i + 1}/{len(pieces)}" if len(pieces) > 1 else None,
                "text": piece,
                "word_count": count_words(piece),
                "metadata": {
                    "ms_topic": doc.get("ms_topic"),
                    "ms_date": front_matter.get("ms.date"),
                    "appliesto": front_matter.get("appliesto"),
                },
            })
            seq += 1
    return chunks


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hierarchical chunking of cleaned Markdown documents.")
    parser.add_argument("--input", "-i", type=Path, default=DEFAULT_INPUT,
                         help=f"cleaned_docs.jsonl from 03_clean.py (default: {DEFAULT_INPUT})")
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT,
                         help=f"Directory to write chunks.jsonl into (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--max-words", type=int, default=400,
                         help="Word-count ceiling per chunk before a leaf is split further (default: 400)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path: Path = args.input.resolve()
    output_dir: Path = args.output.resolve()

    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path} (run 03_clean.py first)")

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "chunks.jsonl"

    docs_processed = 0
    docs_with_no_sections = 0
    leaves_split_multi = 0
    all_chunk_word_counts: list[int] = []
    total_chunks = 0

    with input_path.open(encoding="utf-8") as in_f, out_path.open("w", encoding="utf-8") as out_f:
        for line in in_f:
            doc = json.loads(line)
            docs_processed += 1

            _, sections = build_tree(doc["cleaned_markdown"])
            if not sections:
                docs_with_no_sections += 1

            chunks = chunk_document(doc, args.max_words)
            total_chunks += len(chunks)

            split_parts_seen: set[str] = set()
            for c in chunks:
                all_chunk_word_counts.append(c["word_count"])
                if c["split_part"]:
                    key = c["chunk_id"].rsplit("__", 1)[0] + "|" + "/".join(c["heading_path"])
                    split_parts_seen.add(key)
                out_f.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")
            leaves_split_multi += len(split_parts_seen)

    print("=== Chunk summary ===")
    print(f"Docs processed             : {docs_processed}")
    print(f"Total chunks produced      : {total_chunks}")
    print(f"Avg chunks per doc         : {round(total_chunks / docs_processed, 2) if docs_processed else 0}")
    print(f"Docs with no H2 sections   : {docs_with_no_sections}")
    print(f"Leaves split into >1 chunk : {leaves_split_multi}")
    if all_chunk_word_counts:
        print(f"Chunk word count: min={min(all_chunk_word_counts)} "
              f"median={median(all_chunk_word_counts)} "
              f"mean={round(mean(all_chunk_word_counts), 1)} "
              f"max={max(all_chunk_word_counts)}")
    print(f"Output written to: {out_path}")


if __name__ == "__main__":
    main()
