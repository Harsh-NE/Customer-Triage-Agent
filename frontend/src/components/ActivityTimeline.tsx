import type { ActivityStep } from "../api";
import { cx } from "./ui";

const ICON: Record<ActivityStep["level"], { glyph: string; cls: string }> = {
  ok: { glyph: "✓", cls: "bg-emerald-100 text-emerald-700" },
  warn: { glyph: "!", cls: "bg-amber-100 text-amber-700" },
  error: { glyph: "×", cls: "bg-red-100 text-red-700" },
};

/** What the agent actually did, from the stored event log (not a reconstruction): guard, clarifier, cache, retrieval, gate, LLM, verify. */
export default function ActivityTimeline({ steps }: { steps: ActivityStep[] }) {
  if (!steps.length) return <p className="text-sm text-slate-400">No recorded activity.</p>;
  return (
    <ol className="space-y-2">
      {steps.map((s, i) => (
        <li key={i} className="flex items-start gap-2.5 text-sm">
          <span className={cx("mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-xs font-bold", ICON[s.level].cls)} aria-label={s.level}>{ICON[s.level].glyph}</span>
          <span className="text-slate-700">{s.label}{s.latency_ms != null && <span className="ml-2 text-xs text-slate-400">{Math.round(s.latency_ms)} ms</span>}</span>
        </li>
      ))}
    </ol>
  );
}
