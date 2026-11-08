import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// App-shell service worker (production only; it never caches /api responses).
if ("serviceWorker" in navigator && import.meta.env.PROD && import.meta.env.VITE_MOCK !== "1") {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* non-fatal: app works without it */
    });
  });
}
