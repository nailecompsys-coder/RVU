import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type StaffMe } from "../api/client";

/**
 * Clinical staff “portal” on a desktop browser: same magic-link registration as mobile,
 * then this hub links to scanner + history. No admin password required.
 */
export default function StaffWorkspacePage() {
  const [me, setMe] = useState<StaffMe | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.meStaff()
      .then(setMe)
      .catch(() => {
        setErr("This browser isn’t registered yet.");
      });
  }, []);

  if (err) {
    return (
      <div className="min-h-dvh bg-brand-gradient-v flex items-center justify-center px-4">
        <div className="max-w-md w-full card p-8 text-center">
          <h1 className="text-lg font-bold text-ink mb-2">Register this browser</h1>
          <p className="text-sm text-ink-secondary mb-6">
            Open the <strong>magic link</strong> your admin emailed you (or paste the token). Clinical staff
            does not use the admin login — that’s only for practice managers.
          </p>
          <Link to="/register" className="btn-primary w-full py-3 justify-center">
            Register with magic link
          </Link>
        </div>
      </div>
    );
  }

  if (!me) {
    return (
      <div className="min-h-dvh bg-brand-gradient-v flex items-center justify-center">
        <div className="w-10 h-10 border-2 border-brand-blue border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="min-h-dvh bg-surface-soft px-4 py-8">
      <div className="max-w-lg mx-auto">
        <header className="mb-8">
          <p className="text-xs font-semibold text-ink-secondary uppercase tracking-wide mb-1">My workspace</p>
          <h1 className="text-2xl font-bold text-ink">{me.full_name}</h1>
          <p className="text-sm text-ink-secondary mt-1">Scanner &amp; saved estimates on this device</p>
        </header>

        <div className="grid gap-4">
          <Link
            to="/capture"
            className="card p-6 flex items-center gap-4 hover:border-brand-blue/40 transition-colors"
          >
            <div className="w-12 h-12 bg-brand-gradient rounded-xl flex items-center justify-center flex-shrink-0">
              <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round"
                  d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </div>
            <div className="text-left flex-1">
              <div className="font-bold text-ink">Open scanner</div>
              <div className="text-sm text-ink-secondary">Snap a charge screen or paste CPT text</div>
            </div>
            <span className="text-brand-blue font-semibold text-sm">→</span>
          </Link>

          <Link
            to="/history"
            className="card p-6 flex items-center gap-4 hover:border-brand-blue/40 transition-colors"
          >
            <div className="w-12 h-12 bg-brand-muted rounded-xl flex items-center justify-center flex-shrink-0">
              <svg className="w-6 h-6 text-brand-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div className="text-left flex-1">
              <div className="font-bold text-ink">My history</div>
              <div className="text-sm text-ink-secondary">Estimates you saved from this app</div>
            </div>
            <span className="text-brand-blue font-semibold text-sm">→</span>
          </Link>

          <Link
            to="/done"
            className="card p-6 text-left w-full hover:border-brand-border transition-colors block"
          >
            <div className="font-bold text-ink">Finished for now</div>
            <div className="text-sm text-ink-secondary mt-1">Open done screen</div>
          </Link>
        </div>
      </div>
    </div>
  );
}
