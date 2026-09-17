import { Link, Outlet } from "react-router-dom";

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <Link to="/" className="app-title">
          FleetAlert AI
        </Link>
        <p className="app-subtitle">
          Agentic investigation demo — fixed scenarios only, no free-text input.
        </p>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}
