import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api, hasStaffSession } from "../api/client";

/**
 * Root `/` must not send office users to staff registration.
 * - Saved staff JWT → scanner immediately.
 * - Otherwise: choose Portal (username/password) vs clinical staff flow.
 */
export default function HomePage() {
  const nav = useNavigate();
  const [dest, setDest] = useState<"/capture" | null>(null);
  const [staffBusy, setStaffBusy] = useState(false);

  useEffect(() => {
    if (hasStaffSession()) {
      setDest("/capture");
    }
  }, []);

  const continueStaff = async () => {
    setStaffBusy(true);
    try {
      await api.meStaff();
      setDest("/capture");
    } catch {
      nav("/register", { replace: true });
    } finally {
      setStaffBusy(false);
    }
  };

  if (dest) {
    return <Navigate to={dest} replace />;
  }

  return (
    <div className="min-h-dvh bg-brand-gradient-v flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="w-14 h-14 bg-brand-gradient rounded-2xl mx-auto mb-4 flex items-center justify-center shadow-card">
            <svg className="w-7 h-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>
          <h1 className="text-xl font-bold text-ink">RVU Insight</h1>
          <p className="text-sm text-ink-secondary mt-1">Mid Florida Surgical</p>
        </div>

        <div className="card p-6 mb-4">
          <p className="label text-brand-blue mb-3">Practice office</p>
          <p className="text-sm text-ink-secondary mb-4">
            Sign in with the username and password your practice set up for the RVU portal (scans, staff, devices, settings).
          </p>
          <Link to="/portal/login" className="btn-primary w-full py-3.5 text-center block text-base">
            Portal login
          </Link>
        </div>

        <div className="card p-6 border border-brand-border">
          <p className="label mb-3">Clinical staff</p>
          <p className="text-sm text-ink-secondary mb-4">
            Use the registration link from your office on this phone or computer, then open the scanner.
          </p>
          <div className="flex flex-col gap-2">
            <button
              type="button"
              disabled={staffBusy}
              onClick={() => void continueStaff()}
              className="btn-primary w-full py-3 text-sm"
            >
              {staffBusy ? "Checking…" : "Continue to scanner"}
            </button>
            <Link to="/register" className="btn-secondary w-full py-2.5 text-sm text-center">
              Register with magic link
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
