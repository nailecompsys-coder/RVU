import { Link } from "react-router-dom";

/**
 * Root `/` must not send office users to staff registration.
 * The browser portal is practice-office only; clinical capture now happens in
 * the native mobile app.
 */
export default function HomePage() {
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
      </div>
    </div>
  );
}
