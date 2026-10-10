import { NavLink, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { useStore } from "./store";
import { SynthsPage } from "./pages/Synths";
import { MixesPage } from "./pages/Mixes";
import { CollabPage } from "./pages/Collab";
import { HealthPage } from "./pages/Health";

export function App() {
  const userId = useStore((state) => state.userId);
  const setUserId = useStore((state) => state.setUserId);
  const connected = useStore((state) => state.connected);
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });

  const statusClass =
    health?.status === "ok" ? "ok" : health?.status === "degraded" ? "warn" : "bad";

  return (
    <div className="layout">
      <header className="topbar">
        <div className="row">
          <span className="brand">MixWeb</span>
          <span className={`badge ${statusClass}`}>
            {health ? `MixCore ${health.status}` : "MixCore недоступен"}
          </span>
          {health && <span className="badge">режим: {health.effective_mode}</span>}
          {health && health.library_tracks > 0 && (
            <span className="badge">треков: {health.library_tracks}</span>
          )}
          <span className={`badge ${connected ? "ok" : "warn"}`}>
            {connected ? "realtime: подключено" : "realtime: нет"}
          </span>
        </div>
        <div className="row">
          <label className="muted" htmlFor="user">
            Пользователь
          </label>
          <input id="user" value={userId} onChange={(event) => setUserId(event.target.value)} size={12} />
        </div>
      </header>

      <nav className="nav">
        <NavLink to="/">Синтезы</NavLink>
        <NavLink to="/mixes">Миксы</NavLink>
        <NavLink to="/collab">Совместные</NavLink>
        <NavLink to="/health">Состояние</NavLink>
      </nav>

      <main style={{ marginTop: 20 }}>
        <Routes>
          <Route path="/" element={<SynthsPage />} />
          <Route path="/mixes" element={<MixesPage />} />
          <Route path="/collab" element={<CollabPage />} />
          <Route path="/health" element={<HealthPage />} />
        </Routes>
      </main>
    </div>
  );
}