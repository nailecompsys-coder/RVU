import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

function forceFreshLoadOnOpen() {
  try {
    const url = new URL(window.location.href);
    const hasRefreshFlag = url.searchParams.get("__refresh") === "1";
    const marker = "__rvu_fresh_loaded";

    // Force one cache-busting reload for each new app open/session.
    if (!sessionStorage.getItem(marker) && !hasRefreshFlag) {
      sessionStorage.setItem(marker, "1");
      url.searchParams.set("__refresh", "1");
      url.searchParams.set("v", String(Date.now()));
      window.location.replace(url.toString());
      return true;
    }

    // Clean URL after forced refresh.
    if (hasRefreshFlag) {
      url.searchParams.delete("__refresh");
      url.searchParams.delete("v");
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    }
  } catch {
    // no-op
  }
  return false;
}

if (forceFreshLoadOnOpen()) {
  // stop normal render until reloaded
} else {
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>
);
}
