"""
05_metadata.py -- Enrich chunks with retrieval/citation metadata.

For every chunk from 04_chunk.py, derives and attaches:
  - product_area / component   -- from the repo path (e.g. "Exchange/ExchangeHybrid/...",
                                   "support/windows-client/...")
  - category / subcategory     -- from the doc's "sap:<category>\\<subcategory>" tag in
                                   ms.custom (front matter). This is a bottom-up taxonomy:
                                   values are whatever the docs actually use, nothing hardcoded.
  - error_codes                -- hex error codes / Event IDs found in the chunk text
  - kb_number                  -- the "Original KB number" line, if the article has one
  - source_url                 -- canonical GitHub URL to the source file (citable evidence link)
  - license                    -- CC-BY-4.0 (per the repo's LICENSE)
  - ms_topic / ms_date / appliesto -- carried over from 04_chunk.py's metadata

Also writes taxonomy.json: frequency-counted product_area / component / category values,
so the taxonomy can be reviewed rather than trusted blindly.

Read-only against chunks.jsonl and cleaned_docs.jsonl. Writes chunks_metadata.jsonl + taxonomy.json.

Usage:
    python scripts/05_metadata.py
    python scripts/05_metadata.py --chunks data/processed/chunks.jsonl \
                                   --cleaned data/processed/cleaned_docs.jsonl \
                                   --output data/processed
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHUNKS = PROJECT_ROOT / "data" / "processed" / "chunks.jsonl"
DEFAULT_CLEANED = PROJECT_ROOT / "data" / "processed" / "cleaned_docs.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "processed"

GITHUB_BASE_URL = "https://github.com/MicrosoftDocs/SupportArticles-docs/blob/main/"
LICENSE = "CC-BY-4.0"

ERROR_CODE_RE = re.compile(r"0x[0-9A-Fa-f]{6,8}")
EVENT_ID_RE = re.compile(r"[Ee]vent\s?ID\s*[:#]?\s*(\d{2,6})")
KB_NUMBER_RE = re.compile(r"Original KB number:.*?(\d{4,7})")
SAP_TAG_RE = re.compile(r"^sap:\s*(.+)$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Per-document derivation (shared by every chunk of that document)
# ---------------------------------------------------------------------------

def product_area_and_component(rel_path: str) -> tuple[str | None, str | None]:
    parts = rel_path.split("/")
    if parts and parts[0] == "support" and len(parts) > 1:
        parts = parts[1:]
    product_area = parts[0] if parts else None
    component = parts[1] if len(parts) > 1 else None
    return product_area, component


def category_and_subcategory(ms_custom: list | None) -> tuple[str | None, str | None]:
    if not isinstance(ms_custom, list):
        return None, None
    for tag in ms_custom:
        if not isinstance(tag, str):
            continue
        m = SAP_TAG_RE.match(tag.strip())
        if m:
            value = m.group(1)
            if "\\" in value:
                category, subcategory = value.split("\\", 1)
                return category.strip(), subcategory.strip()
            return value.strip(), None
    return None, None


def extract_kb_number(full_markdown: str) -> str | None:
    m = KB_NUMBER_RE.search(full_markdown)
    return m.group(1) if m else None


def build_doc_metadata(doc: dict) -> dict:
    front_matter = doc.get("front_matter") or {}
    product_area, component = product_area_and_component(doc["rel_path"])
    category, subcategory = category_and_subcategory(front_matter.get("ms.custom"))
    return {
        "product_area": product_area,
        "component": component,
        "category": category,
        "subcategory": subcategory,
        "kb_number": extract_kb_number(doc["cleaned_markdown"]),
        "source_url": GITHUB_BASE_URL + doc["rel_path"],
        "license": LICENSE,
    }


# ---------------------------------------------------------------------------
# Per-chunk derivation
# ---------------------------------------------------------------------------

def extract_error_codes(text: str) -> list[str]:
    codes = set(ERROR_CODE_RE.findall(text))
    codes.update(f"Event ID {n}" for n in EVENT_ID_RE.findall(text))
    return sorted(codes)


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
    category_counter: Counter[str] = Counter()
    chunks_with_error_codes = 0
    chunks_with_kb_number = 0
    chunks_missing_category = 0
    total = 0

    out_path = output_dir / "chunks_metadata.jsonl"
    print(f"Enriching chunks from {chunks_path} ...")

    with chunks_path.open(encoding="utf-8") as in_f, out_path.open("w", encoding="utf-8") as out_f:
        for line in in_f:
            chunk = json.loads(line)
            total += 1

            doc_meta = doc_metadata_by_path.get(chunk["source_path"], {})
            error_codes = extract_error_codes(chunk["text"])

            chunk["metadata"] = {
                **chunk.get("metadata", {}),
                **doc_meta,
                "error_codes": error_codes,
            }

            if error_codes:
                chunks_with_error_codes += 1
            if doc_meta.get("kb_number"):
                chunks_with_kb_number += 1
            if not doc_meta.get("category"):
                chunks_missing_category += 1

            product_counter[doc_meta.get("product_area") or "(none)"] += 1
            component_counter[doc_meta.get("component") or "(none)"] += 1
            category_counter[doc_meta.get("category") or "(none)"] += 1

            out_f.write(json.dumps(chunk, ensure_ascii=False, default=str) + "\n")

    taxonomy = {
        "product_area": product_counter.most_common(),
        "component": component_counter.most_common(50),
        "category": category_counter.most_common(50),
    }
    taxonomy_path = output_dir / "taxonomy.json"
    taxonomy_path.write_text(json.dumps(taxonomy, indent=2), encoding="utf-8")

    print()
    print("=== Metadata summary ===")
    print(f"Total chunks              : {total}")
    print(f"Chunks with error codes   : {chunks_with_error_codes}")
    print(f"Chunks with kb_number     : {chunks_with_kb_number}")
    print(f"Chunks missing category   : {chunks_missing_category}")
    print(f"Distinct product_area     : {len(product_counter)}")
    print(f"Distinct component        : {len(component_counter)}")
    print(f"Distinct category         : {len(category_counter)}")
    print()
    print("Top product areas:")
    for name, count in product_counter.most_common(10):
        print(f"  {name:30s} {count}")
    print()
    print("Top categories:")
    for name, count in category_counter.most_common(10):
        print(f"  {name:30s} {count}")
    print()
    print(f"Enriched chunks written to: {out_path}")
    print(f"Taxonomy written to: {taxonomy_path}")


if __name__ == "__main__":
    main()
