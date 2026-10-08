import { Link, NavLink, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api/client";
import Alerts from "./pages/Alerts";
import Connections from "./pages/Connections";
import DataSources from "./pages/DataSources";
import Jobs from "./pages/Jobs";
import Overview from "./pages/Overview";
import Settings from "./pages/Settings";
import WalletDetail from "./pages/WalletDetail";
import Wallets from "./pages/Wallets";

export default function App() {
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.jobs, refetchInterval: 10_000 });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
  const active = (jobs.data ?? []).filter((j) => ["queued", "running", "cancelling"].includes(j.status)).length;
  const healthy = health.data?.postgres === "ok" && health.data?.clickhouse === "ok";

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/" className="brand" style={{ color: "var(--ink)", textDecoration: "none" }}>
            <span className="brand-mark" aria-hidden="true" />
            <span>Chain<b>lens</b></span>
          </Link>
          <nav className="mainnav" aria-label="Main">
            <NavLink to="/" end>Overview</NavLink>
            <NavLink to="/wallets">Wallets</NavLink>
            <NavLink to="/connections">Connections</NavLink>
            <NavLink to="/alerts">Alerts</NavLink>
            <NavLink to="/data">Data</NavLink>
            <NavLink to="/jobs">Jobs{active > 0 && <span className="badge">{active}</span>}</NavLink>
            <NavLink to="/settings">Settings</NavLink>
          </nav>
          <div className="topbar-right">
            <span className={`live ${health.isError || (health.data && !healthy) ? "bad" : ""}`}
              title={health.data ? `PostgreSQL: ${health.data.postgres} · ClickHouse: ${health.data.clickhouse}` : "Checking the backend"}>
              <i /><span>{health.isError ? "API offline" : healthy ? "Live" : "Connecting"}</span>
            </span>
            <Link className="btn primary small" to="/data">+ Add data</Link>
          </div>
        </div>
      </header>
      <main className="page">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/wallets" element={<Wallets />} />
          <Route path="/wallets/:chain/:address" element={<WalletDetail />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/connections" element={<Connections />} />
          <Route path="/data" element={<DataSources />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<p>Page not found. <Link to="/">Go to the overview</Link>.</p>} />
        </Routes>
      </main>
    </>
  );
}
