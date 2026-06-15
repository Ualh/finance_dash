import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./styles.css";
import { ThemeProvider } from "@/context/ThemeContext";
import { DisplayCurrencyProvider } from "@/context/DisplayCurrencyContext";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element not found. Ensure index.html contains #root div.");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <ThemeProvider>
      <DisplayCurrencyProvider>
        <App />
      </DisplayCurrencyProvider>
    </ThemeProvider>
  </React.StrictMode>
);
