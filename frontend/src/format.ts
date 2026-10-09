// Small pure helpers (unit-tested in format.test.ts).

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ${m % 60}m` : `${Math.floor(h / 24)}d ${h % 24}h`;
}

export function fmtAge(minutes: number): string {
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  return h < 24 ? `${h} h` : `${Math.floor(h / 24)} d`;
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  return v == null ? "—" : `${(v * 100).toFixed(digits)}%`;
}

/** USD with enough precision for LLM-sized amounts: $0.0008, $0.42, $18.42. null = not priced. */
export function fmtMoney(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v === 0) return "$0";
  if (Math.abs(v) < 0.01) return `$${v.toFixed(5).replace(/0+$/, "").replace(/\.$/, "")}`;
  return `$${v.toFixed(v < 1 ? 4 : 2)}`;
}

export function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 10_000) return `${(n / 1000).toFixed(1)}k`;
  return n.toLocaleString("en-US");
}

export function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/**
 * The backend's question text already contains the numbered menu ("1. ...") and a "reply with the number" hint. With buttons
 * rendered from `options`, show only the prompt above the list.
 */
export function splitQuestion(content: string, options: string[]): string {
  if (!options.length) return content;
  const lines = content.split("\n");
  const firstItem = lines.findIndex((l) => /^\s*\d+[.)]\s/.test(l));
  const prompt = (firstItem === -1 ? lines : lines.slice(0, firstItem)).filter((l) => !/^\(reply with/i.test(l.trim()));
  return prompt.join("\n").trim() || content;
}

export const REASON_LABELS: Record<string, string> = {
  LOW_EVIDENCE: "Insufficient evidence",
  RETRY_EXHAUSTED: "Suggested fixes did not work",
  VERIFICATION_FAILED: "Draft failed verification",
  CRITICAL_SEVERITY: "Critical severity",
  SECURITY_OR_DATA_LOSS: "Security / data loss",
  CLARIFY_LOOP_EXHAUSTED: "Problem could not be specified",
  OUT_OF_SCOPE: "Out of scope",
  SYSTEM_ERROR: "System error",
  REOPENED: "Reopened",
};
export const reasonLabel = (r: string | null | undefined) => (r ? REASON_LABELS[r] ?? r : "—");
