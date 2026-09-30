import { useState } from "react";
import { Link, Outlet, useNavigate } from "react-router-dom";

import { resetDemoData, simulateInboundEmail } from "./api";

export default function App() {
  const [resetting, setResetting] = useState(false);
  const [emailing, setEmailing] = useState(false);
  const [headerNotice, setHeaderNotice] = useState<string | null>(null);
  const navigate = useNavigate();

  // Runs the same code as the 4-hourly scheduled email, then opens the
  // alert it raised. If the last email is still being handled, it opens
  // that one instead and says why.
  const handleEmail = async () => {
    setEmailing(true);
    setHeaderNotice(null);
    try {
      const delivery = await simulateInboundEmail();
      if (delivery.budget_exhausted) {
        setHeaderNotice(delivery.reason ?? "Today's demo budget is used up.");
        return;
      }
      navigate(`/alerts/${delivery.alert_id}`, {
        state: { notice: delivery.started ? "Inbound email received." : delivery.reason },
      });
    } finally {
      setEmailing(false);
    }
  };

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
        <div className="header-actions">
          <button className="email-button" disabled={emailing} onClick={handleEmail}>
            {emailing ? "Sending…" : "Simulate inbound email"}
          </button>
          <button className="reset-button" disabled={resetting} onClick={handleReset}>
            {resetting ? "Resetting…" : "Reset Alerts"}
          </button>
        </div>
      </header>
      {headerNotice && <p className="header-notice">{headerNotice}</p>}
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
