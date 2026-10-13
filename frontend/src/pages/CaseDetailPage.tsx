import { useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type CaseDetail, type Priority } from "../api";
import { useAuth } from "../auth";
import ActivityTimeline from "../components/ActivityTimeline";
import { Badge, Button, Card, ErrorNote, PriorityBadge, Spinner, StatusBadge, cx, inputClass, selectClass } from "../components/ui";
import { fmtAge, fmtDuration, fmtMoney, fmtTime, fmtTokens, reasonLabel } from "../format";

const ROLE_STYLE: Record<string, string> = {
  customer: "border-brand-100 bg-brand-50", agent: "border-slate-200 bg-white", engineer: "border-emerald-200 bg-emerald-50", system: "border-amber-200 bg-amber-50",
};

function Row({ k, children }: { k: string; children: ReactNode }) {
  return <div className="flex items-center justify-between gap-3 py-1 text-sm"><dt className="text-slate-500">{k}</dt><dd className="text-right font-medium text-slate-800">{children}</dd></div>;
}

export default function CaseDetailPage() {
  const { id = "" } = useParams();
  const { user } = useAuth();
  const qc = useQueryClient();
  const [reply, setReply] = useState("");
  const [note, setNote] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolution, setResolution] = useState("");
  const [promote, setPromote] = useState(false);

  const q = useQuery({ queryKey: ["case", id], queryFn: () => api.caseDetail(id), refetchInterval: 5000 });
  const done = (v: CaseDetail) => { qc.setQueryData(["case", id], v); qc.invalidateQueries({ queryKey: ["cases"] }); qc.invalidateQueries({ queryKey: ["summary"] }); };
  const replyM = useMutation({ mutationFn: (t: string) => api.reply(id, t), onSuccess: (v) => { done(v); setReply(""); } });
  const assignM = useMutation({ mutationFn: () => api.assign(id), onSuccess: done });
  const prioM = useMutation({ mutationFn: (p: Priority) => api.setPriority(id, p), onSuccess: done });
  const noteM = useMutation({ mutationFn: (t: string) => api.addNote(id, t), onSuccess: (v) => { done(v); setNote(""); } });
  const resolveM = useMutation({ mutationFn: () => api.resolve(id, resolution, promote), onSuccess: (v) => { done(v); setResolving(false); setResolution(""); } });
  const reopenM = useMutation({ mutationFn: () => api.reopen(id), onSuccess: done });
  const actionError = replyM.error ?? assignM.error ?? prioM.error ?? noteM.error ?? resolveM.error ?? reopenM.error;

  if (q.isLoading) return <Spinner />;
  if (q.isError) return <div className="p-6"><ErrorNote error={q.error} /></div>;
  const c = q.data!;
  const a = c.agent;
  const open = c.status === "escalated";

  return (
    <div className="mx-auto max-w-7xl p-3 sm:p-6">
      <Link to="/cases" className="text-sm text-brand-600 hover:underline">← Escalated cases</Link>
      <div className="mb-4 mt-1 flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-slate-900">Case {c.id}</h1>
        <PriorityBadge priority={c.priority} /><StatusBadge status={c.status} />
        <span className="text-sm text-slate-500">{reasonLabel(c.reason)}</span>
      </div>
      {actionError != null && <div className="mb-3"><ErrorNote error={actionError} /></div>}

      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        {/* ---------------- conversation ---------------- */}
        <div className="space-y-4">
          <Card title="Conversation">
            <div className="space-y-2.5">
              {c.messages.map((m) => (
                <div key={m.id} className={cx("rounded-lg border px-3 py-2", ROLE_STYLE[m.role])}>
                  <div className="mb-0.5 flex items-center justify-between text-xs text-slate-500">
                    <span className="font-semibold capitalize">{m.role === "customer" ? `Customer · ${c.customer}` : m.role === "engineer" ? `Engineer · ${m.author ?? ""}` : m.role === "agent" ? `Agent · ${m.kind}` : "System"}</span>
                    <span>{fmtTime(m.created_at)}</span>
                  </div>
                  <p className="whitespace-pre-wrap text-sm text-slate-800">{m.content}</p>
                </div>
              ))}
            </div>
            {open ? (
              <div className="mt-4 border-t border-slate-100 pt-3">
                <textarea aria-label="Reply to customer" rows={3} className={inputClass} placeholder="Reply to the customer…" value={reply} onChange={(e) => setReply(e.target.value)} />
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Button onClick={() => replyM.mutate(reply)} disabled={!reply.trim() || replyM.isPending}>{replyM.isPending ? "Sending…" : "Send reply"}</Button>
                  <Button variant="secondary" onClick={() => setResolving((v) => !v)}>Resolve case…</Button>
                </div>
                {resolving && (
                  <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
                    <label htmlFor="resolution" className="mb-1 block text-sm font-medium text-slate-700">Resolution (sent to the customer)</label>
                    <textarea id="resolution" rows={3} className={inputClass} value={resolution} onChange={(e) => setResolution(e.target.value)} placeholder="What fixed it?" />
                    <label className="mt-2 flex items-center gap-2 text-sm text-slate-600"><input type="checkbox" checked={promote} onChange={(e) => setPromote(e.target.checked)} />Flag this fix for reuse as knowledge (stored for review; not automatic)</label>
                    <div className="mt-2 flex gap-2">
                      <Button onClick={() => resolveM.mutate()} disabled={!resolution.trim() || resolveM.isPending}>Mark resolved</Button>
                      <Button variant="ghost" onClick={() => setResolving(false)}>Cancel</Button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3 text-sm text-slate-500">
                <span>{c.status === "resolved" ? `Resolved by ${c.resolved_by}${c.resolution_text ? `: “${c.resolution_text}”` : ""}` : "This conversation has no open case."}</span>
                {c.status !== "declined" && <Button variant="secondary" onClick={() => reopenM.mutate()} disabled={reopenM.isPending}>Reopen</Button>}
              </div>
            )}
          </Card>

          <Card title="Agent activity" action={<span className="text-xs text-slate-400">from the stored event log</span>}>
            <details open><summary className="mb-3 cursor-pointer text-sm text-slate-500">{c.activity.length} steps</summary><ActivityTimeline steps={c.activity} /></details>
          </Card>

          {a.attempts.length > 0 && (
            <Card title={`Fixes the agent tried (${a.attempts.length})`}>
              <ol className="space-y-3">
                {a.attempts.map((t) => (
                  <li key={t.attempt_no} className="rounded-lg border border-slate-200 p-3 text-sm">
                    <div className="mb-1 flex items-center gap-2"><span className="font-medium">Attempt {t.attempt_no}</span><Badge tone={t.tier === "kb" ? "green" : "violet"}>{t.tier === "kb" ? "docs" : "community tickets"}</Badge>
                      {t.reply_label && <Badge tone={t.reply_label === "resolved" ? "green" : "amber"}>{t.reply_label.replace("_", " ")}</Badge>}</div>
                    {t.diagnosis && <p className="text-slate-600">{t.diagnosis}</p>}
                    <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate-700">{t.steps.map((s, i) => <li key={i}>{s.text} <span className="font-mono text-xs text-slate-400">{s.evidence_ids.join(" ")}</span></li>)}</ul>
                    {t.sources && t.sources.length > 0 && (
                      <p className="mt-1 text-xs text-slate-500">Cited: {t.sources.map((s, i) => (
                        <span key={s.id}>{i > 0 && " · "}{s.url ? <a href={s.url} target="_blank" rel="noreferrer" className="text-brand-600 hover:underline">{s.title || s.id}</a> : s.title}</span>))}</p>
                    )}
                    {t.customer_reply && <p className="mt-1 text-slate-500">Customer: “{t.customer_reply}”</p>}
                  </li>
                ))}
              </ol>
            </Card>
          )}
        </div>

        {/* ---------------- side panel ---------------- */}
        <div className="space-y-4">
          <Card title="Case">
            <dl className="divide-y divide-slate-100">
              <Row k="Customer">{c.customer}</Row>
              <Row k="Opened">{fmtTime(c.created_at)} ({fmtAge(Math.floor((Date.now() - new Date(c.created_at).getTime()) / 60000))} ago)</Row>
              <Row k="Priority">
                <select aria-label="Priority" className={selectClass} value={c.priority ?? ""} disabled={!open || prioM.isPending} onChange={(e) => prioM.mutate(e.target.value as Priority)}>
                  {!c.priority && <option value="">—</option>}{["P1", "P2", "P3", "P4"].map((p) => <option key={p}>{p}</option>)}
                </select>
              </Row>
              <Row k="Assigned to">{c.assigned_to ?? <Button variant="secondary" className="px-2 py-1 text-xs" disabled={!open || assignM.isPending} onClick={() => assignM.mutate()}>Assign to me{user ? ` (${user.username})` : ""}</Button>}</Row>
              {c.closed_at && <Row k="Time to close">{fmtDuration(c.duration_s)}</Row>}
              {c.rating != null && <Row k="Customer rating">{"★".repeat(c.rating)}</Row>}
            </dl>
          </Card>

          <Card title="Why the agent escalated">
            <dl className="divide-y divide-slate-100">
              <Row k="Reason">{reasonLabel(c.reason)}</Row>
              {a.gate && <Row k="Evidence gate">{a.gate_decision} · score {a.gate.confidence?.toFixed(2)}</Row>}
              {a.gate?.reasons && a.gate.reasons.length > 0 && <Row k="Gate notes"><span className="text-xs font-normal text-slate-600">{a.gate.reasons.join("; ")}</span></Row>}
              {a.clarifier.status && <Row k="Clarifier">{a.clarifier.status}{a.clarifier.p_top != null ? ` · top cause ${(a.clarifier.p_top * 100).toFixed(0)}%` : ""}</Row>}
              {a.clarifier.uncovered_terms && a.clarifier.uncovered_terms.length > 0 && <Row k="Uncovered terms">{a.clarifier.uncovered_terms.join(", ")}</Row>}
              <Row k="Cache">{a.cache_status ?? "—"}</Row>
            </dl>
            {a.error && <div className="mt-2"><ErrorNote error={a.error} /></div>}
            {a.escalation?.suggested_next_checks?.length ? (
              <div className="mt-3"><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Suggested next checks</div>
                <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">{a.escalation.suggested_next_checks.map((s, i) => <li key={i}>{s}</li>)}</ul></div>
            ) : null}
            <p className="mt-3 text-xs text-slate-400">The gate score is a heuristic, not a probability.</p>
          </Card>

          {a.entities && a.entities.length > 0 && (
            <Card title="Recognised in the request" action={<span className="text-xs text-slate-400" title="From the Docker ontology (aliases resolved to canonical names)">ontology</span>}>
              <div className="flex flex-wrap gap-1.5">{a.entities.map((e) => <Badge key={e.id} tone={e.type === "platform" ? "blue" : e.type === "issue" ? "amber" : "slate"} title={`${e.type} · ${e.id}`}>{e.name}</Badge>)}</div>
            </Card>
          )}

          {a.hypotheses.length > 0 && (
            <Card title="Causes the agent considered">
              <ul className="space-y-2.5">
                {a.hypotheses.map((h, i) => (
                  <li key={i} className="text-sm">
                    <div className="flex justify-between gap-2"><span className="text-slate-700">{h.issue || h.label}</span><span className="shrink-0 font-medium text-slate-800">{(h.weight * 100).toFixed(0)}%</span></div>
                    <div className="mt-1 h-1.5 rounded-full bg-slate-100"><div className="h-1.5 rounded-full bg-brand-500" style={{ width: `${Math.max(2, h.weight * 100)}%` }} /></div>
                    {h.missing_terms && h.missing_terms.length > 0 && <div className="mt-0.5 text-xs text-amber-700">Doesn’t mention: {h.missing_terms.join(", ")}</div>}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {a.evidence.length > 0 && (
            <Card title={`Last evidence retrieved (${a.evidence.length})`} action={<span className="text-xs text-slate-400" title="What each fix cited is listed under the attempts">from the final search</span>}>
              <ul className="space-y-2.5">
                {a.evidence.map((e) => (
                  <li key={e.id} className="text-sm">
                    <div className="flex items-center gap-2"><span className="font-mono text-xs text-slate-400">{e.id}</span><Badge tone={e.tier === "kb" ? "green" : "violet"}>{e.tier === "kb" ? "docs" : "ticket"}</Badge>
                      <span className="text-xs text-slate-500">score {e.score?.toFixed(2) ?? "—"}</span></div>
                    {e.url ? <a href={e.url} target="_blank" rel="noreferrer" className="text-brand-600 hover:underline">{e.issue || e.url}</a> : <span>{e.issue}</span>}
                    <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{e.snippet}</p>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card title="Usage and cost">
            <dl className="divide-y divide-slate-100">
              <Row k="LLM calls">{c.usage.llm_calls}</Row>
              <Row k="Tokens in / out">{fmtTokens(c.usage.input_tokens)} / {fmtTokens(c.usage.output_tokens)}</Row>
              <Row k="Cost">{fmtMoney(c.usage.cost_usd)}{c.usage.unpriced_calls > 0 && <span className="ml-1 text-xs text-amber-600">+{c.usage.unpriced_calls} unpriced</span>}</Row>
            </dl>
          </Card>

          <Card title="Internal notes" action={<span className="text-xs text-slate-400">never shown to the customer</span>}>
            {c.notes.length === 0 && <p className="mb-2 text-sm text-slate-400">No notes yet.</p>}
            <ul className="mb-3 space-y-2">{c.notes.map((n) => <li key={n.id} className="rounded-lg bg-slate-50 px-3 py-2 text-sm"><div className="text-xs text-slate-500">{n.author} · {fmtTime(n.created_at)}</div>{n.body}</li>)}</ul>
            <textarea aria-label="Add internal note" rows={2} className={inputClass} placeholder="Add a note for the team…" value={note} onChange={(e) => setNote(e.target.value)} />
            <Button variant="secondary" className="mt-2" disabled={!note.trim() || noteM.isPending} onClick={() => noteM.mutate(note)}>Add note</Button>
            {c.actions.length > 0 && <details className="mt-3 text-xs text-slate-500"><summary className="cursor-pointer">Audit trail ({c.actions.length})</summary>
              <ul className="mt-1 space-y-0.5">{c.actions.map((x, i) => <li key={i}>{fmtTime(x.created_at)} · {x.actor} · {x.action}</li>)}</ul></details>}
          </Card>
        </div>
      </div>
    </div>
  );
}
