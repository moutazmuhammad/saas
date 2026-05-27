import * as React from "react";
import { api, ApiError, type ApiUser } from "@/lib/api";

interface RegisterForm {
  name: string;
  email: string;
  phone: string;
  company_name?: string;
  country_id: number | string;
  city: string;
  street?: string;
  password: string;
}

interface AuthContextValue {
  user: ApiUser | null;
  loading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  // phone-OTP registration (mirrors the Odoo saas.registration.otp flow)
  registerStart: (form: RegisterForm) => Promise<void>;
  registerResend: (phone: string) => Promise<void>;
  registerVerify: (form: RegisterForm & { otp: string }) => Promise<ApiUser>;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<ApiUser | null>(null);
  const [loading, setLoading] = React.useState(true);

  const refresh = React.useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me);
    } catch (e) {
      // auth_required is expected when logged out — not an error.
      setUser(null);
      if (!(e instanceof ApiError) || e.code !== "auth_required") {
        // Network/server problems: stay logged out, surfaced by callers.
      }
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    refresh();
  }, [refresh]);

  const login = React.useCallback(async (email: string, password: string) => {
    const me = await api.login(email, password);
    setUser(me);
  }, []);

  const logout = React.useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setUser(null);
    }
  }, []);

  const registerStart = React.useCallback(async (form: RegisterForm) => {
    await api.registerStart(form as unknown as Record<string, unknown>);
  }, []);

  const registerResend = React.useCallback(async (phone: string) => {
    await api.registerResend(phone);
  }, []);

  const registerVerify = React.useCallback(
    async (form: RegisterForm & { otp: string }) => {
      const me = await api.registerVerify(form as unknown as Record<string, unknown>);
      setUser(me);
      return me;
    },
    []
  );

  const value = React.useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      isAuthenticated: !!user,
      login,
      logout,
      refresh,
      registerStart,
      registerResend,
      registerVerify,
    }),
    [user, loading, login, logout, refresh, registerStart, registerResend, registerVerify]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = React.useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
