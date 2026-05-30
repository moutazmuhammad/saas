/**
 * Client for the saas_website JSON API (Odoo `type='json'` / JSON-RPC 2.0).
 *
 * Every backend endpoint returns our envelope `{ ok, data }` or
 * `{ ok, error, code }` inside the JSON-RPC `result`. This module unwraps
 * that and throws a typed `ApiError` so callers can `try/catch`.
 */

export class ApiError extends Error {
  code: string;
  constructor(message: string, code = "error") {
    super(message);
    this.name = "ApiError";
    this.code = code;
  }
}

let rpcId = 0;

async function rpc<T = unknown>(
  path: string,
  params: Record<string, unknown> = {}
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params,
        id: ++rpcId,
      }),
    });
  } catch {
    throw new ApiError(
      "We couldn't reach the server. Check your connection and try again.",
      "network"
    );
  }

  if (!res.ok) {
    throw new ApiError("Something went wrong. Please try again.", "http_" + res.status);
  }

  const payload = await res.json();

  // JSON-RPC transport-level error (e.g. session expired, server crash).
  if (payload.error) {
    const data = payload.error.data || {};
    const name: string = data.name || "";
    if (name.includes("SessionExpired") || name.includes("AccessDenied")) {
      throw new ApiError("Your session has expired. Please sign in again.", "auth_required");
    }
    throw new ApiError(
      data.message || payload.error.message || "Server error.",
      "server"
    );
  }

  const result = payload.result;
  if (result && typeof result === "object" && "ok" in result) {
    if (!result.ok) {
      throw new ApiError(result.error || "Request failed.", result.code || "error");
    }
    return result.data as T;
  }
  return result as T;
}

/* ────────────────────────────── Types ────────────────────────────── */

export interface ApiUser {
  id: number;
  name: string;
  email: string;
  company: string;
  initials: string;
  phone: string;
  /** True for Odoo internal/backend users (shows a "Backend" menu link). */
  is_internal?: boolean;
}

export interface PriceResult {
  workers: number;
  storage: number;
  billing: "monthly" | "yearly";
  total: number;
  monthly_equivalent: number;
  yearly_savings: number;
  savings_percent: number;
  currency: string;
  limits: {
    workers: { min: number; max: number };
    storage: { min: number; max: number };
  };
}

export interface PlanConfigMeta {
  worker_price: number;
  storage_price_per_gb: number;
  min_workers: number;
  max_workers: number;
  min_storage: number;
  max_storage: number;
  yearly_discount_pct: number;
  currency: string;
}

export interface TrialInfo {
  days: number;
  services_available: boolean;
  hosting_available: boolean;
}

export interface Meta {
  hosting_config: PlanConfigMeta;
  custom_config: PlanConfigMeta;
  trial: TrialInfo;
  sections: { services: boolean; hosting: boolean };
  support_email: string;
  countries: { id: number; name: string; code: string }[];
  domains: { id: number; name: string }[];
  hosting_versions: { id: number; name: string }[];
}

export interface ApiService {
  id: number;
  name: string;
  tagline: string;
  icon: string;
  is_hosting: boolean;
  image_url: string;
  highlights?: string[];
  description?: string;
  trial_plan_id?: number;
  features?: { title: string; description: string }[];
  plans?: {
    id: number;
    name: string;
    workers: number;
    storage_gb: number;
    is_trial: boolean;
    recommended_users: number;
  }[];
}

export type InstanceState =
  | "draft"
  | "pending_payment"
  | "paid"
  | "pending_provision"
  | "provisioning"
  | "running"
  | "stopped"
  | "suspended"
  | "failed"
  | "cancelled"
  | "cancelled_by_client";

export interface ApiUsage {
  cpu: number;
  ram: number;
  storage: number;
}

export interface ApiBackup {
  id: number;
  label: string;
  type: "manual" | "automatic";
  size_mb: number;
  created: string;
  status: "available" | "in_progress" | "failed";
  download_url: string;
  is_full_instance: boolean;
  db_name?: string;
  format?: string;
}

export interface ApiInvoice {
  id: number;
  number: string;
  status: "paid" | "open" | "overdue" | "draft";
  issued: string;
  due: string;
  total: number;
  residual: number;
  currency: string;
  currency_symbol: string;
  instance_name: string;
  portal_url: string;
  payable: boolean;
  lines?: { description: string; quantity: number; total: number }[];
  subtotal?: number;
  tax?: number;
}

export interface ApiInstance {
  id: number;
  name: string;
  domain: string;
  url: string;
  region: string;
  version: string;
  state: InstanceState;
  state_label: string;
  workers: number;
  storage_gb: number;
  billing_cycle: "monthly" | "yearly";
  created: string;
  is_hosting: boolean;
  is_trial: boolean;
  usage: ApiUsage;
  access_token: string;
  // detail-only
  plan_name?: string;
  next_invoice_date?: string;
  daily_backup_enabled?: boolean;
  pending_plan?: string;
  scheduled_plan?: string;
  backups?: ApiBackup[];
  invoices?: ApiInvoice[];
  has_unpaid_invoice?: boolean;
  checkout_url?: string;
}

