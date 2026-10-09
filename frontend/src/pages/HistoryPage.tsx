import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { fmtDuration, fmtTime } from "../format";
import { Badge, Card, Empty, ErrorNote, PageHeader, Spinner, StatusBadge } from "../components/ui";

export default function HistoryPage() {
  const q = useQuery({ queryKey: ["history"], queryFn: api.history });
  return (
    <div className="mx-auto max-w-4xl p-3 sm:p-6">
      <PageHeader title="My conversations" subtitle="Everything you've asked, with how it ended." />
      {q.isLoading && <Spinner />}
      {q.isError && <ErrorNote error={q.error} />}
      {q.data && (
        <Card>
          {q.data.conversations.length === 0 ? <Empty title="No conversations yet" hint="Start one from “New conversation”." /> : (
            <div className="overflow-x-auto"><table className="w-full min-w-[40rem] text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-500"><tr><th className="pb-2 font-medium">Issue</th><th className="pb-2 font-medium">Status</th><th className="pb-2 font-medium">Started</th><th className="pb-2 font-medium">Time taken</th><th className="pb-2 font-medium">Feedback</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {q.data.conversations.map((c) => (
                  <tr key={c.id} className="hover:bg-slate-50">
                    <td className="max-w-sm truncate py-2.5 pr-3"><Link to={`/chat/${c.id}`} className="font-medium text-brand-700 hover:underline">{c.title}</Link></td>
                    <td className="py-2.5 pr-3"><div className="flex items-center gap-1.5"><StatusBadge status={c.status} />{c.escalated && c.status === "resolved" && <Badge tone="amber" title="A support engineer was involved">Engineer</Badge>}</div></td>
                    <td className="py-2.5 pr-3 text-slate-600">{fmtTime(c.created_at)}</td>
                    <td className="py-2.5 pr-3 text-slate-600">{c.status === "active" ? "—" : fmtDuration(c.duration_s)}</td>
                    <td className="py-2.5 text-slate-600">{c.rating ? "★".repeat(c.rating) : c.helpful === true ? "👍" : c.helpful === false ? "👎" : "—"}</td>
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
