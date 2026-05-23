import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

const HomePage = lazy(() => import("./pages/HomePage"));
const RegisterPage = lazy(() => import("./pages/RegisterPage"));
const StaffCapturePage = lazy(() => import("./pages/StaffCapturePage"));
const StaffHistoryPage = lazy(() => import("./pages/StaffHistoryPage"));
const StaffDonePage = lazy(() => import("./pages/StaffDonePage"));
const StaffWorkspacePage = lazy(() => import("./pages/StaffWorkspacePage"));
const PortalLoginPage = lazy(() => import("./pages/PortalLoginPage"));
const PortalDashboardPage = lazy(() => import("./pages/PortalDashboardPage"));

function RouteFallback() {
  return (
    <div className="min-h-dvh bg-surface-soft flex items-center justify-center px-6">
      <div className="card px-5 py-4 text-sm font-semibold text-ink-secondary">
        Loading...
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Suspense fallback={<RouteFallback />}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/capture" element={<StaffCapturePage />} />
        <Route path="/history" element={<StaffHistoryPage />} />
        <Route path="/done" element={<StaffDonePage />} />
        <Route path="/staff" element={<StaffWorkspacePage />} />
        <Route path="/portal/login" element={<PortalLoginPage />} />
        <Route path="/portal" element={<PortalDashboardPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
