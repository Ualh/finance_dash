import React from "react";
import { MoonIcon, SunIcon } from "@heroicons/react/24/outline";

import { useTheme } from "@/context/ThemeContext";
import { Button } from "@/components/ui/Button";

interface ThemeToggleProps {
  size?: "sm" | "md";
}

export const ThemeToggle: React.FC<ThemeToggleProps> = ({ size = "md" }) => {
  const { theme, toggleTheme } = useTheme();
  const Icon = theme === "dark" ? SunIcon : MoonIcon;
  const label = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";

  return (
    <Button
      variant="ghost"
      size={size}
      onClick={toggleTheme}
      aria-label={label}
      title={label}
      className="flex items-center gap-2"
    >
      <Icon className="h-4 w-4" />
      <span className="hidden text-sm font-medium md:inline">{theme === "dark" ? "Light" : "Dark"}</span>
    </Button>
  );
};
