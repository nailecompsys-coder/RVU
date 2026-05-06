import { Link } from "react-router-dom";

/** Clear “I’m finished” screen so the app doesn’t feel stuck after a save. */
export default function StaffDonePage() {
  return (
    <div className="min-h-dvh bg-brand-gradient-v flex items-center justify-center px-4 py-10">
      <div className="max-w-sm w-full card p-8 text-center">
        <div className="w-16 h-16 bg-brand-muted rounded-2xl mx-auto mb-5 flex items-center justify-center">
          <svg className="w-8 h-8 text-brand-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 className="text-xl font-bold text-ink mb-2">You&apos;re all set</h1>
        <p className="text-sm text-ink-secondary leading-relaxed mb-6">
          Your estimate is saved under <strong className="text-ink">History</strong> if you tapped save.
          You can close this screen — use the app switcher, swipe home, or lock your phone.
        </p>
        <div className="flex flex-col gap-3">
          <Link to="/capture" className="btn-primary w-full py-3 justify-center">
            Scan another charge
          </Link>
          <Link to="/history" className="btn-secondary w-full py-3 justify-center">
            View my history
          </Link>
        </div>
      </div>
    </div>
  );
}
