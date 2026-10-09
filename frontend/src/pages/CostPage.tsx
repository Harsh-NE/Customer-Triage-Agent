import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type Bucket } from "../api";
import { fmtMoney, fmtTokens } from "../format";
import { Card, Empty, ErrorNote, Kpi, PageHeader, Spinner } from "../components/ui";
import { WindowSelect } from "./DashboardPage";

function BucketTable({ title, rows, label }: { title: string; rows: Record<string, Bucket>; label: string }) {
  const entries = Object.entries(rows).sort((a, b) => b[1].cost_usd - a[1].cost_usd);
  return (
    <Card title={title}>
      {entries.length === 0 ? <Empty title="No LLM calls" /> : (
        <div className="overflow-x-auto"><table className="w-full min-w-[26rem] text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-slate-500"><tr><th className="pb-2 font-medium">{label}</th><th className="pb-2 text-right font-medium">Calls</th><th className="pb-2 text-right font-medium">In</th><th className="pb-2 text-right font-medium">Out</th><th className="pb-2 text-right font-medium">Cost</th></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {entries.map(([k, b]) => (
              <tr key={k}><td className="py-2 font-medium text-slate-700">{k}</td><td className="py-2 text-right">{b.calls}</td><td className="py-2 text-right">{fmtTokens(b.input_tokens)}</td><td className="py-2 text-right">{fmtTokens(b.output_tokens)}</td>
                <td className="py-2 text-right">{fmtMoney(b.cost_usd)}{b.unpriced_calls > 0 && <span className="ml-1 text-xs text-amber-600" title="Calls on a model with no price in triage/pricing.json">+{b.unpriced_calls} unpriced</span>}</td></tr>
            ))}
          </tbody>
        </table></div>
      )}
    </Card>
  );
}

export default function CostPage() {
  const [days, setDays] = useState(30);
  const q = useQuery({ queryKey: ["cost", days], queryFn: () => api.cost(days), refetchInterval: 15000 });
  const c = q.data;
  return (
    <div className="mx-auto max-w-6xl p-3 sm:p-6">
      <PageHeader title="Tokens & cost" subtitle="LLM spend from real token counts and the price table. Embeddings run locally and cost nothing."
        action={<WindowSelect days={days} onChange={setDays} />} />
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorNote error={q.error} />}
      {c && c.overall.unpriced_calls > 0 && (
        <div role="note" className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {c.overall.unpriced_calls} of {c.overall.llm_calls} calls used a model with no price, so the totals below <strong>exclude</strong> them. Add the model to <code>triage/pricing.json</code>.
        </div>
      )}
      {c && c.overall.llm_calls === 0 && <Card><Empty title="No LLM calls in this window" hint="The Clarifier is deterministic; spend comes from the Resolver’s scope check, drafts and reply classification." /></Card>}
      {c && c.overall.llm_calls > 0 && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Kpi label="Total cost" value={fmtMoney(c.overall.total_cost_usd)} hint={`${c.overall.llm_calls} LLM calls`} />
            <Kpi label="Total tokens" value={fmtTokens(c.overall.total_tokens)} hint={`${fmtTokens(c.overall.input_tokens)} in · ${fmtTokens(c.overall.output_tokens)} out`} />
            <Kpi label="Avg cost / conversation" value={fmtMoney(c.overall.avg_cost_per_conversation_usd)} />
            <Kpi label="Resolved vs escalated" value={`${fmtMoney(c.overall.avg_cost_resolved_usd)} / ${fmtMoney(c.overall.avg_cost_escalated_usd)}`} hint="avg cost per conversation" />
          </div>
          <Card title="Cost per day" className="mt-4">
            <div className="h-56" role="img" aria-label="Bar chart of LLM cost per day">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={c.by_day}><CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="date" fontSize={12} /><YAxis fontSize={12} tickFormatter={(v) => fmtMoney(v)} width={70} /><Tooltip formatter={(v) => fmtMoney(Number(v))} /><Bar dataKey="cost_usd" name="Cost" fill="#6366f1" /></BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            <BucketTable title="By model" rows={c.by_model} label="Model" />
            <BucketTable title="By step" rows={c.by_node} label="Step" />
          </div>
        </>
      )}
    </div>
  );
}
