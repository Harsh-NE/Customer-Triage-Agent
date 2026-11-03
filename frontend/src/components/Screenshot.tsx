import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { api, type Attachment } from "../api";
import { Button, Spinner } from "./ui";

/** A screenshot the customer has picked: the file (for the preview), what the server read from it, and the text they will send. */
export interface Shot { previewUrl: string; fileName: string; attachment: Attachment; text: string }

export const ACCEPT = "image/png,image/jpeg,image/bmp,image/tiff,image/webp";

/** The paperclip button: opens the file picker and hands the chosen file up. */
export function ScreenshotButton({ disabled, onPick }: { disabled?: boolean; onPick: (file: File) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const change = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";                                     // picking the same file again must still fire
    if (file) onPick(file);
  };
  return (
    <>
      <input ref={input} type="file" accept={ACCEPT} className="hidden" aria-label="Attach a screenshot" onChange={change} data-testid="screenshot-input" />
      <Button type="button" variant="secondary" disabled={disabled} onClick={() => input.current?.click()} title="Attach a screenshot of the error">
        <span aria-hidden>📎</span> Screenshot
      </Button>
    </>
  );
}

/** What was read from the screenshot, editable, so a wrong read is corrected before it is used. */
export function ScreenshotCard({ shot, onText, onRemove, disabled }: { shot: Shot; onText: (t: string) => void; onRemove: () => void; disabled?: boolean }) {
  const ocr = shot.attachment.ocr;
  const note = !ocr.ok
    ? "I couldn't read any text in this screenshot. Please type the error message in the box below, or in your message."
    : ocr.low_confidence
      ? "The text was hard to read, so it may be wrong. Please check it and fix anything that's off."
      : "This is what I read from your screenshot. Fix anything that's wrong before sending.";
  return (
    <div className="mx-auto mb-2 flex max-w-3xl gap-3 rounded-lg border border-slate-200 bg-slate-50 p-2" data-testid="screenshot-card">
      <img src={shot.previewUrl} alt={`Preview of ${shot.fileName}`} className="h-20 w-28 flex-none rounded border border-slate-200 bg-white object-contain" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <p className={`text-xs ${ocr.ok && !ocr.low_confidence ? "text-slate-500" : "text-amber-700"}`} role={ocr.ok ? undefined : "alert"}>{note}</p>
          <button type="button" onClick={onRemove} disabled={disabled} className="flex-none text-xs font-medium text-slate-500 hover:text-red-600" aria-label="Remove screenshot">Remove</button>
        </div>
        <textarea aria-label="Text from the screenshot" rows={3} value={shot.text} onChange={(e) => onText(e.target.value)} disabled={disabled}
          placeholder="Type the error message shown in the screenshot"
          className="mt-1 w-full resize-y rounded border border-slate-300 bg-white px-2 py-1 font-mono text-xs focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500" />
      </div>
    </div>
  );
}

/** The card shown while the server is reading the image. */
export function ScreenshotReading({ previewUrl }: { previewUrl: string }) {
  return (
    <div className="mx-auto mb-2 flex max-w-3xl items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 p-2" role="status">
      <img src={previewUrl} alt="Screenshot being read" className="h-14 w-20 rounded border border-slate-200 bg-white object-contain" />
      <Spinner /><span className="text-sm text-slate-500">Reading the screenshot…</span>
    </div>
  );
}

/** A screenshot that was sent: the stored image (fetched with the login token) and, folded away, the text read from it. */
export function SentScreenshot({ conversationId, attachment, dark = true }: { conversationId: string; attachment: { id: string; text: string }; dark?: boolean }) {
  const fg = dark ? "text-white/90" : "text-slate-600";
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    let made: string | null = null;
    api.attachmentImage(conversationId, attachment.id)
      .then((u) => { made = u; if (live) setUrl(u); else URL.revokeObjectURL(u); })
      .catch(() => live && setFailed(true));
    return () => { live = false; if (made) URL.revokeObjectURL(made); };
  }, [conversationId, attachment.id]);
  return (
    <div className="mt-2 space-y-1">
      {url && <a href={url} target="_blank" rel="noreferrer"><img src={url} alt="Screenshot you attached" className="max-h-40 rounded border border-slate-300 bg-white object-contain" /></a>}
      {failed && <div className={`text-xs ${fg}`}>(screenshot not available)</div>}
      {attachment.text && (
        <details className={`text-xs ${fg}`}>
          <summary className="cursor-pointer select-none">Text read from the screenshot</summary>
          <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px]">{attachment.text}</pre>
        </details>
      )}
    </div>
  );
}
