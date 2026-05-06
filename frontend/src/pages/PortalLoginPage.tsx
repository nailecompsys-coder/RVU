import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";

export default function PortalLoginPage() {
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setErr(null);
    setBusy(true);
    try {
      await api.portalLogin(username.trim(), password);
      nav("/portal");
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Invalid credentials");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-dvh bg-brand-gradient-v flex items-center justify-center px-4">
      <div className="w-full max-w-sm">

        {/* Brand header */}
        <div className="text-center mb-8">
          <div className="w-16 h-16 bg-brand-gradient rounded-2xl mx-auto mb-4 flex items-center justify-center shadow-card">
            <svg className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-ink mb-1">RVU Insight Portal</h1>
          <p className="text-ink-secondary text-sm">Mid Florida Surgical</p>
        </div>

        {/* Login card */}
        <div className="card p-7">
          <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-5">
            <div>
              <label className="label">Username or email</label>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                disabled={busy}
                className="input"
                placeholder="admin@example.com"
              />
            </div>

            <div>
              <label className="label">Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                disabled={busy}
                className="input"
                placeholder="••••••••"
              />
            </div>

            {err && (
              <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-600">
                {err}
              </div>
            )}

            <button
              type="submit"
              disabled={busy || !username || !password}
              className="btn-primary w-full py-3.5 text-base mt-1"
            >
              {busy ? (
                <>
                  <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                  Signing in…
                </>
              ) : "Sign in"}
            </button>
          </form>
        </div>

        <p className="text-center text-xs text-ink-secondary mt-5">
          Use your RVU portal username and password (practice managers / office staff).
        </p>

        <div className="card p-5 mt-6 border border-brand-border">
          <p className="text-xs font-bold text-ink uppercase tracking-wide mb-2">Clinical staff</p>
          <p className="text-sm text-ink-secondary leading-relaxed mb-4">
            You don’t log in here. Use the <strong className="text-ink">magic link</strong> from your admin to register this phone or computer, then open the scanner or your workspace.
          </p>
          <div className="flex flex-col gap-2">
            <Link to="/register" className="btn-secondary text-sm py-2.5 justify-center text-center">
              Register with magic link
            </Link>
            <Link to="/staff" className="text-xs text-brand-blue text-center hover:underline">
              My workspace (after you’re registered)
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
