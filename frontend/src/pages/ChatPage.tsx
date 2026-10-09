import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ConversationView } from "../api";
import FeedbackBox from "../components/FeedbackBox";
import { MessageView } from "../components/Messages";
import { Button, ErrorNote, Spinner, StatusBadge } from "../components/ui";

const EXAMPLES = [
  "Docker commands fail and say they cannot connect to the Docker daemon",
  "docker pull fails with 'You have reached your pull rate limit'",
  "My container keeps getting killed, I think it runs out of memory",
];

function Banner({ view }: { view: ConversationView }) {
  if (view.status === "escalated") return <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">A support engineer is looking at this. You can keep adding details below; their replies will appear here.</div>;
  if (view.status === "declined") return <div className="rounded-lg border border-slate-200 bg-slate-100 px-3 py-2 text-sm text-slate-600">This request was outside what this assistant helps with (Docker technical support).</div>;
  if (view.status === "resolved" && view.resolved_by === "engineer") return <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">Resolved by a support engineer.</div>;
  return null;
}

export default function ChatPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [draft, setDraft] = useState("");
  const bottom = useRef<HTMLDivElement>(null);

  const conv = useQuery({
    queryKey: ["conv", id], queryFn: () => api.conversation(id!), enabled: !!id,
    refetchInterval: (q) => (q.state.data && (q.state.data.status === "active" || q.state.data.status === "escalated") ? 3000 : false),
  });
  const view = conv.data;

  const start = useMutation({
    mutationFn: (text: string) => api.start(text),
    onSuccess: (v) => { qc.setQueryData(["conv", v.id], v); qc.invalidateQueries({ queryKey: ["history"] }); nav(`/chat/${v.id}`); },
  });
  const send = useMutation({
    mutationFn: (body: { text?: string; action?: "resolved" | "not_fixed" }) => api.send(id!, body),
    onSuccess: (v) => { qc.setQueryData(["conv", id], v); qc.invalidateQueries({ queryKey: ["history"] }); },
  });

  const busy = start.isPending || send.isPending;
  const pendingText = send.isPending ? send.variables?.text ?? (send.variables?.action === "resolved" ? "That fixed it, thanks." : "I tried that but it is still the same error.") : start.isPending ? start.variables : null;

  useEffect(() => { bottom.current?.scrollIntoView?.({ behavior: "smooth", block: "end" }); }, [view?.messages.length, busy]);
  useEffect(() => { setDraft(""); start.reset(); send.reset(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  function submit() {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    if (id) send.mutate({ text }); else start.mutate(text);
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } };

  if (id && conv.isLoading) return <Spinner />;
  if (id && conv.isError) return <div className="p-6"><ErrorNote error={conv.error} /></div>;

  const canReply = !id || (view?.can_reply ?? false);
  const error = start.error ?? send.error;
  const closed = view && !view.can_reply;

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-3 py-3 sm:px-6">
        <div className="min-w-0"><h1 className="truncate text-base font-semibold text-slate-900">{view?.title ?? "New conversation"}</h1>{view && <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-500"><StatusBadge status={view.status} /><span>#{view.id}</span></div>}</div>
        {view && <Link to="/chat" className="text-sm font-medium text-brand-600 hover:underline">Start new</Link>}
      </header>

      <div className="flex-1 overflow-y-auto px-3 py-5 sm:px-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-3">
          {!id && !start.isPending && (
            <div className="py-10 text-center">
              <h2 className="text-lg font-semibold text-slate-900">How can I help with Docker today?</h2>
              <p className="mt-1 text-sm text-slate-500">Describe the problem and include any error text. I'll answer from the documentation and show my sources.</p>
              <div className="mx-auto mt-5 flex max-w-xl flex-col gap-2">
                {EXAMPLES.map((e) => <button key={e} type="button" onClick={() => setDraft(e)} className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-sm text-slate-600 hover:border-brand-500 hover:text-brand-700">{e}</button>)}
              </div>
            </div>
          )}
          {view?.messages.map((m, i) => (
            <MessageView key={m.id} message={m} isLast={i === view.messages.length - 1 && !busy} active={view.status === "active"} busy={busy}
              onChoose={(text) => send.mutate({ text })} onAction={(action) => send.mutate({ action })} />
          ))}
          {pendingText && <div className="flex justify-end"><div className="max-w-[34rem] rounded-2xl rounded-tr-sm bg-brand-600/70 px-4 py-2.5 text-sm text-white">{pendingText}</div></div>}
          {busy && <div className="flex items-center gap-2 text-sm text-slate-500" role="status"><span className="h-3 w-3 animate-pulse rounded-full bg-brand-500" />Checking the documentation…</div>}
          {view && <Banner view={view} />}
          {view && view.status === "resolved" && !busy && <FeedbackBox key={view.id} conversationId={view.id} existing={view.feedback} />}
          {closed && <div className="text-center"><Button variant="secondary" onClick={() => nav("/chat")}>Start a new conversation</Button></div>}
          {error != null && <ErrorNote error={error} />}
          <div ref={bottom} />
        </div>
      </div>

      <footer className="border-t border-slate-200 bg-white px-3 py-3 sm:px-6">
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <textarea aria-label="Message" rows={2} value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} disabled={!canReply || busy}
            placeholder={canReply ? "Describe the problem, or paste an error message…  (Enter to send, Shift+Enter for a new line)" : "This conversation is closed"}
            className="min-h-[3rem] flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500 disabled:bg-slate-50" />
          <Button onClick={submit} disabled={!canReply || busy || !draft.trim()}>Send</Button>
        </div>
      </footer>
    </div>
  );
}
