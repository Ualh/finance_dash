import defaultTheme from "tailwindcss/defaultTheme";
import forms from "@tailwindcss/forms";
import typography from "@tailwindcss/typography";

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["'Inter'", ...defaultTheme.fontFamily.sans],
      },
      colors: {
        brand: {
          50: "#f4f8ff",
          100: "#e9f1ff",
          200: "#c8dcff",
          300: "#a6c7ff",
          400: "#639bff",
          500: "#2563eb",
          600: "#1d4ed8",
          700: "#1e3fa8",
          800: "#1f2f78",
          900: "#111d4a",
        },
      },
    },
  },
  plugins: [forms, typography],
};
