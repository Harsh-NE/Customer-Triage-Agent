import type { Message, Source, Step } from "../api";
import { splitQuestion } from "../format";
import { Badge, Button } from "./ui";

export function SourceList({ sources }: { sources: Source[] }) {
  if (!sources.length) return null;
  return (
    <div className="mt-3 border-t border-slate-100 pt-3">
      <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Sources</div>
      <ul className="space-y-1.5">
        {sources.map((s) => (
          <li key={s.id} id={`src-${s.id}`} className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-mono text-xs text-slate-400">[{s.id}]</span>
            <Badge tone={s.official ? "green" : "violet"} title={s.official ? "From the official Docker documentation" : "A community answer, not official documentation"}>
              {s.official ? "Official docs" : "Community answer"}
            </Badge>
            {s.url ? <a href={s.url} target="_blank" rel="noreferrer" className="text-brand-600 underline-offset-2 hover:underline">{s.title || s.url}</a> : <span>{s.title}</span>}
            {!s.official && s.license && <span className="text-xs text-slate-400">{s.license}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Steps({ steps }: { steps: Step[] }) {
  return (
    <ol className="mt-2 list-decimal space-y-2 pl-5 text-sm text-slate-700">
      {steps.map((s, i) => (
        <li key={i} className="whitespace-pre-wrap">
          {s.text}
          {s.evidence_ids.map((id) => <a key={id} href={`#src-${id}`} className="ml-1 rounded bg-slate-100 px-1 font-mono text-[11px] text-slate-500 hover:bg-brand-50 hover:text-brand-700">{id}</a>)}
        </li>
      ))}
    </ol>
  );
}

export function FixCard({ message, active, busy, onAction }: { message: Message; active: boolean; busy: boolean; onAction: (a: "resolved" | "not_fixed") => void }) {
  const p = message.payload as { diagnosis?: string; steps?: Step[]; verification?: string; sources?: Source[] };
  const hasStructure = !!p.steps?.length;
  return (
    <div className="max-w-[46rem] rounded-2xl rounded-tl-sm border border-slate-200 bg-white p-4 shadow-sm">
      {hasStructure ? (
        <>
          {p.diagnosis && <p className="text-sm font-medium text-slate-800">{p.diagnosis}</p>}
          <Steps steps={p.steps!} />
          {p.verification && <p className="mt-3 text-sm text-slate-600"><span className="font-medium">To confirm:</span> {p.verification}</p>}
          <SourceList sources={p.sources ?? []} />
        </>
      ) : <p className="whitespace-pre-wrap text-sm text-slate-700">{message.content}</p>}
      {active && (
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
          <span className="mr-1 text-sm text-slate-500">Did this resolve the issue?</span>
          <Button disabled={busy} onClick={() => onAction("resolved")}>That fixed it</Button>
          <Button variant="secondary" disabled={busy} onClick={() => onAction("not_fixed")}>Still not working</Button>
        </div>
      )}
    </div>
  );
}

export function QuestionCard({ message, active, busy, onChoose }: { message: Message; active: boolean; busy: boolean; onChoose: (text: string) => void }) {
  const options = (message.payload.options as string[] | undefined) ?? [];
  return (
    <div className="max-w-[40rem] rounded-2xl rounded-tl-sm border border-slate-200 bg-white p-4 shadow-sm">
      <p className="whitespace-pre-wrap text-sm text-slate-800">{splitQuestion(message.content, options)}</p>
      {active && options.length > 0 && (
        <div className="mt-3 flex flex-col items-stretch gap-2">
          {options.map((o) => <Button key={o} variant="secondary" disabled={busy} className="justify-start text-left" onClick={() => onChoose(o)}>{o}</Button>)}
          <Button variant="ghost" disabled={busy} className="justify-start" onClick={() => onChoose("None of these fit.")}>None of these fit</Button>
        </div>
      )}
    </div>
  );
}

export function MessageView({ message, isLast, active, busy, onChoose, onAction }: {
  message: Message; isLast: boolean; active: boolean; busy: boolean; onChoose: (t: string) => void; onAction: (a: "resolved" | "not_fixed") => void;
}) {
  const interactive = isLast && active;
  if (message.role === "customer") {
    return <div className="flex justify-end"><div className="max-w-[34rem] whitespace-pre-wrap rounded-2xl rounded-tr-sm bg-brand-600 px-4 py-2.5 text-sm text-white">{message.content}</div></div>;
  }
  if (message.role === "engineer") {
    return (
      <div className="flex justify-start"><div className="max-w-[40rem] rounded-2xl rounded-tl-sm border border-emerald-200 bg-emerald-50 px-4 py-2.5">
        <div className="mb-0.5 text-xs font-semibold text-emerald-700">Support engineer{message.author ? ` · ${message.author}` : ""}{message.kind === "resolution" ? " · resolution" : ""}</div>
        <p className="whitespace-pre-wrap text-sm text-slate-800">{message.content}</p>
      </div></div>
    );
  }
  if (message.kind === "fix") return <div className="flex justify-start"><FixCard message={message} active={interactive} busy={busy} onAction={onAction} /></div>;
  if (message.kind === "question") return <div className="flex justify-start"><QuestionCard message={message} active={interactive} busy={busy} onChoose={onChoose} /></div>;
  const tone = message.kind === "decline" ? "border-slate-200 bg-slate-100" : message.kind === "escalation" || message.role === "system" ? "border-amber-200 bg-amber-50" : "border-emerald-200 bg-emerald-50";
  return <div className="flex justify-start"><div className={`max-w-[40rem] rounded-2xl rounded-tl-sm border px-4 py-2.5 text-sm text-slate-800 ${tone}`}>{message.content}</div></div>;
}
