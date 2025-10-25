import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

/**
 * Shape of the theme context allowing consumers to inspect the current theme and toggle it.
 */
export interface ThemeContextValue {
  theme: "light" | "dark";
  setTheme: (theme: "light" | "dark") => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

const prefersDarkScheme = () => window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;

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
  const [theme, setThemeState] = useState<"light" | "dark">(() => {
    const stored = localStorage.getItem(STORAGE_KEY) as "light" | "dark" | null;
    if (stored === "light" || stored === "dark") {
      return stored;
    }
    return prefersDarkScheme() ? "dark" : "light";
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, theme);
    applyThemeClass(theme);
  }, [theme]);

  const setTheme = useCallback((value: "light" | "dark") => {
    setThemeState(value);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((current: "light" | "dark") => (current === "dark" ? "light" : "dark"));
  }, []);

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