export interface DashboardData {
  instances: ApiInstance[];
  recent_invoices: ApiInvoice[];
  stats: {
    instances: number;
    running: number;
    open_invoices: number;
    outstanding: number;
  };
}

export interface StatusData {
  id: number;
  state: InstanceState;
  state_label: string;
  url: string;
  usage?: ApiUsage;
  backup_running: boolean;
  db_ops_running: boolean;
}

export interface DbListData {
  databases: { name: string; login: string }[];
  ready: boolean;
  state?: InstanceState;
  /** Instance host, e.g. https://acme.veltnex.com. A specific DB is
   *  opened at `${url}/web?db=${name}` (all DBs share the host). */
  url?: string;
  pending_ops?: { db_name: string; operation: string }[];
}

/* ──────────────────────────── Endpoints ──────────────────────────── */

export const api = {
  // session / account
  me: () => rpc<ApiUser>("/saas/api/v1/me"),
  login: (login: string, password: string) =>
    rpc<ApiUser>("/saas/api/v1/auth/login", { login, password }),
  logout: () => rpc("/saas/api/v1/auth/logout"),
  // `debug_otp` is a TODO-remove testing aid surfaced by the backend.
  registerStart: (form: Record<string, unknown>) =>
    rpc<{ otp_sent: boolean; debug_otp?: string }>("/saas/api/v1/auth/register/start", form),
  registerResend: (phone: string) =>
    rpc<{ otp_sent: boolean; debug_otp?: string }>("/saas/api/v1/auth/register/resend", { phone }),
  registerVerify: (form: Record<string, unknown>) =>
    rpc<ApiUser>("/saas/api/v1/auth/register/verify", form),

  // public
  meta: () => rpc<Meta>("/saas/api/v1/meta"),
  services: () => rpc<ApiService[]>("/saas/api/v1/services"),
  service: (id: number) => rpc<ApiService>(`/saas/api/v1/services/${id}`),
  hostingCalculate: (workers: number, storage: number, billing: string) =>
    rpc<PriceResult>("/saas/api/v1/hosting/calculate", { workers, storage, billing }),
  servicesCalculate: (workers: number, storage: number, billing: string) =>
    rpc<PriceResult>("/saas/api/v1/services/calculate", { workers, storage, billing }),
  checkSubdomain: (subdomain: string, domain_id: number) =>
    rpc<{ available: boolean; message: string }>("/saas/api/v1/check-subdomain", {
      subdomain,
      domain_id,
    }),

  // portal
  dashboard: () => rpc<DashboardData>("/saas/api/v1/dashboard"),
  instances: (itype?: string) =>
    rpc<ApiInstance[]>("/saas/api/v1/instances", itype ? { itype } : {}),
  instance: (id: number, accessToken?: string) =>
    rpc<ApiInstance>(`/saas/api/v1/instances/${id}`, accessToken ? { access_token: accessToken } : {}),
  instanceStatus: (id: number) => rpc<StatusData>(`/saas/api/v1/instances/${id}/status`),
  instanceAction: (id: number, action: string) =>
    rpc<StatusData>(`/saas/api/v1/instances/${id}/action`, { action }),

  databases: (id: number) => rpc<DbListData>(`/saas/api/v1/instances/${id}/databases`),
  dbCreate: (id: number, name: string, login: string, password: string) =>
    rpc<{ db_name: string }>(`/saas/api/v1/instances/${id}/databases/create`, {
      name,
      login,
      password,
    }),
  dbDrop: (id: number, name: string) =>
    rpc<{ db_name: string }>(`/saas/api/v1/instances/${id}/databases/drop`, { name }),
  dbBackup: (id: number, name: string, format: "zip" | "dump" = "zip") =>
    rpc(`/saas/api/v1/instances/${id}/databases/backup`, { name, format }),
  dbResetPassword: (id: number, name: string, new_password: string, login?: string) =>
    rpc<{ login: string }>(`/saas/api/v1/instances/${id}/databases/reset-password`, {
      name,
      new_password,
      login: login || undefined,
    }),

  backups: (id: number) => rpc<ApiBackup[]>(`/saas/api/v1/instances/${id}/backups`),
  backupCreate: (id: number) => rpc(`/saas/api/v1/instances/${id}/backups/create`),

  invoices: () => rpc<ApiInvoice[]>("/saas/api/v1/invoices"),
  invoice: (id: number) => rpc<ApiInvoice>(`/saas/api/v1/invoices/${id}`),
};

/** SSE URL for an instance's live container logs (served by saas_core). */
export function logStreamUrl(instanceId: number, tail = 100) {
  return `/saas/instance/${instanceId}/logs/stream?tail=${tail}`;
}
