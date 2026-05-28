import * as React from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "veltnex-theme";

function getInitialTheme(): Theme {
  // The inline FOUC script in index.html has already set the class on
  // <html> before React mounts; mirror that decision here so the React
  // state matches what the user sees from frame 0.
  if (typeof document !== "undefined") {
    if (document.documentElement.classList.contains("dark")) return "dark";
    if (document.documentElement.classList.contains("light")) return "light";
  }
  return "dark";
}

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  // Mirror as a data-attribute too — QWeb pages and the DB manager
  // read it the same way, keeping one source of truth across the SPA
  // and the Odoo-rendered shell.
  root.setAttribute("data-theme", theme);
}

/**
 * Returns the active theme and a setter. Persists to localStorage and
 * applies the class to <html>. Listens for OS-level preference changes
 * only when the user hasn't picked an explicit theme.
 */
export function useTheme(): {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggle: () => void;
} {
  const [theme, setThemeState] = React.useState<Theme>(getInitialTheme);

  const setTheme = React.useCallback((t: Theme) => {
    try {
      localStorage.setItem(STORAGE_KEY, t);
    } catch {
      // localStorage may be disabled in private mode — apply anyway.
    }
    applyTheme(t);
    setThemeState(t);
  }, []);

  const toggle = React.useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [theme, setTheme]);

  // Sync across tabs.
  React.useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY && (e.newValue === "dark" || e.newValue === "light")) {
        applyTheme(e.newValue);
        setThemeState(e.newValue);
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  // Follow OS preference if the user hasn't expressed one.
  React.useEffect(() => {
    if (!window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (e: MediaQueryListEvent) => {
      try {
        if (localStorage.getItem(STORAGE_KEY)) return; // explicit choice wins
      } catch {
        // fall through
      }
      const next: Theme = e.matches ? "dark" : "light";
      applyTheme(next);
      setThemeState(next);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  return { theme, setTheme, toggle };
}
