import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import type { Role } from "../api";
import { Button, ErrorNote, cx, inputClass } from "../components/ui";

export default function Login() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const [role, setRole] = useState<Role>("customer");
  const [username, setUsername] = useState("");
  const [passcode, setPasscode] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={user.role === "engineer" ? "/dashboard" : "/chat"} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), role, role === "engineer" ? passcode : undefined);
      nav(role === "engineer" ? "/dashboard" : "/chat", { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-full place-items-center bg-gradient-to-b from-brand-50 to-slate-50 p-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-5 flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-600 text-lg font-bold text-white">D</span>
          <div><h1 className="text-lg font-semibold text-slate-900">Docker Support Agent</h1><p className="text-sm text-slate-500">Evidence-first help, with a human on hand</p></div>
        </div>

        <div role="tablist" aria-label="Sign in as" className="mb-4 grid grid-cols-2 gap-1 rounded-lg bg-slate-100 p-1">
          {(["customer", "engineer"] as Role[]).map((r) => (
            <button key={r} type="button" role="tab" aria-selected={role === r} onClick={() => setRole(r)}
              className={cx("rounded-md px-3 py-1.5 text-sm font-medium capitalize", role === r ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700")}>
              {r === "customer" ? "I need help" : "Support engineer"}
            </button>
          ))}
        </div>

        <label className="mb-1 block text-sm font-medium text-slate-700" htmlFor="username">Username</label>
        <input id="username" className={inputClass} value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required minLength={2} placeholder="e.g. alice" />

        {role === "engineer" && (
          <>
            <label className="mb-1 mt-3 block text-sm font-medium text-slate-700" htmlFor="passcode">Engineer passcode</label>
            <input id="passcode" type="password" className={inputClass} value={passcode} onChange={(e) => setPasscode(e.target.value)} required />
          </>
        )}

        {error != null && <div className="mt-3"><ErrorNote error={error} /></div>}
        <Button type="submit" className="mt-5 w-full" disabled={busy || username.trim().length < 2}>{busy ? "Signing in…" : "Continue"}</Button>
        <p className="mt-4 text-xs text-slate-400">Demo sign-in: no password for customers. Do not expose this server publicly.</p>
      </form>
    </div>
  );
}
