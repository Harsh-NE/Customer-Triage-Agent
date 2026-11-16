"""
ocr_eval.py -- how accurately does the screenshot reader read an error, and how fast does it get worse when the picture is poor?

The ground truth is the text we drew: scripts/make_test_screenshots.py renders known lines, this script reads the image back with the same
function the upload endpoint uses (preprocess + Tesseract/RapidOCR) and compares.

  CER   character error rate = edit distance(read, truth) / len(truth), after normalising whitespace (lines joined with one space).
  WER   the same over words.
  key-line recovery   the share of images in which the error line a person would search for (the line with the error cue) is recovered
                      EXACTLY and, more usefully, to within 10% character error. That line is what reaches the Clarifier.
  confidence          the engine's own mean word confidence, and how it tracks CER (a reader that is sure and wrong is the dangerous one).

Two sets: `shots` (the 6 readable example screenshots as drawn) and `degraded` (the rate-limit screenshot at lower scale and with blur, to show
where reading breaks down). LIMITS: these are synthetic images of clean terminal text with one font, so the numbers are an UPPER BOUND for real
screenshots (cropped, anti-aliased, themed, scaled by the OS). Real screenshots from users are still needed (docs/DATASET_PLAN.md).

    python -m triage.eval.ocr_eval
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REPORT_DIR = ROOT / "reports"
sys.path.insert(0, str(ROOT / "scripts"))

KEY_CUE = re.compile(r"(?i)\b(error|denied|cannot|failed|incomplete|unauthorized|not valid|toomanyrequests)\b")


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def edit_distance(a, b) -> int:
    """Levenshtein distance between two sequences (characters or words)."""
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def cer(truth: str, read: str) -> float:
    t, r = normalise(truth), normalise(read)
    return edit_distance(t, r) / len(t) if t else 0.0


def wer(truth: str, read: str) -> float:
    t, r = normalise(truth).split(), normalise(read).split()
    return edit_distance(t, r) / len(t) if t else 0.0


def key_line(lines: list[str]) -> str | None:
    """The first non-command line with an error cue: what a person would copy into a search box."""
    return next((l for l in lines if l.strip() and not l.startswith(("$", "PS ")) and KEY_CUE.search(l)), None)


def key_line_error(truth_line: str, read_text: str) -> float:
    """Smallest character error of the truth line against any line of the read text (or against the text joined, if the reader wrapped it)."""
    t = normalise(truth_line)
    read_lines = [normalise(l) for l in read_text.splitlines() if l.strip()]
    candidates = read_lines + [normalise(read_text)]
    best = min((edit_distance(t, c[:len(t) + 20]) / len(t) for c in candidates), default=1.0)
    return best


def read_raw(img) -> tuple[str, float | None, str | None, float]:
    """(text before secret masking, confidence, engine, milliseconds): the engine call the upload endpoint makes, without redaction."""
    from triage import ocr
    started = time.perf_counter()
    text, conf, engine, _ = ocr._run_engines(ocr._preprocess(img), "eng")
    return text, conf, engine, (time.perf_counter() - started) * 1000


def cases() -> list[dict]:
    import make_test_screenshots as shots
    readable = [n for n in shots.SHOTS if n not in ("blank", "hard_to_read", "not_docker", "instructions_inside")]
    out = [{"set": "shots", "name": n, **shots.SHOTS[n]} for n in readable]
    base = shots.SHOTS["rate_limit"]
    for scale in (1.0, 0.75, 0.55, 0.4):
        for blur in (0.0, 0.6, 1.1):
            out.append({"set": "degraded", "name": f"rate_limit scale {scale} blur {blur}", **base, "scale": scale, "blur": blur})
    return out


def evaluate(items: list[dict]) -> list[dict]:
    import make_test_screenshots as shots
    rows = []
    for c in items:
        kw = {k: v for k, v in c.items() if k not in ("set", "name")}
        img = shots.render(**kw)
        truth = "\n".join(c["lines"])
        text, conf, engine, ms = read_raw(img)
        kl = key_line(c["lines"])
        kle = key_line_error(kl, text) if kl else None
        rows.append({"set": c["set"], "name": c["name"], "cer": round(cer(truth, text), 4), "wer": round(wer(truth, text), 4), "confidence": conf,
                     "key_line_cer": None if kle is None else round(kle, 4), "key_line_exact": None if kle is None else kle == 0.0,
                     "key_line_within_10pct": None if kle is None else kle <= 0.10, "ms": round(ms), "engine": engine, "chars": len(normalise(truth))})
    return rows


def summarize(rows: list[dict]) -> dict:
    out = {}
    for name in sorted({r["set"] for r in rows}):
        part = [r for r in rows if r["set"] == name]
        kl = [r for r in part if r["key_line_cer"] is not None]
        out[name] = {"n": len(part), "cer_mean": round(statistics.mean(r["cer"] for r in part), 4), "cer_median": round(statistics.median(r["cer"] for r in part), 4),
                     "wer_mean": round(statistics.mean(r["wer"] for r in part), 4),
                     "key_line_exact": f"{sum(r['key_line_exact'] for r in kl)}/{len(kl)}", "key_line_within_10pct": f"{sum(r['key_line_within_10pct'] for r in kl)}/{len(kl)}",
                     "ms_median": round(statistics.median(r["ms"] for r in part)), "engine": part[0]["engine"]}
    return out


def write_markdown(path: Path, rows: list[dict], summary: dict) -> None:
    lines = ["# OCR accuracy on screenshots with known text", "", f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `python -m triage.eval.ocr_eval`. Synthetic clean terminal text, one font: "
             "an upper bound for real screenshots. CER/WER = character/word error rate (lower is better); key line = the line with the error cue._", "",
             "| set | n | CER mean | CER median | WER mean | key line exact | key line within 10% | ms median | engine |", "|---|---|---|---|---|---|---|---|---|"]
    for name, s in summary.items():
        lines.append(f"| {name} | {s['n']} | {s['cer_mean']:.3f} | {s['cer_median']:.3f} | {s['wer_mean']:.3f} | {s['key_line_exact']} | {s['key_line_within_10pct']} | {s['ms_median']} | {s['engine']} |")
    lines += ["", "## Per image", "", "| set | image | CER | WER | key line CER | confidence | ms |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['set']} | {r['name']} | {r['cer']:.3f} | {r['wer']:.3f} | {'-' if r['key_line_cer'] is None else format(r['key_line_cer'], '.3f')} | {r['confidence']} | {r['ms']} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="OCR character and word error rate against the text drawn in the test screenshots.")
    ap.add_argument("--out-json", type=Path, default=REPORT_DIR / "regression" / "ocr_eval.json")
    ap.add_argument("--out-md", type=Path, default=REPORT_DIR / "regression" / "ocr_eval.md")
    args = ap.parse_args()
    rows = evaluate(cases())
    summary = summarize(rows)
    write_markdown(args.out_md, rows, summary)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(args.out_md.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
