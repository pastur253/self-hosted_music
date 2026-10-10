import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { useUserId } from "../store";
import type { GenerateResponse } from "../types";

export function SynthsPage() {
  const user = useUserId();
  const [selected, setSelected] = useState<string | null>(null);
  const { data, isLoading, error } = useQuery({ queryKey: ["synths"], queryFn: api.synths });
  const preview = useMutation({
    mutationFn: (code: string) => api.preview(code, user),
    onSuccess: (result: GenerateResponse) => setSelected(result.mix_id ? code : code),
  });

  const createAndGenerate = useMutation({
    mutationFn: async (code: string) => {
      const mix = await api.createMix({ owner_id: user, template_code: code, name: code });
      return api.generate(mix.mix_id, { reason: "manual" });
    },
  });

  const lastResult = createAndGenerate.data ?? preview.data;

  return (
    <section>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
        <h2 style={{ fontSize: 18, margin: 0 }}>Плейлисты-синтезы</h2>
        <div className="row">
          <span className="badge">каталог: {data?.items.length ?? "…"}</span>
          {data && data.mode !== "algo" && <span className="badge warn">режим: {data.mode}</span>}
          {data?.degraded_reason && <span className="badge warn">деградация: {data.degraded_reason}</span>}
        </div>
      </div>

      {error && <p className="error">Ошибка загрузки каталога: {String(error)}</p>}

      <div className="grid">
        {data?.items.map((item) => (
          <article className="card" key={item.code}>
            <h3>{item.name_ru}</h3>
            <p>{item.goal}</p>
            <div className="metrics">
              <span>длина: {item.length}</span>
              <span>период: {item.period}</span>
              <span>контекст: {item.context_types.join(", ") || "нет"}</span>
            </div>
            <div className="row" style={{ marginTop: 10 }}>
              <button onClick={() => preview.mutate(item.code)} disabled={preview.isPending}>
                Предпросмотр
              </button>
              <button
                className="primary"
                onClick={() => createAndGenerate.mutate(item.code)}
                disabled={createAndGenerate.isPending}
              >
                Создать
              </button>
              {selected === item.code && lastResult && <span className="badge ok">готово</span>}
            </div>
          </article>
        ))}
      </div>

      {isLoading && <p className="muted">Загрузка…</p>}
      {lastResult && (
        <div className="card" style={{ marginTop: 18 }}>
          <h3>{lastResult.title}</h3>
          <p>{lastResult.description}</p>
          <div className="metrics">
            <span>треков: {lastResult.track_ids.length}</span>
            <span>режим: {lastResult.mode}</span>
            <span>diversity: {lastResult.metrics.diversity}</span>
            <span>novelty: {lastResult.metrics.novelty}</span>
            <span>repeat: {lastResult.metrics.repeat_rate}</span>
            <span>записано: {lastResult.written ? "да" : "нет"}</span>
          </div>
          {lastResult.quality_problems.length > 0 && (
            <p className="error">Пороги качества: {lastResult.quality_problems.join("; ")}</p>
          )}
        </div>
      )}
    </section>
  );
}