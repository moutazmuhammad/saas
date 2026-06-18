import { Routes, Route, Navigate } from "react-router-dom";
import * as React from "react";
import { PublicLayout } from "./components/layout/PublicLayout";
import { PortalLayout } from "./components/layout/PortalLayout";
import { ProtectedRoute } from "./components/layout/ProtectedRoute";
import { useSections } from "./lib/useSections";

import Home from "./pages/Home";
import Services from "./pages/Services";
import ServiceDetail from "./pages/ServiceDetail";
import Hosting from "./pages/Hosting";
import Docs from "./pages/Docs";
import DocArticle from "./pages/DocArticle";
import Help from "./pages/Help";
import Login from "./pages/Login";
import Register from "./pages/Register";
import NotFound from "./pages/NotFound";

import Instances from "./pages/portal/Instances";
import InstanceDetail from "./pages/portal/InstanceDetail";
import Databases from "./pages/portal/Databases";
import Environments from "./pages/portal/Environments";
import Code from "./pages/portal/Code";
import Logs from "./pages/portal/Logs";
import Backups from "./pages/portal/Backups";
import Metrics from "./pages/portal/Metrics";
import ShellPage from "./pages/portal/ShellPage";
import SqlPage from "./pages/portal/SqlPage";
import Invoices from "./pages/portal/Invoices";
import InvoiceDetail from "./pages/portal/InvoiceDetail";
import Settings from "./pages/portal/Settings";

// Hard guard: a disabled section's pages aren't reachable even by typing
// the URL. Sections default to enabled while loading, so we never flash a
// redirect before the config arrives.
function RequireSection({
  section,
  children,
}: {
  section: "services" | "hosting";
  children: React.ReactNode;
}) {
  const sections = useSections();
  if (!sections[section]) return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      {/* Public */}
      <Route element={<PublicLayout />}>
        <Route path="/" element={<Home />} />
        <Route path="/services" element={<RequireSection section="services"><Services /></RequireSection>} />
        {/* Generic sign-up — not section-gated, so it works hosting-only. */}
        <Route path="/register" element={<Register />} />
        <Route path="/services/register" element={<RequireSection section="services"><Register /></RequireSection>} />
        <Route path="/services/:id" element={<RequireSection section="services"><ServiceDetail /></RequireSection>} />
        <Route path="/hosting" element={<RequireSection section="hosting"><Hosting /></RequireSection>} />
        <Route path="/docs" element={<Docs />} />
        <Route path="/docs/:slug" element={<DocArticle />} />
        <Route path="/help" element={<Help />} />
        <Route path="/login" element={<Login />} />
      </Route>

      {/* Authenticated portal. /my, /my/instances/* and /my/billing/*
          are served by Odoo as the SPA shell (see spa.py); ordering and
          checkout live on Odoo QWeb routes we navigate to directly. */}
      <Route element={<ProtectedRoute />}>
        <Route path="/my" element={<PortalLayout />}>
          {/* Overview merged into Projects — the projects list is the home. */}
          <Route index element={<Navigate to="/my/instances" replace />} />
          <Route path="home" element={<Navigate to="/my/instances" replace />} />
          <Route path="instances" element={<Instances />} />
          <Route path="instances/:id" element={<InstanceDetail />} />
          <Route path="instances/:id/metrics" element={<Metrics />} />
          <Route path="instances/:id/environments" element={<Environments />} />
          <Route path="instances/:id/databases" element={<Databases />} />
          <Route path="instances/:id/code" element={<Code />} />
          <Route path="instances/:id/shell" element={<ShellPage />} />
          <Route path="instances/:id/sql" element={<SqlPage />} />
          <Route path="instances/:id/logs" element={<Logs />} />
          <Route path="instances/:id/backups" element={<Backups />} />
          <Route path="billing" element={<Invoices />} />
          <Route path="billing/:id" element={<InvoiceDetail />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      </Route>

      <Route path="/404" element={<NotFound />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
