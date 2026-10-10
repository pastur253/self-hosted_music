import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useUserId } from "../store";

export function MixesPage() {
  const user = useUserId();
  const queryClient = useQueryClient();
  const [template, setTemplate] = useState("daily_mix");
  const { data: synths } = useQuery({ queryKey: ["synths"], queryFn: api.synths });
  const mixes = useQuery({ queryKey: ["mixes"], queryFn: api.mixes });

  const create = useMutation({
    mutationFn: async () => {
      const spec = synths?.items.find((item) => item.code === template);
      const mix = await api.createMix({
        owner_id: user,
        template_code: template,
        name: spec?.name_ru ?? template,
        length: spec?.length ?? 30,
      });
      return api.generate(mix.mix_id, {});
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["mixes"] }),
  });

  const regenerate = useMutation({
    mutationFn: (mixId: string) => api.generate(mixId, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["mixes"] }),
  });

  return (
    <section>
      <div className="card">
        <h3>Новый микс</h3>
        <div className="row">
          <select value={template} onChange={(event) => setTemplate(event.target.value)}>
            {synths?.items.map((item) => (
              <option key={item.code} value={item.code}>
                {item.name_ru}
              </option>
            ))}
          </select>
          <button className="primary" onClick={() => create.mutate()} disabled={create.isPending}>
            Создать и сгенерировать
          </button>
        </div>
        {create.error && <p className="error">{String(create.error)}</p>}
      </div>

      <table style={{ marginTop: 18 }}>
        <thead>
          <tr>
            <th>Микс</th>
            <th>Шаблон</th>
            <th>Владелец</th>
            <th>Плейлист Navidrome</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {mixes.data?.items.map((mix) => (
            <tr key={mix.mix_id}>
              <td>{mix.name}</td>
              <td className="muted">{mix.template_code}</td>
              <td className="muted">{mix.owner_id}</td>
              <td className="muted">{mix.navidrome_playlist_id || "—"}</td>
              <td style={{ textAlign: "right" }}>
                <button onClick={() => regenerate.mutate(mix.mix_id)} disabled={regenerate.isPending}>
                  Перегенерировать
                </button>
              </td>
            </tr>
          ))}
          {mixes.data?.items.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
                Миксов пока нет
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}