import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import type { Role } from "./api";
import Login from "./pages/Login";
import ChatPage from "./pages/ChatPage";
import HistoryPage from "./pages/HistoryPage";
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const CasesPage = lazy(() => import("./pages/CasesPage"));
const CaseDetailPage = lazy(() => import("./pages/CaseDetailPage"));
const AnalyticsPage = lazy(() => import("./pages/AnalyticsPage"));
const CostPage = lazy(() => import("./pages/CostPage"));

function RequireRole({ role, children }: { role: Role; children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== role) return <Navigate to={user.role === "engineer" ? "/dashboard" : "/chat"} replace />;
  return <>{children}</>;
}

function Home() {
  const { user, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={user.role === "engineer" ? "/dashboard" : "/chat"} replace />;
}

export default function App() {
  return (
    <Suspense fallback={<Spinner />}>
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Layout />}>
        <Route path="/chat" element={<RequireRole role="customer"><ChatPage /></RequireRole>} />
        <Route path="/chat/:id" element={<RequireRole role="customer"><ChatPage /></RequireRole>} />
        <Route path="/history" element={<RequireRole role="customer"><HistoryPage /></RequireRole>} />
        <Route path="/dashboard" element={<RequireRole role="engineer"><DashboardPage /></RequireRole>} />
        <Route path="/cases" element={<RequireRole role="engineer"><CasesPage mode="escalated" /></RequireRole>} />
        <Route path="/all-cases" element={<RequireRole role="engineer"><CasesPage mode="all" /></RequireRole>} />
        <Route path="/cases/:id" element={<RequireRole role="engineer"><CaseDetailPage /></RequireRole>} />
        <Route path="/analytics" element={<RequireRole role="engineer"><AnalyticsPage /></RequireRole>} />
        <Route path="/cost" element={<RequireRole role="engineer"><CostPage /></RequireRole>} />
      </Route>
      <Route path="*" element={<Home />} />
    </Routes>
    </Suspense>
  );
}
