"""
05_metadata.py -- Enrich chunks with retrieval/citation metadata.

For every chunk from 04_chunk.py, derives and attaches:
  - product_area / component   -- from the repo path under content/manuals/ (e.g.
                                   "engine/daemon", "desktop/troubleshoot-and-support")
  - tags                       -- carried over from front matter (e.g. ["Troubleshooting"]);
                                   docker/docs has no ms.custom sap:<category>\\<subcategory>
                                   equivalent, so tags are the whole taxonomy here, not a
                                   category/subcategory split
  - error_signals               -- HTTP/response codes and exit codes found in the chunk text.
                                   NOTE: unlike Microsoft's hex error codes / Event IDs (a
                                   near-universal convention there), docker/docs has no
                                   consistent structured error-code convention -- a check
                                   across ~12 real troubleshoot pages found the "NNN response
                                   code" phrasing in only one of them. Expect this field to be
                                   sparse; the verbatim error text in the chunk body (already
                                   preserved by 03_clean.py) is the more reliable retrieval
                                   signal, not this field.
  - source_url                 -- canonical GitHub URL to the source file (citable evidence link)
  - license                    -- Apache-2.0 (the docker/docs repo's LICENSE, verified 2026-10-05)

Also writes taxonomy.json: frequency-counted product_area / component / tag values,
so the taxonomy can be reviewed rather than trusted blindly.

Read-only against chunks.jsonl and cleaned_docs.jsonl. Writes chunks_metadata.jsonl + taxonomy.json.

Usage:
    python scripts/05_metadata.py
    python scripts/05_metadata.py --chunks data/processed/docker/chunks.jsonl \
                                   --cleaned data/processed/docker/cleaned_docs.jsonl \
                                   --output data/processed/docker
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHUNKS = PROJECT_ROOT / "data" / "processed" / "docker" / "chunks.jsonl"
DEFAULT_CLEANED = PROJECT_ROOT / "data" / "processed" / "docker" / "cleaned_docs.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed" / "docker"

GITHUB_BASE_URL = "https://github.com/docker/docs/blob/main/"
LICENSE = "Apache-2.0"   # the docker/docs repo LICENSE is Apache License 2.0 (read 2026-10-05); applies to the repo, not to _vendor/ (excluded)
CONTENT_PREFIX = "content/manuals/"

# Confirmed against live docker/docs pages: "(429 response code)" is real phrasing;
# "exit code N" is standard Docker/container vocabulary but unconfirmed in the troubleshoot
# pages sampled -- kept as a best-effort pattern, not a verified-high-yield one.
RESPONSE_CODE_RE = re.compile(r"\b(\d{3})\s*response code\b", re.IGNORECASE)
EXIT_CODE_RE = re.compile(r"\bexit code\s*:?\s*(\d{1,3})\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Per-document derivation (shared by every chunk of that document)
# ---------------------------------------------------------------------------

def product_area_and_component(rel_path: str) -> tuple[str | None, str | None]:
    """content/manuals/<product>/<component>/... -> (product, component).
    content/<guides|reference|get-started>/<x>/... -> (section, x): those sections aren't
    products, but a stable label beats the old "content" bucket that swallowed ~1.9k chunks.
    A single-file segment like "retired.md" has its extension stripped, never used raw."""
    if rel_path.startswith("content/"):
        rel_path = rel_path[len("content/"):]
    parts = rel_path.split("/")
    if parts and parts[0] == "manuals":
        parts = parts[1:]
    parts = [p[:-3] if p.endswith(".md") else p for p in parts]
    product_area = parts[0] if parts else None
    component = parts[1] if len(parts) > 1 else None
    return product_area, component


def doc_kind_for(rel_path: str, tags: list[str]) -> str:
    """Coarse page type, so retrieval/clarification can weight release notes and archived
    versions (~25% of this KB) differently from troubleshooting pages. First match wins."""
    lowered_tags = {t.lower() for t in tags}
    parts = rel_path.lower().split("/")
    if "troubleshooting" in lowered_tags or any("troubleshoot" in p for p in parts):
        return "troubleshooting"
    if "faq" in lowered_tags or "faqs" in parts:
        return "faq"
    if "previous-versions" in parts:
        return "archive"
    if "release-notes" in lowered_tags or any(p.startswith("release-notes") for p in parts):
        return "release_notes"
    if "guides" in parts:
        return "guide"
    if "reference" in parts:
        return "reference"
    return "docs"


def build_doc_metadata(doc: dict) -> dict:
    product_area, component = product_area_and_component(doc["rel_path"])
    tags = doc.get("tags") or []
    return {
        "product_area": product_area,
        "component": component,
        "doc_kind": doc_kind_for(doc["rel_path"], tags),
        "tags": tags,
        "source_url": GITHUB_BASE_URL + doc["rel_path"],
        "license": LICENSE,
    }


# ---------------------------------------------------------------------------
# Per-chunk derivation
# ---------------------------------------------------------------------------

def extract_error_signals(chunk: dict) -> list[str]:
    """Scans the chunk body AND its heading path -- confirmed against real docker/docs
    pages that the response-code callout is often the heading text itself (e.g.
    "## You have reached your pull rate limit (429 response code)"), not the body."""
    searchable = chunk.get("text", "") + " " + " ".join(chunk.get("heading_path") or [])
    signals = {f"HTTP {code} response code" for code in RESPONSE_CODE_RE.findall(searchable)}
    signals.update(f"exit code {code}" for code in EXIT_CODE_RE.findall(searchable))
    return sorted(signals)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enrich chunks with retrieval/citation metadata.")
    parser.add_argument("--chunks", "-c", type=Path, default=DEFAULT_CHUNKS,
                         help=f"chunks.jsonl from 04_chunk.py (default: {DEFAULT_CHUNKS})")
    parser.add_argument("--cleaned", type=Path, default=DEFAULT_CLEANED,
                         help=f"cleaned_docs.jsonl from 03_clean.py (default: {DEFAULT_CLEANED})")
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT,
                         help=f"Directory to write outputs into (default: {DEFAULT_OUTPUT})")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    chunks_path: Path = args.chunks.resolve()
    cleaned_path: Path = args.cleaned.resolve()
    output_dir: Path = args.output.resolve()

    if not chunks_path.exists():
        raise SystemExit(f"Chunks file not found: {chunks_path} (run 04_chunk.py first)")
    if not cleaned_path.exists():
        raise SystemExit(f"Cleaned docs file not found: {cleaned_path} (run 03_clean.py first)")

    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading cleaned docs for front-matter lookup ...")
    doc_metadata_by_path: dict[str, dict] = {}
    with cleaned_path.open(encoding="utf-8") as f:
        for line in f:
            doc = json.loads(line)
            doc_metadata_by_path[doc["rel_path"]] = build_doc_metadata(doc)

    product_counter: Counter[str] = Counter()
    component_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()
    chunks_with_error_signals = 0
    chunks_missing_tags = 0
    total = 0

    out_path = output_dir / "chunks_metadata.jsonl"
    print(f"Enriching chunks from {chunks_path} ...")

    with chunks_path.open(encoding="utf-8") as in_f, out_path.open("w", encoding="utf-8") as out_f:
        for line in in_f:
            chunk = json.loads(line)
            total += 1

            doc_meta = doc_metadata_by_path.get(chunk["source_path"], {})
            error_signals = extract_error_signals(chunk)

            chunk["metadata"] = {
                **chunk.get("metadata", {}),
                **doc_meta,
                "error_signals": error_signals,
            }

            if error_signals:
                chunks_with_error_signals += 1
            if not doc_meta.get("tags"):
                chunks_missing_tags += 1

            product_counter[doc_meta.get("product_area") or "(none)"] += 1
            component_counter[doc_meta.get("component") or "(none)"] += 1
            for tag in doc_meta.get("tags") or ["(none)"]:
                tag_counter[tag] += 1

            out_f.write(json.dumps(chunk, ensure_ascii=False, default=str) + "\n")

    taxonomy = {
        "product_area": product_counter.most_common(),
        "component": component_counter.most_common(50),
        "tags": tag_counter.most_common(50),
    }
    taxonomy_path = output_dir / "taxonomy.json"
    taxonomy_path.write_text(json.dumps(taxonomy, indent=2), encoding="utf-8")

    print()
    print("=== Metadata summary ===")
    print(f"Total chunks              : {total}")
    print(f"Chunks with error signals : {chunks_with_error_signals}")
    print(f"Chunks missing tags       : {chunks_missing_tags}")
    print(f"Distinct product_area     : {len(product_counter)}")
    print(f"Distinct component        : {len(component_counter)}")
    print(f"Distinct tags             : {len(tag_counter)}")
    print()
    print("Top product areas:")
    for name, count in product_counter.most_common(10):
        print(f"  {name:30s} {count}")
    print()
    print("Top tags:")
    for name, count in tag_counter.most_common(10):
        print(f"  {name:30s} {count}")
    print()
    print(f"Enriched chunks written to: {out_path}")
    print(f"Taxonomy written to: {taxonomy_path}")


if __name__ == "__main__":
    main()
