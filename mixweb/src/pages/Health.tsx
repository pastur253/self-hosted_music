import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

export function HealthPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 10_000 });
  const sync = useQuery({ queryKey: ["library"], queryFn: api.syncLibrary, enabled: false });

  if (isLoading) return <p className="muted">Проверка состояния…</p>;
  if (error || !data) return <p className="error">MixCore недоступен: {String(error)}</p>;

  return (
    <section>
      <div className="grid">
        <div className="card">
          <h3>Состояние</h3>
          <p>
            Версия {data.version}, схема состояния {data.schema_version ?? "?"}
          </p>
          <div className="metrics">
            <span>Navidrome: {data.navidrome.status}</span>
            <span>режим: {data.effective_mode}</span>
            <span>модули: {data.enabled_modules.join(", ") || "нет"}</span>
          </div>
        </div>

        <div className="card">
          <h3>Хранилище</h3>
          <p>{data.storage.state_dir}</p>
          <div className="metrics">
            <span>событий: {data.storage.play_events}</span>
            <span>треков в кэше: {data.library_tracks}</span>
            <span>хранение: {data.storage.mode}</span>
          </div>
        </div>

        <div className="card">
          <h3>ИИ-контур</h3>
          {data.ai.map((module) => (
            <div key={module.name} className="metrics">
              <span className={`badge ${module.available ? "ok" : "warn"}`}>
                {module.name}: {module.available ? "доступен" : module.reason}
              </span>
            </div>
          ))}
          <div className="row" style={{ marginTop: 8 }}>
            <button onClick={() => sync.mutate()} disabled={sync.isPending}>
              Синхронизировать библиотеку
            </button>
            {sync.data && <span className="badge ok">треков: {sync.data.total}</span>}
          </div>
        </div>

        <div className="card">
          <h3>Погода и контекст</h3>
          <div className="metrics">
            <span>провайдер: {data.weather_provider}</span>
            <span>деградация: {data.degraded_reason || "нет"}</span>
          </div>
          <div className="metrics">
            <span>uptime: {Math.round(data.uptime_seconds)} c</span>
          </div>
        </div>
      </div>
    </section>
  );
}