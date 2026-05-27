import { Routes, Route, Navigate } from "react-router-dom";
import { PublicLayout } from "./components/layout/PublicLayout";
import { PortalLayout } from "./components/layout/PortalLayout";
import { ProtectedRoute } from "./components/layout/ProtectedRoute";

import Home from "./pages/Home";
import Services from "./pages/Services";
import ServiceDetail from "./pages/ServiceDetail";
import Hosting from "./pages/Hosting";
import Docs from "./pages/Docs";
import Login from "./pages/Login";
import Register from "./pages/Register";
import NotFound from "./pages/NotFound";

import Dashboard from "./pages/portal/Dashboard";
import Instances from "./pages/portal/Instances";
import InstanceDetail from "./pages/portal/InstanceDetail";
import Databases from "./pages/portal/Databases";
import Logs from "./pages/portal/Logs";
import Backups from "./pages/portal/Backups";
import Invoices from "./pages/portal/Invoices";
import InvoiceDetail from "./pages/portal/InvoiceDetail";

export default function App() {
  return (
    <Routes>
      {/* Public */}
      <Route element={<PublicLayout />}>
        <Route path="/" element={<Home />} />
        <Route path="/services" element={<Services />} />
        <Route path="/services/register" element={<Register />} />
        <Route path="/services/:id" element={<ServiceDetail />} />
        <Route path="/hosting" element={<Hosting />} />
        <Route path="/docs" element={<Docs />} />
        <Route path="/login" element={<Login />} />
      </Route>

      {/* Authenticated portal. /my, /my/instances/* and /my/billing/*
          are served by Odoo as the SPA shell (see spa.py); ordering and
          checkout live on Odoo QWeb routes we navigate to directly. */}
      <Route element={<ProtectedRoute />}>
        <Route path="/my" element={<PortalLayout />}>
          <Route index element={<Dashboard />} />
          <Route path="instances" element={<Instances />} />
          <Route path="instances/:id" element={<InstanceDetail />} />
          <Route path="instances/:id/databases" element={<Databases />} />
          <Route path="instances/:id/logs" element={<Logs />} />
          <Route path="instances/:id/backups" element={<Backups />} />
          <Route path="billing" element={<Invoices />} />
          <Route path="billing/:id" element={<InvoiceDetail />} />
        </Route>
      </Route>

      <Route path="/404" element={<NotFound />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
