import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { fmtDuration, fmtMoney, fmtPct, fmtTokens, reasonLabel } from "../format";
import { Card, Empty, ErrorNote, Kpi, PageHeader, Spinner, selectClass } from "../components/ui";

export const COLORS = { resolved: "#10b981", escalated: "#f59e0b", declined: "#94a3b8", active: "#38bdf8" };

export function WindowSelect({ days, onChange }: { days: number; onChange: (d: number) => void }) {
  return (
    <label className="flex items-center gap-2 text-sm text-slate-600">Window
      <select className={selectClass} value={days} onChange={(e) => onChange(Number(e.target.value))}>
        <option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option>
      </select>
    </label>
  );
}

export default function DashboardPage() {
  const [days, setDays] = useState(30);
  const summary = useQuery({ queryKey: ["summary", days], queryFn: () => api.summary(days), refetchInterval: 15000 });
  const series = useQuery({ queryKey: ["series", days], queryFn: () => api.timeseries(days), refetchInterval: 15000 });
  const s = summary.data;
  const reasons = s ? Object.entries(s.escalation_reasons).map(([k, v]) => ({ reason: reasonLabel(k), count: v })) : [];

  return (
    <div className="mx-auto max-w-6xl p-3 sm:p-6">
      <PageHeader title="Support dashboard" subtitle="How the agent is performing. Every number comes from stored conversations; hover a tile for its definition."
        action={<WindowSelect days={days} onChange={setDays} />} />
      {summary.isLoading && <Spinner />}
      {summary.isError && <ErrorNote error={summary.error} />}
      {s && s.totals.conversations === 0 && <Card><Empty title="No conversations in this window" hint="Numbers appear here as customers use the assistant." /></Card>}
      {s && s.totals.conversations > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Conversations" value={s.totals.conversations} hint={`${s.totals.active} in progress`} />
            <Kpi label="Resolved by agent" value={s.totals.resolved_by_agent} hint={`${s.totals.resolved_by_engineer} resolved by engineers`} />
            <Kpi label="Resolution rate" value={fmtPct(s.rates.resolution_rate)} title={s.definitions.resolution_rate} hint={`agent alone ${fmtPct(s.rates.agent_resolution_rate)}`} />
            <Kpi label="Escalated (open)" value={s.totals.escalated_open} hint={<Link to="/cases" className="text-brand-600 hover:underline">Open the queue →</Link>} />
            <Kpi label="Out of scope" value={s.totals.declined} title={s.definitions.decline_rate} hint={`${fmtPct(s.rates.decline_rate)} of finished`} />
            <Kpi label="Avg time to resolution" value={fmtDuration(s.timing.avg_time_to_resolution_s)} hint={`agent alone ${fmtDuration(s.timing.avg_agent_resolution_s)}`} />
            <Kpi label="Avg rating" value={s.feedback.avg_rating != null ? `${s.feedback.avg_rating.toFixed(1)} / 5` : "—"} hint={`${s.feedback.ratings} rating${s.feedback.ratings === 1 ? "" : "s"}`} />
            <Kpi label="LLM cost" value={fmtMoney(s.cost.total_cost_usd)} title={s.definitions.cost}
              hint={<>{fmtTokens(s.cost.total_tokens)} tokens{s.cost.unpriced_calls > 0 && <span className="text-amber-600"> · {s.cost.unpriced_calls} unpriced</span>}</>} />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            <Card title="Conversations over time" className="lg:col-span-2">
              <div className="h-64" role="img" aria-label="Stacked bar chart of conversations per day by outcome">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={series.data?.days ?? []}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="date" fontSize={12} /><YAxis allowDecimals={false} fontSize={12} /><Tooltip /><Legend />
                    <Bar dataKey="resolved" name="Resolved" stackId="a" fill={COLORS.resolved} />
                    <Bar dataKey="escalated" name="Escalated" stackId="a" fill={COLORS.escalated} />
                    <Bar dataKey="declined" name="Out of scope" stackId="a" fill={COLORS.declined} />
                    <Bar dataKey="active" name="In progress" stackId="a" fill={COLORS.active} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title="Agent behaviour">
              <dl className="space-y-3 text-sm">
                {([
                  ["Questions per conversation", s.agent_behaviour.avg_questions_per_conversation?.toFixed(2) ?? "—"],
                  ["Cache hit rate", `${fmtPct(s.agent_behaviour.cache_hit_rate)} (${s.agent_behaviour.cache_lookups} lookups)`],
                  ["Draft steps removed by verification", fmtPct(s.agent_behaviour.verify_drop_rate)],
                  ["Average evidence-gate score", s.agent_behaviour.avg_gate_confidence?.toFixed(2) ?? "—"],
                  ["Helpful votes", s.feedback.helpful_votes ? `${fmtPct(s.feedback.helpful_rate, 0)} of ${s.feedback.helpful_votes}` : "—"],
                ] as [string, string][]).map(([k, v]) => <div key={k} className="flex justify-between gap-3"><dt className="text-slate-500">{k}</dt><dd className="font-medium text-slate-800">{v}</dd></div>)}
              </dl>
              <p className="mt-3 text-xs text-slate-400" title={s.definitions.verify_drop_rate}>The gate score is a heuristic, not a probability.</p>
            </Card>
          </div>

          <Card title="Why conversations were escalated" className="mt-4">
            {reasons.length === 0 ? <Empty title="No escalations in this window" /> : (
              <div className="h-52" role="img" aria-label="Bar chart of escalation reasons">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={reasons} layout="vertical" margin={{ left: 40 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} /><XAxis type="number" allowDecimals={false} fontSize={12} /><YAxis type="category" dataKey="reason" width={190} fontSize={12} /><Tooltip />
                    <Bar dataKey="count" name="Cases" fill={COLORS.escalated} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
