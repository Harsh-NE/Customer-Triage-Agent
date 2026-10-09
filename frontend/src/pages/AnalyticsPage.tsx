import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { fmtDuration, fmtPct, reasonLabel } from "../format";
import { Card, Empty, ErrorNote, Kpi, PageHeader, Spinner } from "../components/ui";
import { COLORS, WindowSelect } from "./DashboardPage";

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const summary = useQuery({ queryKey: ["summary", days], queryFn: () => api.summary(days) });
  const series = useQuery({ queryKey: ["series", days], queryFn: () => api.timeseries(days) });
  const s = summary.data;
  const outcomes = s ? [
    { name: "Resolved by agent", value: s.totals.resolved_by_agent, color: COLORS.resolved },
    { name: "Resolved by engineer", value: s.totals.resolved_by_engineer, color: "#059669" },
    { name: "Escalated (open)", value: s.totals.escalated_open, color: COLORS.escalated },
    { name: "Out of scope", value: s.totals.declined, color: COLORS.declined },
    { name: "In progress", value: s.totals.active, color: COLORS.active },
  ].filter((o) => o.value > 0) : [];

  return (
    <div className="mx-auto max-w-6xl p-3 sm:p-6">
      <PageHeader title="Analytics" subtitle="Outcomes, quality signals and agent behaviour." action={<WindowSelect days={days} onChange={setDays} />} />
      {summary.isLoading && <Spinner />}
      {summary.isError && <ErrorNote error={summary.error} />}
      {s && s.totals.conversations === 0 && <Card><Empty title="No conversations in this window" /></Card>}
      {s && s.totals.conversations > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Resolution rate" value={fmtPct(s.rates.resolution_rate)} title={s.definitions.resolution_rate} hint="resolved / (resolved + escalated)" />
            <Kpi label="Escalation rate" value={fmtPct(s.rates.escalation_rate)} hint="needed an engineer" />
            <Kpi label="Avg time to resolution" value={fmtDuration(s.timing.avg_time_to_resolution_s)} />
            <Kpi label="Avg rating" value={s.feedback.avg_rating != null ? `${s.feedback.avg_rating.toFixed(1)} / 5` : "—"} hint={`${s.feedback.ratings} ratings · ${s.feedback.helpful_votes} helpful votes`} />
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <Card title="Outcomes">
              <div className="h-64" role="img" aria-label="Pie chart of conversation outcomes">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart><Pie data={outcomes} dataKey="value" nameKey="name" innerRadius={55} outerRadius={90} paddingAngle={2}>{outcomes.map((o) => <Cell key={o.name} fill={o.color} />)}</Pie><Tooltip /><Legend /></PieChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title="Created per day">
              <div className="h-64" role="img" aria-label="Bar chart of conversations created per day">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={series.data?.days ?? []}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="date" fontSize={12} /><YAxis allowDecimals={false} fontSize={12} /><Tooltip /><Bar dataKey="created" name="Conversations" fill="#6366f1" /></BarChart>
                </ResponsiveContainer>
              </div>
            </Card>
            <Card title="Escalation reasons">
              {Object.keys(s.escalation_reasons).length === 0 ? <Empty title="No escalations" /> : (
                <ul className="space-y-2 text-sm">{Object.entries(s.escalation_reasons).sort((a, b) => b[1] - a[1]).map(([k, v]) => <li key={k} className="flex justify-between"><span className="text-slate-600">{reasonLabel(k)}</span><span className="font-medium">{v}</span></li>)}</ul>
              )}
            </Card>
            <Card title="Agent behaviour">
              <dl className="space-y-2 text-sm">
                {([["Clarifying questions per conversation", s.agent_behaviour.avg_questions_per_conversation?.toFixed(2) ?? "—"], ["Cache hit rate", fmtPct(s.agent_behaviour.cache_hit_rate)],
                   ["Fix steps removed by verification", fmtPct(s.agent_behaviour.verify_drop_rate)], ["Average evidence-gate score", s.agent_behaviour.avg_gate_confidence?.toFixed(2) ?? "—"],
                   ["Out-of-scope rate", fmtPct(s.rates.decline_rate)]] as [string, string][]).map(([k, v]) => <div key={k} className="flex justify-between"><dt className="text-slate-500">{k}</dt><dd className="font-medium">{v}</dd></div>)}
              </dl>
            </Card>
          </div>
          <Card title="Definitions" className="mt-4">
            <dl className="space-y-2 text-sm">{Object.entries(s.definitions).map(([k, v]) => <div key={k}><dt className="font-medium text-slate-700">{k.replace(/_/g, " ")}</dt><dd className="text-slate-500">{v}</dd></div>)}</dl>
          </Card>
        </>
      )}
    </div>
  );
}
