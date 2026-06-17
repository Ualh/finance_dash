import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { useApiClient } from "@/hooks/useApiClient";

export interface ThemeContextValue {
  theme: "light" | "dark";
  setTheme: (theme: "light" | "dark") => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

const STORAGE_KEY = "finance_dash_theme";

function applyThemeClass(theme: "light" | "dark") {
  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("dark");
  } else {
    root.classList.remove("dark");
  }
}

type ThemeProviderProps = {
  children: React.ReactNode;
};

export const ThemeProvider: React.FC<ThemeProviderProps> = ({ children }: ThemeProviderProps) => {
  const api = useApiClient();
  const [theme, setThemeState] = useState<"light" | "dark">("light");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY) as "light" | "dark" | null;
    const localTheme = stored === "light" || stored === "dark" ? stored : null;

    api.getSetting("theme").then((res) => {
      if (res.value === "light" || res.value === "dark") {
        setThemeState(res.value);
      } else if (localTheme) {
        setThemeState(localTheme);
        api.setSetting("theme", localTheme).catch(() => {});
      }
    }).catch(() => {
      if (localTheme) {
        setThemeState(localTheme);
      }
    }).finally(() => {
      setLoaded(true);
    });
  }, [api]);

  useEffect(() => {
    if (!loaded) return;
    localStorage.setItem(STORAGE_KEY, theme);
    applyThemeClass(theme);
  }, [theme, loaded]);

  const setTheme = useCallback((value: "light" | "dark") => {
    setThemeState(value);
    api.setSetting("theme", value).catch(() => {});
  }, [api]);

  const toggleTheme = useCallback(() => {
    setThemeState((current: "light" | "dark") => {
      const next = current === "dark" ? "light" : "dark";
      api.setSetting("theme", next).catch(() => {});
      return next;
    });
  }, [api]);

  const value = useMemo<ThemeContextValue>(() => ({ theme, setTheme, toggleTheme }), [theme, setTheme, toggleTheme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
};

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}
