"""
04_chunk.py -- Hierarchical chunking of cleaned documents (Article -> Section -> Subsection -> Chunk).

For every cleaned doc from 03_clean.py:
  - Article  = the whole document (title + doc-level metadata)
  - Section  = each H2 heading (content before the first H2 becomes an "Overview" section)
  - Subsection = each H3 heading within a section (H4+ headings are folded in as bold text,
                 not a new tree level -- the required hierarchy is exactly 3 levels deep)
  - Chunk    = the text of one Section/Subsection (the "leaf"), split further only if it
               exceeds --max-tokens (the embedding model's own token count), so a single
               troubleshooting step never gets separated from the sentence that introduces it

Every chunk carries its full heading path and a few useful article-level metadata fields,
so it is self-describing once pulled out of a vector/BM25 index.

Fenced code blocks (```...```) are treated as atomic: '#' lines inside them are never
mistaken for headings, and blank lines inside them never cause a paragraph split. A block that
alone exceeds the token budget is split on line boundaries and each part re-wrapped in its fence.

TOKEN-AWARE: no chunk exceeds --max-tokens (default 500) as counted by the tokenizer of the
embedding model (EMBEDDING_MODEL, default BAAI/bge-base-en-v1.5, which reads at most 512 tokens
and silently drops the rest). This script exits non-zero if any chunk would exceed the limit.
Requires the `transformers` package (installed with sentence-transformers). Changing the
chunking changes chunk ids, so BM25 and the vector store must be rebuilt (06_store.py).

Read-only against 03_clean.py's output. Writes a single JSONL file of chunks.

Usage:
    python scripts/04_chunk.py
    python scripts/04_chunk.py --input data/processed/docker/cleaned_docs.jsonl --output data/processed/docker
    python scripts/04_chunk.py --max-tokens 400
    python scripts/04_chunk.py --tokenizer BAAI/bge-base-en-v1.5
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median, quantiles

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "processed" / "docker" / "cleaned_docs.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed" / "docker"
DEFAULT_MAX_TOKENS = 500       # the model reads 512 including [CLS]/[SEP]; 500 leaves headroom
FALLBACK_TOKENIZER = "BAAI/bge-base-en-v1.5"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
CODE_FENCE_RE = re.compile(r"^```")
WORD_RE = re.compile(r"\S+")


def count_words(text: str) -> int:
    return len(WORD_RE.findall(text))


def resolve_tokenizer_name() -> str:
    """Same precedence as 06_store.py: real environment variable > .env file > default. The chunker
    must count tokens with the SAME model that will embed the chunks."""
    if os.environ.get("EMBEDDING_MODEL"):
        return os.environ["EMBEDDING_MODEL"]
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("EMBEDDING_MODEL=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip()
    return FALLBACK_TOKENIZER


def load_token_counter(name: str) -> "TokenCounter":
    from transformers import AutoTokenizer
    try:                                    # local cache first: no network round-trip, robust to a flaky connection
        tokenizer = AutoTokenizer.from_pretrained(name, local_files_only=True)
    except Exception:  # noqa: BLE001 -- not cached yet: download once
        tokenizer = AutoTokenizer.from_pretrained(name)
    return TokenCounter(tokenizer)


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
# Step 3: split an oversized leaf into TOKEN-capped chunks
#
# The embedding model reads at most 512 tokens and silently drops the rest, so the cap must be
# in TOKENS of that model's own tokenizer -- a word cap does not bound it (400 "words" of code,
# URLs or identifiers can be 800+ tokens; measured: 10.9% of the first Docker build's chunks
# exceeded the limit). Splitting prefers the most natural boundary that fits:
#     paragraph  ->  line (list items / code lines)  ->  sentence  ->  token-offset window
# Fenced code blocks that must be split are re-wrapped in their fences, so every chunk stays valid
# Markdown; the last-resort window cuts at token boundaries of the ORIGINAL text (never decoded
# back from ids), so no content is altered or lost.
# ---------------------------------------------------------------------------

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
FENCE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


class TokenCounter:
    """Counts tokens with a HuggingFace *fast* tokenizer (offsets are needed for exact slicing)."""

    def __init__(self, tokenizer) -> None:
        if not getattr(tokenizer, "is_fast", False):
            raise ValueError("04_chunk.py needs a fast tokenizer (offset mapping) -- pass a fast HF tokenizer")
        tokenizer.model_max_length = 10**9      # we do the limiting; silences the "longer than max length" warning
        self._tok = tokenizer

    def count(self, text: str) -> int:
        return len(self._tok(text, add_special_tokens=False)["input_ids"])

    def offsets(self, text: str) -> list[tuple[int, int]]:
        return list(self._tok(text, add_special_tokens=False, return_offsets_mapping=True)["offset_mapping"])


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


def hard_split(text: str, counter: TokenCounter, max_tokens: int) -> list[str]:
    """Last resort for a unit with no usable boundary (one huge line, a minified blob). Cuts at token
    boundaries, preferring a spot where a new word starts, and returns exact slices of `text`."""
    spans = counter.offsets(text)
    if not spans:
        return [text] if text.strip() else []
    pieces: list[str] = []
    i = 0
    while i < len(spans):
        j = min(i + max_tokens, len(spans))
        k = j
        while k < len(spans) and k > i + max_tokens // 2 and spans[k][0] == spans[k - 1][1]:
            k -= 1                                  # token k continues the word of k-1: back up to a word start
        if k <= i + max_tokens // 2:
            k = j                                   # no word boundary nearby (one giant identifier): cut anyway
        piece = text[spans[i][0]:spans[k - 1][1]]
        while counter.count(piece) > max_tokens and k - i > 1:
            k -= 1                                  # re-tokenising a slice can differ by a token or two
            piece = text[spans[i][0]:spans[k - 1][1]]
        pieces.append(piece)
        i = k
    return pieces


def pack(units: list[str], counter: TokenCounter, max_tokens: int, joiner: str) -> list[str]:
    """Greedily join whole units into chunks of at most max_tokens (each unit is already <= max_tokens;
    the joiner is whitespace, which adds no tokens for BERT-style tokenizers -- split_text re-checks anyway)."""
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for unit in units:
        t = counter.count(unit)
        if current and current_tokens + t > max_tokens:
            chunks.append(joiner.join(current))
            current, current_tokens = [], 0
        current.append(unit)
        current_tokens += t
    if current:
        chunks.append(joiner.join(current))
    return chunks


def split_prose(text: str, counter: TokenCounter, max_tokens: int) -> list[str]:
    units: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if counter.count(line) <= max_tokens:
            units.append(line)
            continue
        for sentence in SENTENCE_RE.split(line):
            if counter.count(sentence) <= max_tokens:
                units.append(sentence)
            else:
                units.extend(hard_split(sentence, counter, max_tokens))
    return pack(units, counter, max_tokens, "\n")


def split_code(block: str, counter: TokenCounter, max_tokens: int) -> list[str]:
    """Split a fenced block on line boundaries and re-wrap each part in the same fence."""
    lines = block.splitlines()
    opener = lines[0]
    body = lines[1:-1] if len(lines) > 1 and lines[-1].strip().startswith("```") else lines[1:]
    budget = max_tokens - counter.count(opener + "\n```")
    units: list[str] = []
    for line in body:
        units.extend(hard_split(line, counter, budget) if counter.count(line) > budget else [line])
    return [f"{opener}\n{part}\n```" for part in pack(units, counter, budget, "\n")]


def split_block(block: str, counter: TokenCounter, max_tokens: int) -> list[str]:
    """One paragraph that alone exceeds the budget: peel off code fences, split each segment by kind."""
    segments: list[tuple[str, str]] = []
    pos = 0
    for m in FENCE_BLOCK_RE.finditer(block):
        if block[pos:m.start()].strip():
            segments.append(("text", block[pos:m.start()].strip()))
        segments.append(("code", m.group(0)))
        pos = m.end()
    if block[pos:].strip():
        segments.append(("text", block[pos:].strip()))
    pieces: list[str] = []
    for kind, seg in segments or [("text", block)]:
        if counter.count(seg) <= max_tokens:
            pieces.append(seg)
        elif kind == "code":
            pieces.extend(split_code(seg, counter, max_tokens))
        else:
            pieces.extend(split_prose(seg, counter, max_tokens))
    return pieces


def split_text(text: str, counter: TokenCounter, max_tokens: int) -> list[str]:
    if counter.count(text) <= max_tokens:
        return [text]
    units: list[str] = []
    for paragraph in split_into_paragraphs(text):
        if counter.count(paragraph) <= max_tokens:
            units.append(paragraph)
        else:
            units.extend(split_block(paragraph, counter, max_tokens))
    chunks = pack(units, counter, max_tokens, "\n\n")
    # invariant guard: whatever the packing arithmetic did, nothing leaves this function over budget
    return [p for c in chunks for p in ([c] if counter.count(c) <= max_tokens else hard_split(c, counter, max_tokens))]


def split_leaf(leaf: Leaf, counter: TokenCounter, max_tokens: int) -> list[str]:
    return split_text(leaf.text, counter, max_tokens) or [leaf.text]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def doc_id_from_rel_path(rel_path: str) -> str:
    return rel_path[:-3].replace("/", "__") if rel_path.endswith(".md") else rel_path.replace("/", "__")


def chunk_document(doc: dict, counter: TokenCounter, max_tokens: int) -> list[dict]:
    article_title = doc.get("title") or doc["rel_path"]
    intro_lines, sections = build_tree(doc["cleaned_markdown"])
    leaves = flatten_to_leaves(article_title, intro_lines, sections)

    front_matter = doc.get("front_matter") or {}
    doc_id = doc_id_from_rel_path(doc["rel_path"])
    tags = doc.get("tags") or []

    chunks: list[dict] = []
    seq = 0
    for leaf in leaves:
        pieces = split_leaf(leaf, counter, max_tokens)
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
                "token_count": counter.count(piece),
                "metadata": {
                    "tags": tags,
                    "is_troubleshooting": "troubleshooting" in [t.lower() for t in tags],
                    "weight": front_matter.get("weight"),
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
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                         help=f"Token ceiling per chunk, counted with the embedding model's tokenizer (default: {DEFAULT_MAX_TOKENS})")
    parser.add_argument("--tokenizer", type=str, default=None,
                         help="HF tokenizer/model name to count tokens with (default: EMBEDDING_MODEL from env/.env, "
                              f"else {FALLBACK_TOKENIZER})")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path: Path = args.input.resolve()
    output_dir: Path = args.output.resolve()

    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path} (run 03_clean.py first)")

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "chunks.jsonl"
    tokenizer_name = args.tokenizer or resolve_tokenizer_name()
    print(f"Counting tokens with: {tokenizer_name}  (limit {args.max_tokens})")
    counter = load_token_counter(tokenizer_name)

    docs_processed = 0
    docs_with_no_sections = 0
    leaves_split_multi = 0
    all_chunk_word_counts: list[int] = []
    all_chunk_token_counts: list[int] = []
    total_chunks = 0

    with input_path.open(encoding="utf-8") as in_f, out_path.open("w", encoding="utf-8") as out_f:
        for line in in_f:
            doc = json.loads(line)
            docs_processed += 1

            _, sections = build_tree(doc["cleaned_markdown"])
            if not sections:
                docs_with_no_sections += 1

            chunks = chunk_document(doc, counter, args.max_tokens)
            total_chunks += len(chunks)

            split_parts_seen: set[str] = set()
            for c in chunks:
                all_chunk_word_counts.append(c["word_count"])
                all_chunk_token_counts.append(c["token_count"])
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
    if all_chunk_token_counts:
        q = quantiles(all_chunk_token_counts, n=20)
        print(f"Chunk token count: min={min(all_chunk_token_counts)} median={median(all_chunk_token_counts)} "
              f"p95={round(q[18])} max={max(all_chunk_token_counts)}")
    over = sum(t > args.max_tokens for t in all_chunk_token_counts)
    print(f"Chunks over {args.max_tokens} tokens : {over}")
    print(f"Output written to: {out_path}")
    if over:
        raise SystemExit(f"{over} chunk(s) exceed the token limit -- this is a bug in the splitter, do not embed this output.")


if __name__ == "__main__":
    main()
