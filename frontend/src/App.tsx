import { useState } from "react";
import { Link, Outlet } from "react-router-dom";

import { resetDemoData } from "./api";

export default function App() {
  const [resetting, setResetting] = useState(false);

  const handleReset = async () => {
    setResetting(true);
    try {
      await resetDemoData();
      // Every page fetches its own data on mount -- a full reload is the
      // simplest way to get every component (list, or whichever alert
      // detail page happens to be open) to pick up the fresh state,
      // without wiring up cross-component refresh plumbing for a single
      // utility button.
      window.location.href = "/";
    } catch {
      setResetting(false);
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <Link to="/" className="app-title">
            FleetAlert AI
          </Link>
          <p className="app-subtitle">
            Agentic investigation demo — fixed scenarios only, no free-text input.
          </p>
        </div>
        <button className="reset-button" disabled={resetting} onClick={handleReset}>
          {resetting ? "Resetting…" : "Reset Alerts"}
        </button>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
