import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api/client";

export default function RegisterPage() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const initial = useMemo(() => params.get("token") ?? "", [params]);
  const [token, setToken] = useState(initial);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [surgeon, setSurgeon] = useState<string | null>(null);

  useEffect(() => {
    api.meStaff().then(() => nav("/capture", { replace: true })).catch(() => {});
  }, [nav]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const r = await api.register(token.trim());
      const name = (r.surgeon as Record<string, unknown>)?.full_name as string | undefined;
      setSurgeon(name ?? "You");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  };

  if (surgeon) {
    return (
      <div className="min-h-dvh bg-brand-gradient-v flex items-center justify-center px-4">
        <div className="text-center max-w-sm w-full">
          <div className="w-20 h-20 bg-brand-gradient rounded-3xl mx-auto mb-6 flex items-center justify-center shadow-card">
            <svg className="w-10 h-10 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-ink mb-2">You're in!</h1>
          <p className="text-ink-secondary text-sm mb-8 leading-relaxed">
            Welcome, <strong className="text-ink">{surgeon}</strong>.<br />This device is now registered.
          </p>
          <Link
            to="/capture"
            className="btn-primary w-full py-3.5 text-base justify-center"
          >
            Open RVU Estimator
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 7l5 5m0 0l-5 5m5-5H6" />
            </svg>
          </Link>
          <p className="text-center text-xs text-ink-secondary mt-4">
            On a computer?{" "}
            <Link to="/staff" className="text-brand-blue font-semibold hover:underline">My workspace</Link>
            {" "}has scanner + history links.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-dvh bg-brand-gradient-v flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-sm">

        {/* Header */}
        <div className="text-center mb-8">
          <div className="w-16 h-16 bg-brand-gradient rounded-2xl mx-auto mb-4 flex items-center justify-center shadow-card">
            <svg className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-ink mb-1">Register this device</h1>
          <p className="text-ink-secondary text-sm">RVU Insight · Mid Florida Surgical</p>
        </div>

        {/* Card */}
        <div className="card p-7 mb-4">
          {initial ? (
            <div className="text-center">
              <div className="w-12 h-12 bg-brand-muted rounded-2xl mx-auto mb-4 flex items-center justify-center">
                <svg className="w-6 h-6 text-brand-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round"
                    d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                </svg>
              </div>
              <p className="text-sm text-ink-secondary mb-6 leading-relaxed">
                Your magic link was detected. Tap below to register this device and open the app.
              </p>
              {err && (
                <div className="badge-red w-full rounded-xl px-4 py-3 text-sm mb-5 text-left">
                  {err}
                </div>
              )}
              <button
                type="button"
                disabled={busy}
                onClick={(e) => void submit(e as unknown as React.FormEvent)}
                className="btn-primary w-full py-3.5 text-base"
              >
                {busy ? (
                  <>
                    <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                    </svg>
                    Registering…
                  </>
                ) : "Register this device"}
              </button>
            </div>
          ) : (
            <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-5">
              <p className="text-sm text-ink-secondary leading-relaxed">
                Paste the token from your magic link email below.
              </p>
              <div>
                <label className="label">Token</label>
                <textarea
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="Paste token here…"
                  rows={3}
                  className="input font-mono text-xs resize-y"
                />
              </div>
              {err && (
                <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-600">
                  {err}
                </div>
              )}
              <button
                type="submit"
                disabled={busy || !token.trim()}
                className="btn-primary w-full py-3.5 text-base"
              >
                {busy ? "Registering…" : "Register"}
              </button>
            </form>
          )}
        </div>

        <p className="text-center text-xs text-ink-secondary">
          Link expired?{" "}
          <span className="text-ink">Contact your admin to send a new one.</span>
        </p>
        <p className="text-center text-xs text-ink-secondary mt-4">
          Office / admin?{" "}
          <Link to="/portal/login" className="text-brand-blue font-semibold hover:underline">Portal login</Link>
          {" · "}
          <Link to="/" className="text-brand-blue font-semibold hover:underline">Home</Link>
        </p>
      </div>
    </div>
  );
}
