import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useAuth } from "../auth";
import { fmtAge, reasonLabel, REASON_LABELS } from "../format";
import { Card, Empty, ErrorNote, PageHeader, PriorityBadge, Spinner, StatusBadge, inputClass, selectClass } from "../components/ui";

export default function CasesPage({ mode }: { mode: "escalated" | "all" }) {
  const { user } = useAuth();
  const [status, setStatus] = useState(mode === "all" ? "all" : "escalated");
  const [priority, setPriority] = useState("");
  const [reason, setReason] = useState("");
  const [assigned, setAssigned] = useState("");
  const [q, setQ] = useState("");
  const effectiveStatus = mode === "escalated" ? "escalated" : status;

  const cases = useQuery({
    queryKey: ["cases", effectiveStatus, priority, reason, assigned, q],
    queryFn: () => api.cases({ status: effectiveStatus, priority, reason, assigned, q }),
    refetchInterval: 10000,
  });

  return (
    <div className="mx-auto max-w-6xl p-3 sm:p-6">
      <PageHeader title={mode === "escalated" ? "Escalated cases" : "All cases"}
        subtitle={mode === "escalated" ? "Conversations the agent could not resolve safely. Highest priority first, then oldest." : "Every conversation, any status."} />
      <Card className="mb-4">
        <div className="flex flex-wrap items-center gap-3">
          {mode === "all" && (
            <select aria-label="Status" className={selectClass} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="all">All statuses</option><option value="escalated">Escalated</option><option value="resolved">Resolved</option><option value="declined">Out of scope</option><option value="active">In progress</option>
            </select>
          )}
          <select aria-label="Priority" className={selectClass} value={priority} onChange={(e) => setPriority(e.target.value)}>
            <option value="">Any priority</option>{["P1", "P2", "P3", "P4"].map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <select aria-label="Escalation reason" className={selectClass} value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">Any reason</option>{Object.entries(REASON_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <select aria-label="Assignee" className={selectClass} value={assigned} onChange={(e) => setAssigned(e.target.value)}>
            <option value="">Anyone</option><option value="unassigned">Unassigned</option>{user && <option value={user.username}>Assigned to me</option>}
          </select>
          <input aria-label="Search" className={`${inputClass} max-w-xs`} placeholder="Search issue text…" value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="ml-auto text-sm text-slate-500">{cases.data ? `${cases.data.total} case${cases.data.total === 1 ? "" : "s"}` : ""}</span>
        </div>
      </Card>

      {cases.isLoading && <Spinner />}
      {cases.isError && <ErrorNote error={cases.error} />}
      {cases.data && (
        <Card>
          {cases.data.cases.length === 0 ? <Empty title="No cases match" hint={mode === "escalated" ? "Nothing is waiting for an engineer." : undefined} /> : (
            <div className="overflow-x-auto"><table className="w-full min-w-[40rem] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-500"><tr>
                <th className="pb-2 font-medium">Case</th><th className="pb-2 font-medium">Issue</th><th className="pb-2 font-medium">Priority</th><th className="pb-2 font-medium">Reason</th>
                <th className="pb-2 font-medium">Age</th><th className="pb-2 font-medium">Status</th><th className="pb-2 font-medium">Assigned</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {cases.data.cases.map((c) => (
                  <tr key={c.id} className="hover:bg-slate-50">
                    <td className="py-2.5 pr-3 font-mono text-xs"><Link to={`/cases/${c.id}`} className="text-brand-700 hover:underline">{c.id}</Link></td>
                    <td className="max-w-xs truncate py-2.5 pr-3">{c.title}</td>
                    <td className="py-2.5 pr-3"><PriorityBadge priority={c.priority} /></td>
                    <td className="py-2.5 pr-3 text-slate-600">{reasonLabel(c.reason)}</td>
                    <td className="py-2.5 pr-3 text-slate-600">{fmtAge(c.age_minutes)}</td>
                    <td className="py-2.5 pr-3"><StatusBadge status={c.status} /></td>
                    <td className="py-2.5 text-slate-600">{c.assigned_to ?? <span className="text-slate-400">Unassigned</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
        </Card>
      )}
    </div>
  );
}
