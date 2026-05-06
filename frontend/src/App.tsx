import { Navigate, Route, Routes } from "react-router-dom";
import RegisterPage from "./pages/RegisterPage";
import StaffCapturePage from "./pages/StaffCapturePage";
import StaffHistoryPage from "./pages/StaffHistoryPage";
import PortalLoginPage from "./pages/PortalLoginPage";
import PortalDashboardPage from "./pages/PortalDashboardPage";
import HomePage from "./pages/HomePage";
import StaffDonePage from "./pages/StaffDonePage";
import StaffWorkspacePage from "./pages/StaffWorkspacePage";

export default function App() {
  return (
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
  );
}
