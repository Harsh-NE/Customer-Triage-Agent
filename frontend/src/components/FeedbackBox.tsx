import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type Feedback } from "../api";
import { Button, ErrorNote, cx, inputClass } from "./ui";

export default function FeedbackBox({ conversationId, existing }: { conversationId: string; existing: Feedback }) {
  const qc = useQueryClient();
  const [rating, setRating] = useState<number>(existing.rating ?? 0);
  const [helpful, setHelpful] = useState<boolean | null>(existing.helpful);
  const [comment, setComment] = useState(existing.comment ?? "");
  const save = useMutation({
    mutationFn: () => api.feedback(conversationId, { rating: rating || undefined, helpful: helpful ?? undefined, comment: comment.trim() || undefined }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["conv", conversationId] }); qc.invalidateQueries({ queryKey: ["history"] }); },
  });
  const saved = save.isSuccess || existing.rating != null || existing.helpful != null;

  return (
    <div className="mx-auto w-full max-w-md rounded-xl border border-slate-200 bg-white p-4 text-center shadow-sm">
      <p className="text-sm font-medium text-slate-800">{saved ? "Thanks for the feedback" : "Was this helpful?"}</p>
      <div className="mt-2 flex items-center justify-center gap-1" role="group" aria-label="Rating">
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" aria-label={`${n} star${n > 1 ? "s" : ""}`} aria-pressed={rating >= n} onClick={() => setRating(n)}
            className={cx("text-2xl leading-none transition-colors", rating >= n ? "text-amber-400" : "text-slate-300 hover:text-amber-300")}>★</button>
        ))}
        <span className="mx-2 h-5 w-px bg-slate-200" />
        <Button variant={helpful === true ? "primary" : "secondary"} className="px-2.5 py-1" aria-pressed={helpful === true} onClick={() => setHelpful(true)}>👍</Button>
        <Button variant={helpful === false ? "primary" : "secondary"} className="px-2.5 py-1" aria-pressed={helpful === false} onClick={() => setHelpful(false)}>👎</Button>
      </div>
      <textarea className={cx(inputClass, "mt-3")} rows={2} placeholder="Anything we should know? (optional)" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} />
      {save.isError && <div className="mt-2"><ErrorNote error={save.error} /></div>}
      <Button className="mt-3" onClick={() => save.mutate()} disabled={save.isPending || (!rating && helpful === null && !comment.trim())}>{save.isPending ? "Saving…" : saved ? "Update feedback" : "Send feedback"}</Button>
    </div>
  );
}
