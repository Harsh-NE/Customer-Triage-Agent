"""Convert your processed Docker KB into the JSONL the Resolver loads.

Step 1 — look at your file (prints the fields of the first record):
    python scripts/convert_kb.py --input path/to/chunks.jsonl --inspect

Step 2 — convert (auto-detects common field names; override with --map):
    python scripts/convert_kb.py --input path/to/chunks.jsonl --output data/kb_docker.jsonl
    python scripts/convert_kb.py --input chunks.jsonl --output data/kb_docker.jsonl \
        --map text=chunk_text chunk_id=id doc_id=source_path url=source_url

Accepts .jsonl, .json (a list of records) and .csv. Also writes
data/store_manifest.json (doc hashes) next to the output, which the cache uses
for invalidation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

csv.field_size_limit(2**31 - 1)

CANDIDATES = {
    "text": ["text", "content", "chunk_text", "page_content", "chunk", "body"],
    "chunk_id": ["chunk_id", "id", "chunk_uid", "uid"],
    "doc_id": ["doc_id", "document_id", "source", "source_path", "file", "path", "doc_path"],
    "url": ["url", "source_url", "link", "doc_url"],
    "title": ["title", "heading", "section_title", "section", "header"],
    "parent_text": ["parent_text", "parent", "section_text", "parent_content"],
    "product_area": ["product_area", "product", "area", "category"],
    "component": ["component", "subcategory", "topic"],
}


def load(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else data.get("chunks") or data.get("data") or []
    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    raise SystemExit(f"Unsupported file type: {path.suffix} (use .jsonl, .json or .csv)")


def flatten(r: dict[str, Any]) -> dict[str, Any]:
    """Lift keys out of a nested 'metadata' dict so both layouts work."""
    meta = r.get("metadata")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            meta = {}
    return {**(meta or {}), **{k: v for k, v in r.items() if k != "metadata"}}


def pick(r: dict[str, Any], field: str, mapping: dict[str, str]) -> Any:
    if field in mapping:
        return r.get(mapping[field])
    for c in CANDIDATES[field]:
        if r.get(c) not in (None, ""):
            return r[c]
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default="data/kb_docker.jsonl")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--map", nargs="*", default=[], help="target=source_field pairs")
    a = ap.parse_args()

    rows = load(Path(a.input))
    if not rows:
        raise SystemExit("No records found.")
    if a.inspect:
        first = flatten(rows[0])
        print(f"{len(rows)} records. Fields in the first record (nested metadata flattened):")
        for k, v in first.items():
            print(f"  {k:<20} {str(v)[:70]!r}")
        print("\nAuto-detected mapping:")
        for f in CANDIDATES:
            hit = next((c for c in CANDIDATES[f] if first.get(c) not in (None, "")), None)
            print(f"  {f:<13} <- {hit or '(not found — pass --map ' + f + '=<field>)'}")
        return

    mapping = dict(m.split("=", 1) for m in a.map)
    out, doc_text, skipped = [], {}, 0
    for i, raw in enumerate(rows):
        r = flatten(raw)
        text = pick(r, "text", mapping)
        if not text or not str(text).strip():
            skipped += 1
            continue
        chunk_id = str(pick(r, "chunk_id", mapping) or f"chunk-{i}")
        doc_id = str(pick(r, "doc_id", mapping) or chunk_id.split("#")[0])
        parent = pick(r, "parent_text", mapping)
        out.append({
            "chunk_id": chunk_id, "doc_id": doc_id, "title": pick(r, "title", mapping) or "",
            "text": str(text), "parent_text": parent or None,
            "url": pick(r, "url", mapping) or "", "source": "docker/docs",
            "metadata": {"product_area": pick(r, "product_area", mapping),
                         "component": pick(r, "component", mapping)},
        })
        doc_text.setdefault(doc_id, []).append(str(parent or text))

    hashes = {d: hashlib.sha1("".join(t).encode()).hexdigest()[:16] for d, t in doc_text.items()}
    for rec in out:
        rec["doc_hash"] = hashes[rec["doc_id"]]
    dest = Path(a.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8") as f:
        for rec in out:
            f.write(json.dumps(rec) + "\n")
    (dest.parent / "store_manifest.json").write_text(json.dumps(
        {"version": dest.name, "n_chunks": len(out), "doc_hashes": hashes}, indent=1))
    with_meta = sum(bool(r["metadata"]["product_area"]) for r in out)
    print(f"Wrote {len(out)} chunks from {len(hashes)} documents to {dest} (skipped {skipped} empty).")
    print(f"{with_meta} chunks have product_area metadata"
          + ("" if with_meta else " — the metadata boost will be inactive; pass --map product_area=<field>"))


if __name__ == "__main__":
    main()
