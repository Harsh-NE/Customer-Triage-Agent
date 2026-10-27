"""
11_supplementary.py -- Add third-party tutorial/lab chunks as a SEPARATE, lower-trust knowledge-base tier.

Reads   data/raw/supplementary/chunks_extra_raw.jsonl   (706 chunks a teammate chunked from four GitHub repos)
Writes  data/processed/docker/chunks_supplementary.jsonl          the chunks that passed the quality filter, repaired and labelled
        data/processed/docker/chunks_supplementary_rejected.jsonl every dropped chunk with the reason
        data/processed/docker/supplementary_report.json           counts by reason / source, licences, input checksum
        data/processed/docker/store/supplementary/{vector,bm25}   its own indexes (with --build-store)

Why a separate tier and not more rows in the official store (scripts/06_store.py): these are community guides, not
Docker's documentation. They are mixed in quality, partly written for older Docker versions, and they overlap the
official pages on common topics (volumes, networking, install) so, ranked as peers, they would push official
troubleshooting down (measured: paraphrase MRR 0.66 -> 0.64, recall@3 on documented real questions 0.77 -> 0.69). They
are searched only when the official evidence is weak (triage/resolver/adapters.py), labelled as community material, and
carry their own licence and source link.

What the filter does (every rule is reported, nothing is dropped silently):
  * front / back matter of the ebook ("About the book", sponsors, cover, licence page, PDF tooling)
  * chunks under MIN_TOKENS tokens (navigation lines such as "Next: ...", one-sentence stubs)
  * REPAIR, not drop: HTML anchors in headings (<a name="x"></a>) are removed, and a leading heading that is really a
    "# comment" line inside a code block ("list of cat images") is dropped, then article/section/subsection are rebuilt
    from the repaired path so issue grouping works

Usage:
    python scripts/11_supplementary.py                  # filter + repair + label, write the chunk file and report
    python scripts/11_supplementary.py --build-store    # also build the separate vector + BM25 indexes (embeds ~550 chunks)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "raw" / "supplementary" / "chunks_extra_raw.jsonl"
PROCESSED = PROJECT_ROOT / "data" / "processed" / "docker"
OUT_CHUNKS = PROCESSED / "chunks_supplementary.jsonl"
OUT_REJECTED = PROCESSED / "chunks_supplementary_rejected.jsonl"
OUT_REPORT = PROCESSED / "supplementary_report.json"
STORE_ROOT = PROCESSED / "store" / "supplementary"

MIN_TOKENS = 30
SOURCES = {   # second path element under extra/  ->  how it is labelled to customers and engineers
    "ebook": {"name": "Introduction to Docker ebook (community)", "repo": "bobbyiliev/introduction-to-docker-ebook"},
    "buildkit": {"name": "BuildKit documentation (moby/buildkit)", "repo": "moby/buildkit"},
    "labs": {"name": "docker/labs tutorials (community)", "repo": "docker/labs"},
    "curriculum": {"name": "docker-curriculum tutorial (community)", "repo": "prakhar1989/docker-curriculum"},
}
FRONT_MATTER = re.compile(r"(?i)^(about the (book|author)|sponsors?|book cover|ebook pdf generation tool|table of contents|"
                          r"acknowledg\w*|contributors?|license)$")
ANCHOR = re.compile(r"<a\s+name=[\"'][^\"']*[\"']\s*>\s*</a>", re.I)


def load_script(filename: str):
    spec = importlib.util.spec_from_file_location("pipeline_" + filename[:2], SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def source_key(chunk: dict) -> str:
    parts = chunk["source_path"].split("/")
    return parts[1] if len(parts) > 1 and parts[0] == "extra" else ""


def repair_headings(path: list[str]) -> tuple[list[str], list[str]]:
    """Returns (repaired heading path, list of repairs applied)."""
    repairs: list[str] = []
    fixed = []
    for h in path:
        clean = ANCHOR.sub("", h).strip()
        if clean != h:
            repairs.append("anchor_removed")
        fixed.append(clean)
    # a lowercase, multi-word first heading above real headings is a "# comment" inside a code block, not a title
    if len(fixed) > 1 and re.match(r"[a-z]", fixed[0]) and " " in fixed[0]:
        fixed = fixed[1:]
        repairs.append("code_comment_heading_dropped")
    return fixed, repairs


def process(chunks: list[dict]) -> tuple[list[dict], list[dict], Counter]:
    kept, rejected, repairs_seen = [], [], Counter()
    for c in chunks:
        src = source_key(c)
        reject = None
        if src not in SOURCES:
            reject = "unknown_source"
        elif any(FRONT_MATTER.match(h.strip()) for h in c["heading_path"]):
            reject = "front_or_back_matter"
        elif c["token_count"] < MIN_TOKENS:
            reject = "too_short"
        if reject:
            rejected.append({"chunk_id": c["chunk_id"], "reason": reject, "source": src, "heading": " > ".join(c["heading_path"])[:120],
                             "token_count": c["token_count"]})
            continue
        path, repairs = repair_headings(c["heading_path"])
        if not path:
            rejected.append({"chunk_id": c["chunk_id"], "reason": "no_heading_left", "source": src, "heading": "", "token_count": c["token_count"]})
            continue
        repairs_seen.update(repairs)
        md = dict(c.get("metadata") or {})
        md.update({"source_tier": "supplementary", "source_name": SOURCES[src]["name"], "source_repo": SOURCES[src]["repo"]})
        out = dict(c)
        out.update({"heading_path": path, "article_title": path[0],
                    "section_title": path[1] if len(path) > 1 else None,
                    "subsection_title": path[2] if len(path) > 2 else None, "metadata": md})
        kept.append(out)
    return kept, rejected, repairs_seen


def build_store(chunks: list[dict], rebuild: bool) -> dict:
    store06 = load_script("06_store.py")
    config = store06.get_config()
    vector_path, bm25_path = STORE_ROOT / "vector", STORE_ROOT / "bm25"
    STORE_ROOT.mkdir(parents=True, exist_ok=True)
    store06.prepare_collection_for_build(config["EMBEDDING_MODEL"], vector_path, rebuild)
    store06.build_bm25_index(chunks, bm25_path)
    embedded, errors, dim = store06.build_vector_store(chunks, config["EMBEDDING_MODEL"], config["EMBEDDING_BATCH_SIZE"], vector_path)
    manifest = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "input_file": str(OUT_CHUNKS), "chunk_count": len(chunks),
                "chunks_embedded": embedded, "embedding_model": config["EMBEDDING_MODEL"], "embedding_dimension": dim,
                "vector_db_path": str(vector_path), "vector_collection": store06.collection_name_for_model(config["EMBEDDING_MODEL"]),
                "bm25_path": str(bm25_path), "errors": errors, "status": "success" if not errors else "partial"}
    (STORE_ROOT / "store_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description="Filter, repair and label the third-party chunks; optionally build their own store.")
    ap.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    ap.add_argument("--build-store", action="store_true", help="also build the separate vector + BM25 indexes")
    ap.add_argument("--rebuild", action="store_true", help="drop an existing supplementary vector collection first")
    args = ap.parse_args()

    raw_bytes = args.input.read_bytes()
    chunks = [json.loads(l) for l in raw_bytes.decode("utf-8").splitlines() if l.strip()]
    kept, rejected, repairs = process(chunks)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    OUT_CHUNKS.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in kept) + "\n", encoding="utf-8")
    OUT_REJECTED.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rejected) + "\n", encoding="utf-8")
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "input": str(args.input), "input_sha256": hashlib.sha256(raw_bytes).hexdigest(),
              "in": len(chunks), "kept": len(kept), "rejected": len(rejected),
              "rejected_by_reason": dict(Counter(r["reason"] for r in rejected)),
              "kept_by_source": dict(Counter(source_key(c) for c in kept)),
              "rejected_by_source": dict(Counter(r["source"] for r in rejected)),
              "repairs": dict(repairs), "licenses": dict(Counter(c["metadata"].get("license") for c in kept)),
              "doc_kinds": dict(Counter(c["metadata"].get("doc_kind") for c in kept))}
    if args.build_store:
        report["store"] = build_store(kept, args.rebuild)
    OUT_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "store"}, indent=2))
    print(f"chunks: {OUT_CHUNKS}" + (f"\nstore:  {STORE_ROOT}" if args.build_store else ""))


if __name__ == "__main__":
    main()
